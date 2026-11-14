"""Rotate a private-container SAS and deploy a POC image without printing secrets.

Requires RG Contributor management access and storage Shared Key enabled. The app
receives only a 90-day container SAS, never the storage account key. Production
should use managed identity with container-scoped Blob Data Contributor instead.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

GROUP = "CoC-inst-OMSCS-RG"
ACCOUNT = "cs1301pocstorage26"
APP = "cs1301-poc-web-v2"
CONTAINER = "private-media"


def az(*args, env=None):
    result = subprocess.run(["az", *args, "--only-show-errors", "-o", "json"],
                            capture_output=True, text=True, env=env)
    if result.returncode:
        # Avoid echoing Azure responses that might contain credential material.
        raise RuntimeError("Azure operation failed: " + " ".join(args[:3]))
    return json.loads(result.stdout) if result.stdout.strip() else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-tag", help="Optional new cs1301-web image tag")
    args = parser.parse_args()
    az("storage", "container-rm", "create", "-g", GROUP, "--storage-account", ACCOUNT,
       "--name", CONTAINER, "--public-access", "off")
    keys = az("storage", "account", "keys", "list", "-g", GROUP, "-n", ACCOUNT)
    expiry = (datetime.now(timezone.utc) + timedelta(days=90)).strftime("%Y-%m-%dT%H:%MZ")
    sas = az("storage", "container", "generate-sas", "--account-name", ACCOUNT,
             "--name", CONTAINER, "--permissions", "rcwdl", "--expiry", expiry,
             "--https-only", "--auth-mode", "key",
             env={**os.environ, "AZURE_STORAGE_KEY": keys[0]["value"]})
    app = az("containerapp", "show", "-g", GROUP, "-n", APP)
    base = "https://management.azure.com" + app["id"]
    secrets = az("rest", "--method", "post", "--url", base + "/listSecrets?api-version=2025-01-01")["value"]
    secret_map = {s["name"]: s for s in secrets}
    secret_map["storage-sas-token"] = {"name": "storage-sas-token", "value": sas}
    template = app["properties"]["template"]
    template["revisionSuffix"] = "storage-" + str(int(time.time()))
    container = template["containers"][0]
    if args.image_tag:
        container["image"] = container["image"].rsplit(":", 1)[0] + ":" + args.image_tag
    env = {v["name"]: v for v in container.get("env", [])}
    env["AZURE_STORAGE_SAS_TOKEN"] = {"name": "AZURE_STORAGE_SAS_TOKEN", "secretRef": "storage-sas-token"}
    container["env"] = list(env.values())
    body = {"properties": {"configuration": {
        "secrets": list(secret_map.values()),
        "registries": [{"server": container["image"].split("/")[0],
                        "username": "cs1301-poc-web-pull-token", "passwordSecretRef": "acr-pull-password"}],
    }, "template": template}}
    with tempfile.TemporaryDirectory(prefix="cs1301-storage-") as folder:
        path = Path(folder) / "patch.json"
        path.touch(mode=0o600)
        path.write_text(json.dumps(body))
        az("rest", "--method", "patch", "--url", base + "?api-version=2025-01-01", "--body", "@" + str(path))
    print(f"Storage credential configured; expires {expiry}. Public networking unchanged.")
    print("New revision requested: " + template["revisionSuffix"])


if __name__ == "__main__":
    main()
