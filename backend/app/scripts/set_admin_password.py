"""
Set the admin password used to change settings.

    python -m app.scripts.set_admin_password            (prompts twice)
    python -m app.scripts.set_admin_password --stdin    (reads one line, for automation)

Writes ADMIN_PASSWORD_HASH (argon2) and a fresh JWT_SECRET into the project's
.env file. Every other line in .env is left exactly as it was.
"""

import argparse
import os
import secrets
import sys
from getpass import getpass
from pathlib import Path

from ..auth import hash_password
from ..config import ENV_FILE

MIN_LENGTH = 8


def update_env_file(path: Path, updates: dict[str, str]) -> None:
    """Replace (or append) only the given keys; keep all other lines, comments and line endings."""
    text = ""
    if path.exists():
        with path.open(encoding="utf-8", newline="") as f:  # newline="" keeps \r\n as-is
            text = f.read()
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    found: set[str] = set()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        key = None
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip().removeprefix("export ").strip()
        if key in updates:
            ending = line[len(line.rstrip("\r\n")):]
            out.append(f"{key}='{updates[key]}'{ending}")
            found.add(key)
        else:
            out.append(line)
    missing = [k for k in updates if k not in found]
    if missing and out and not out[-1].endswith(("\n", "\r")):
        out[-1] += newline
    out.extend(f"{key}='{updates[key]}'{newline}" for key in missing)

    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("".join(out), encoding="utf-8", newline="")
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Set the Local RAG Studio admin password.")
    parser.add_argument("--env-file", type=Path, default=ENV_FILE, help=f"default: {ENV_FILE}")
    parser.add_argument("--stdin", action="store_true", help="read the password from standard input")
    args = parser.parse_args(argv)

    if args.stdin:
        password = sys.stdin.readline().rstrip("\r\n")
    else:
        password = getpass("New admin password: ")
        if getpass("Repeat password: ") != password:
            print("Passwords do not match. Nothing was changed.", file=sys.stderr)
            return 1
    if len(password) < MIN_LENGTH:
        print(f"Password must be at least {MIN_LENGTH} characters. Nothing was changed.", file=sys.stderr)
        return 1

    update_env_file(args.env_file, {"ADMIN_PASSWORD_HASH": hash_password(password), "JWT_SECRET": secrets.token_urlsafe(48)})
    print(f"Saved ADMIN_PASSWORD_HASH and JWT_SECRET in {args.env_file} (other keys untouched).")
    print("Restart the backend for the new password to take effect.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
