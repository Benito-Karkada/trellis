"""Run a trusted maintenance script, optionally upload a file, via Azure exec.

Uses the same authenticated WebSocket protocol as `az containerapp exec`; it does
not enable app ingress or change storage networking. Requires websocket-client
(included with Azure CLI's Python). Never use this to execute student programs.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import subprocess
from urllib.parse import quote_plus
import websocket
import certifi

GROUP = "CoC-inst-OMSCS-RG"


def az(*args):
    result = subprocess.run(["az", *args, "--only-show-errors", "-o", "json"], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("Azure exec management request failed")
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", default="cs1301-poc-web-v2")
    parser.add_argument("--python-file", type=Path, required=True, help="Trusted local maintenance code")
    parser.add_argument("--upload", type=Path)
    parser.add_argument("--remote-path", default="/tmp/cs1301-course-import.tar.gz")
    args = parser.parse_args()
    source = args.python_file.read_text()
    upload = base64.b64encode(args.upload.read_bytes()) if args.upload else b""
    chunk_size = 2048  # Keep writes below the remote PTY input buffer limit.
    if upload:
        digest = hashlib.sha256(args.upload.read_bytes()).hexdigest()
        source = (
            "import sys,tty,base64,hashlib,pathlib\n"
            "tty.setraw(sys.stdin.fileno())\n"
            "print('CS1301_UPLOAD_READY',flush=True)\n"
            f"target=pathlib.Path({args.remote_path!r})\n"
            "partial=target.with_suffix(target.suffix+'.part')\n"
            "with partial.open('wb') as stream:\n"
            f"    for offset in range(0,{len(upload)},{chunk_size}):\n"
            f"        count=min({chunk_size},{len(upload)}-offset)\n"
            "        data=sys.stdin.buffer.read(count)\n"
            "        if len(data)!=count: raise ValueError('Incomplete upload chunk')\n"
            "        stream.write(base64.b64decode(data,validate=True))\n"
            "        print('CS1301_ACK:'+str(offset+count),flush=True)\n"
            f"assert hashlib.sha256(partial.read_bytes()).hexdigest()=={digest!r},'Upload checksum mismatch'\n"
            "partial.replace(target)\n"
            "print('CS1301_UPLOAD_VERIFIED',flush=True)\n" + source
        )
    wrapper = "try:\n" + "\n".join("    " + line for line in source.splitlines()) + "\nexcept Exception as exc:\n    print('CS1301_MAINTENANCE_FAILED: '+type(exc).__name__,flush=True)\nelse:\n    print('CS1301_MAINTENANCE_DONE',flush=True)\n"
    encoded = base64.b64encode(wrapper.encode()).decode()
    # Keep the exec URL short: IIS/proxy limits reject long command query strings.
    bootstrap = (
        "import sys,tty,base64\n"
        "tty.setraw(sys.stdin.fileno())\n"
        "parts=[]\nprint('CS1301_CODE_READY',flush=True)\n"
        f"for offset in range(0,{len(encoded)},{chunk_size}):\n"
        f"    count=min({chunk_size},{len(encoded)}-offset)\n"
        "    parts.append(sys.stdin.buffer.read(count))\n"
        "    print('CS1301_CODE_ACK:'+str(offset+count),flush=True)\n"
        "exec(base64.b64decode(b''.join(parts),validate=True))\n"
    )
    command = "python -u -c exec(__import__('base64').b64decode('" + base64.b64encode(bootstrap.encode()).decode() + "'))"
    app = az("containerapp", "show", "-g", GROUP, "-n", args.app)
    revision = app["properties"]["latestReadyRevisionName"]
    replicas = az("containerapp", "replica", "list", "-g", GROUP, "-n", args.app, "--revision", revision)
    replica = replicas[0]
    container = replica["properties"]["containers"][0]
    base = container["logStreamEndpoint"].split("/subscriptions/")[0].replace("https://", "wss://")
    path = app["id"].split("/providers/Microsoft.App/")[0] + "/containerApps/" + args.app
    url = base + path + f"/revisions/{revision}/replicas/{replica['name']}/containers/{container['name']}/exec?command=" + quote_plus(command)
    token = az("rest", "--method", "post", "--url", "https://management.azure.com" + app["id"] + "/getAuthToken?api-version=2025-01-01")["properties"]["token"]
    sock = websocket.create_connection(url, header=["Authorization: Bearer " + token],
                                      sslopt={"ca_certs": certifi.where()}, timeout=90)
    sock.send(b'\x00\x04{"Width":180,"Height":40}')
    buffer = ""
    sent = False
    def receive():
        while True:
            message = sock.recv()
            if not message:
                raise RuntimeError("Azure exec closed before maintenance completed")
            if isinstance(message, str):
                message = message.encode()
            if message[0] == 2:
                raise RuntimeError("Azure exec proxy rejected the connection")
            if message[0] == 0:
                return message[2:].decode(errors="replace")
    try:
        ready = ""
        while "CS1301_CODE_READY" not in ready:
            ready += receive()
        initial = ""
        for offset in range(0, len(encoded), chunk_size):
            part = encoded[offset:offset + chunk_size].encode()
            sock.send(b"\x00\x00" + part)
            acknowledgement = f"CS1301_CODE_ACK:{offset + len(part)}\n"
            received = ""
            while acknowledgement not in received.replace("\r", ""):
                received += receive()
            initial = received.replace("\r", "").split(acknowledgement, 1)[1]
        while True:
            output = initial or receive()
            initial = ""
            print(output, end="", flush=True)
            buffer = (buffer + output)[-4096:]
            if upload and not sent and "CS1301_UPLOAD_READY" in buffer:
                for offset in range(0, len(upload), chunk_size):
                    chunk = upload[offset:offset + chunk_size]
                    sock.send(b"\x00\x00" + chunk)
                    acknowledgement = f"CS1301_ACK:{offset + len(chunk)}\n"
                    received = ""
                    while acknowledgement not in received.replace("\r", ""):
                        received += receive()
                        if "CS1301_MAINTENANCE_FAILED" in received:
                            raise RuntimeError("Remote upload failed")
                    remainder = received.replace("\r", "").split(acknowledgement, 1)[1]
                    if remainder:
                        print(remainder, end="", flush=True)
                        buffer += remainder
                    if offset and offset % (1024 * 1024) == 0:
                        print(f"Private transfer: {offset * 100 // len(upload)}%", flush=True)
                sent = True
            if "CS1301_MAINTENANCE_FAILED" in buffer:
                raise RuntimeError("Remote maintenance failed")
            if "CS1301_MAINTENANCE_DONE" in buffer:
                break
    finally:
        sock.close()


if __name__ == "__main__":
    main()
