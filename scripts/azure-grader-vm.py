"""Install and connect the dedicated Trellis POC grader without opening SSH.

Uses Azure managed Run Command. Credentials travel as protected parameters,
never command-line arguments, source scripts or printed deployment output.
"""
import argparse
import base64
import io
import json
from pathlib import Path
import secrets
import re
import subprocess
import tarfile
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
GROUP = "CoC-inst-OMSCS-RG"
SUB = "75f0c79c-0712-4558-955b-b78bfe006946"
PREFIX = f"/subscriptions/{SUB}/resourceGroups/{GROUP}/providers/"
VM = PREFIX + "Microsoft.Compute/virtualMachines/cs1301-poc-grader-vm"
APP = PREFIX + "Microsoft.App/containerApps/cs1301-poc-web-v2"
WEB_API = "2025-01-01"


def az(*args):
    for attempt in range(21):
        result = subprocess.run(["az", *args, "--only-show-errors", "-o", "json"],
                                capture_output=True, text=True)
        if not result.returncode:
            return json.loads(result.stdout) if result.stdout.strip() else {}
        if 'ContainerAppOperationInProgress' in result.stderr and attempt < 20:
            print('Waiting for Azure web configuration lock.', flush=True)
            time.sleep(15)
            continue
        # Azure errors may repeat sensitive request bodies. Expose only the code.
        code = re.search(r'ERROR: \(([A-Za-z0-9_]+)\)', result.stderr)
        raise RuntimeError('Azure request failed: ' + (code.group(1) if code else 'see resource activity status'))


def rest(method, path, version, body=None, query=""):
    url = "https://management.azure.com" + path + "?api-version=" + version + query
    with tempfile.TemporaryDirectory(prefix="trellis-grader-") as folder:
        args = ["rest", "--method", method, "--url", url]
        if body is not None:
            payload = Path(folder) / "body.json"
            payload.touch(mode=0o600)
            payload.write_text(json.dumps(body))
            args += ["--body", "@" + str(payload)]
        return az(*args)


def command(name, script, protected=None, timeout=900):
    resource = VM + "/runCommands/trellis-" + name
    body = {"location": "southcentralus", "properties": {
        "source": {"script": script}, "timeoutInSeconds": timeout,
        "asyncExecution": True,
        "protectedParameters": [{"name": key, "value": value}
                                for key, value in (protected or {}).items()],
    }}
    rest("put", resource, "2025-04-01", body)
    deadline = time.monotonic() + timeout + 120
    while time.monotonic() < deadline:
        result = rest("get", resource, "2025-04-01", query="&$expand=instanceView")
        view = result.get("properties", {}).get("instanceView", {})
        state = view.get("executionState")
        if state in {"Succeeded", "Failed", "Canceled", "TimedOut"}:
            output = view.get("output", "")
            # Our scripts never echo protected parameters or environment files.
            if output:
                print(output, flush=True)
            if state != "Succeeded" or view.get("exitCode", 1) != 0:
                raise RuntimeError("VM task failed; execution state=" + str(state))
            return
        print("Waiting for VM task: " + name, flush=True)
        time.sleep(15)
    raise RuntimeError("Timed out waiting for VM task")


def bundle_source():
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w:gz") as bundle:
        files = [ROOT / "runner/service.py"]
        files += sorted((ROOT / "runner/grading").glob("*.py"))
        files += sorted((ROOT / "runner/sandbox").glob("*.py"))
        files += [ROOT / "runner/sandbox/Dockerfile"]
        files += sorted((ROOT / "runner/tests").glob("test_*.py"))
        for path in files:
            bundle.add(path, arcname=str(path.relative_to(ROOT / "runner")))
        bundle.add(ROOT / "backend/core/grading_contract.py",arcname="trellis_contract.py")
    encoded = base64.b64encode(archive.getvalue()).decode()
    return encoded


def install():
    encoded = bundle_source()
    script = """#!/bin/bash
set -eu
export DEBIAN_FRONTEND=noninteractive
unset RunnerToken
if systemctl is-active --quiet trellis-worker.service; then
    systemctl stop trellis-worker.service
fi
apt-get update -qq >/var/log/trellis-install.log 2>&1
apt-get install -y -qq docker.io python3-venv ca-certificates >>/var/log/trellis-install.log 2>&1
systemctl enable --now docker >/dev/null
install -d -m 0755 /opt/trellis/runner
python3 - <<'PY'
import base64, io, tarfile
with tarfile.open(fileobj=io.BytesIO(base64.b64decode('BUNDLE'))) as bundle:
    bundle.extractall('/opt/trellis/runner', filter='data')
PY
python3 -m venv /opt/trellis/venv
/opt/trellis/venv/bin/pip install --disable-pip-version-check 'requests>=2.32.4,<3' >>/var/log/trellis-install.log 2>&1
docker build --pull -t cs1301-student-python:local /opt/trellis/runner/sandbox >>/var/log/trellis-install.log 2>&1
cd /opt/trellis/runner
docker build -t cs1301-student-python:local sandbox >/var/log/trellis-sandbox-build.log 2>&1
RUN_DOCKER_TESTS=1 /opt/trellis/venv/bin/python -m unittest discover -s tests >/var/log/trellis-tests.log 2>&1
cat /var/log/trellis-tests.log
echo TRELLIS_INSTALL_AND_ISOLATION_TESTS_PASSED
""".replace("BUNDLE", encoded)
    command("install", script)


def update():
    encoded=bundle_source()
    script="""#!/bin/bash
set -eu
systemctl stop trellis-worker.service
trap 'systemctl start trellis-worker.service' EXIT
python3 - <<'PYCODE'
import base64,io,tarfile
with tarfile.open(fileobj=io.BytesIO(base64.b64decode('BUNDLE'))) as bundle:
    bundle.extractall('/opt/trellis/runner',filter='data')
PYCODE
cd /opt/trellis/runner
docker build -t cs1301-student-python:local sandbox >/var/log/trellis-sandbox-build.log 2>&1
RUN_DOCKER_TESTS=1 /opt/trellis/venv/bin/python -m unittest discover -s tests >/var/log/trellis-tests.log 2>&1 || { cat /var/log/trellis-tests.log; exit 1; }
cat /var/log/trellis-tests.log
echo TRELLIS_WORKER_UPDATED_AND_TESTED
""".replace('BUNDLE',encoded)
    command('update',script)


def app_config(enabled=None, connect=False):
    app = rest("get", APP, WEB_API)
    template = app["properties"]["template"]
    config = app["properties"]["configuration"]
    container = template["containers"][0]
    env = {item["name"]: item for item in container.get("env", [])}
    token = None
    if connect:
        values = rest("post", APP + "/listSecrets", WEB_API)["value"]
        existing = next((item["value"] for item in values if item["name"] == "runner-token"), None)
        token = existing or secrets.token_urlsafe(48)
        if not existing:
            values.append({"name": "runner-token", "value": token})
            rest("patch", APP, WEB_API, {"properties": {"configuration": {"secrets": values}}})
        env["RUNNER_TOKEN"] = {"name": "RUNNER_TOKEN", "secretRef": "runner-token"}
    if enabled is not None:
        env["EXECUTION_ENABLED"] = {"name": "EXECUTION_ENABLED", "value": "1" if enabled else "0"}
    endpoint = "https://" + config["ingress"]["fqdn"] + "/api/runner/"
    properties = app["properties"]
    if (container.get("env", []) == list(env.values()) and
            properties.get("provisioningState") == "Succeeded" and
            properties.get("latestRevisionName") == properties.get("latestReadyRevisionName")):
        print("Web configuration already ready.", flush=True)
        return token, endpoint
    container["env"] = list(env.values())
    template["revisionSuffix"] = "grader-" + str(int(time.time()))
    rest("patch", APP, WEB_API, {"properties": {
        "configuration": {"registries": [{k:v for k,v in registry.items() if v and
            k in {"server", "username", "passwordSecretRef", "identity"}}
            for registry in config["registries"]]}, "template": template}})
    print("Web configuration accepted; waiting for its revision.", flush=True)
    for _ in range(40):
        latest = rest("get", APP, WEB_API)["properties"]
        if (latest.get("provisioningState") == "Succeeded" and
                latest.get("latestReadyRevisionName") == APP.rsplit("/", 1)[-1] + "--" + template["revisionSuffix"]):
            print("Web revision ready.", flush=True)
            return token, endpoint
        time.sleep(5)
    raise RuntimeError("New web revision is not ready; execution remains unverified")


def connect():
    token, url = app_config(enabled=False, connect=True)
    script = """#!/bin/bash
set -eu
umask 077
python3 - <<'PY'
import os
import urllib.request, urllib.error
from pathlib import Path
token = os.environ['RunnerToken']
assert token and '\\n' not in token and '\\r' not in token
request=urllib.request.Request('__TRELLIS_API_ENDPOINT__complete/00000000-0000-0000-0000-000000000000/',data=b'{"lease":"health-check"}',headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'},method='POST')
try:
    urllib.request.urlopen(request,timeout=15)
    raise RuntimeError('Unexpected health check response')
except urllib.error.HTTPError as error:
    assert error.code==404, 'Worker authentication check failed'
path = Path('/opt/trellis/worker.env')
path.write_text('RUNNER_TOKEN=' + token + '\\nRUNNER_API_URL=__TRELLIS_API_ENDPOINT__\\n')
path.chmod(0o600)
PY
unset RunnerToken
cat >/etc/systemd/system/trellis-worker.service <<'UNIT'
[Unit]
Description=Trellis isolated execution queue worker
After=network-online.target docker.service
Wants=network-online.target
Requires=docker.service

[Service]
Type=simple
WorkingDirectory=/opt/trellis/runner
EnvironmentFile=/opt/trellis/worker.env
ExecStart=/opt/trellis/venv/bin/python -u /opt/trellis/runner/service.py
Restart=always
RestartSec=5
TimeoutStopSec=300
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ProtectKernelTunables=true
ProtectControlGroups=true
MemoryMax=512M
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable trellis-worker.service >/dev/null
systemctl restart trellis-worker.service
sleep 3
systemctl is-active trellis-worker.service
echo TRELLIS_WORKER_CONNECTED
""".replace("__TRELLIS_API_ENDPOINT__", url)
    command("connect", script, {"RunnerToken": token}, timeout=120)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["install", "update", "connect", "enable", "disable", "status"])
    args = parser.parse_args()
    if args.action == "install":
        install()
    elif args.action == "update":
        update()
    elif args.action == "connect":
        connect()
    elif args.action in {"enable", "disable"}:
        app_config(enabled=args.action == "enable")
    else:
        command("status", "#!/bin/bash\nset -eu\nsystemctl is-active trellis-worker.service\n"
                "journalctl -u trellis-worker.service -n 8 --no-pager\n", timeout=120)


if __name__ == "__main__":
    main()
