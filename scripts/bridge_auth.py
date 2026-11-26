"""Shared token handling for the Hermes Blender bridge and its clients.

The token is a 64-char hex string (32 random bytes). It is stored in a
0600 file outside the skill directory so syncing the skill never copies it.
Environment override: HERMES_BRIDGE_TOKEN (value) or HERMES_BRIDGE_TOKEN_FILE (path).
"""
import os
import secrets


def default_path():
    return os.environ.get("HERMES_BRIDGE_TOKEN_FILE") or os.path.join(
        os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")),
        "blender", "bridge.token")


def load_token(required=True):
    token = os.environ.get("HERMES_BRIDGE_TOKEN")
    if token:
        if len(token) < 32:
            raise RuntimeError("HERMES_BRIDGE_TOKEN demasiado corto (usar 64 hex)")
        return token
    path = default_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            token = fh.read().strip()
    except OSError:
        if required:
            raise RuntimeError("No hay token de bridge. Generalo con: python3 bridge_auth.py")
        return None
    if len(token) < 32:
        raise RuntimeError("Token de bridge invalido en " + path)
    return token


def ensure_token():
    """Return the existing token or create a 0600 token file on first use."""
    token = load_token(required=False)
    if token:
        return token
    path = default_path()
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    token = secrets.token_hex(32)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return load_token(required=True)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(token + "\n")
    os.chmod(path, 0o600)
    return token


if __name__ == "__main__":
    print("HERMES_BRIDGE_TOKEN_FILE:", default_path())
    print("token generado/leido; no lo compartas:", "OK" if ensure_token() else "FALLO")
