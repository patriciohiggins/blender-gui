#!/usr/bin/env python3
"""Send a Python command to the Blender GUI bridge on localhost:7999."""
import json
import socket
import sys

HOST, PORT = "127.0.0.1", 7999


def call(code, timeout=130):
    s = socket.create_connection((HOST, PORT), timeout=timeout)
    s.settimeout(timeout)
    s.sendall((json.dumps({"id": 1, "code": code}) + "\n").encode("utf-8"))
    data = b""
    while b"\n" not in data:
        chunk = s.recv(65536)
        if not chunk:
            break
        data += chunk
    s.close()
    return json.loads(data.split(b"\n", 1)[0].decode("utf-8", "replace"))


if __name__ == "__main__":
    code = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "import bpy\nRESULT = bpy.app.version_string"
    code = code.replace("\\n", "\n")
    r = call(code)
    if r.get("output"):
        print(r["output"], end="" if r["output"].endswith("\n") else "\n")
    if r.get("result"):
        print(r["result"])
    if not r.get("ok"):
        print("ERROR:", r.get("error"), file=sys.stderr)
        sys.exit(1)
