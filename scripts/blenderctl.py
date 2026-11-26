#!/usr/bin/env python3
"""Send authenticated Python commands to the Blender GUI bridge on localhost.

Uses the same 0600 token file as the bridge (see bridge_auth.py).
RESULT is printed as JSON when structured; PROGRESS() events are printed live
in the final response. Cancellation: blenderctl.cancel(req_id).
"""
import json
import os
import socket
import sys

import bridge_auth

HOST = "127.0.0.1"
PORT = int(os.environ.get("HERMES_BRIDGE_PORT", "7999"))


def _request(payload, timeout=130):
    payload = dict(payload)
    payload.setdefault("token", bridge_auth.ensure_token())
    s = socket.create_connection((HOST, PORT), timeout=timeout)
    s.settimeout(timeout)
    s.sendall((json.dumps(payload) + "\n").encode("utf-8"))
    data = b""
    while b"\n" not in data:
        chunk = s.recv(65536)
        if not chunk:
            break
        data += chunk
    s.close()
    return json.loads(data.split(b"\n", 1)[0].decode("utf-8", "replace"))


def call(code, timeout=130, req_id=1, token=None):
    payload = {"id": req_id, "code": code}
    if token is not None:
        payload["token"] = token
    return _request(payload, timeout=timeout)


def cancel(req_id=1, timeout=5):
    """Ask the bridge to set the cooperative cancel flag for req_id."""
    return _request({"id": 0, "cancel": req_id}, timeout=timeout)


if __name__ == "__main__":
    code = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "import bpy\\nRESULT = bpy.app.version_string"
    code = code.replace("\\n", "\n")
    r = call(code)
    for message in r.get("progress", []):
        print("PROGRESS:", message)
    if r.get("output"):
        print(r["output"], end="" if r["output"].endswith("\n") else "\n")
    result = r.get("result")
    if result not in (None, ""):
        print(result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str))
    if not r.get("ok"):
        print("ERROR:", r.get("error"), file=sys.stderr)
        sys.exit(1)
