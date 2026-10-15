#!/usr/bin/env python3
"""Upload hero files and run deploy_hero.sh on Fixogram server."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko

HOST = "85.198.54.48"
USER = "root"
ROOT = Path(__file__).resolve().parents[1]
REMOTE = "/var/www/tamirneshan"

FILES = [
    (ROOT / "templates/talent/home.html", f"{REMOTE}/templates/talent/home.html"),
    (ROOT / "templates/talent/base.html", f"{REMOTE}/templates/talent/base.html"),
    (ROOT / "talent/static/talent/style.css", f"{REMOTE}/talent/static/talent/style.css"),
    (ROOT / "talent/copy.py", f"{REMOTE}/talent/copy.py"),
    (ROOT / "scripts/deploy_hero.sh", f"{REMOTE}/scripts/deploy_hero.sh"),
]


def load_password() -> str:
    pw_file = Path.home() / ".ssh" / "arvan.password"
    if pw_file.is_file():
        return pw_file.read_text(encoding="ascii").strip()
    return os.environ.get("ARVAN_ROOT_PASSWORD", "")


def main() -> int:
    password = load_password()
    key_paths = [
        Path.home() / ".ssh" / "arvan",
        Path.home() / ".ssh" / "naghsh_arvan",
    ]
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    connected = False
    last_err: Exception | None = None
    for key_path in key_paths:
        if not key_path.is_file():
            continue
        try:
            client.connect(
                HOST,
                username=USER,
                key_filename=str(key_path),
                timeout=25,
                banner_timeout=25,
                auth_timeout=25,
                look_for_keys=False,
                allow_agent=False,
            )
            connected = True
            break
        except Exception as exc:  # noqa: BLE001
            last_err = exc
    if not connected and password:
        try:
            client.connect(
                HOST,
                username=USER,
                password=password,
                timeout=25,
                banner_timeout=25,
                auth_timeout=25,
                look_for_keys=False,
                allow_agent=False,
            )
            connected = True
        except Exception as exc:  # noqa: BLE001
            last_err = exc
    if not connected:
        print(f"SSH failed: {last_err}", file=sys.stderr)
        return 1

    sftp = client.open_sftp()
    try:
        for local, remote in FILES:
            if not local.is_file():
                print(f"missing local file: {local}", file=sys.stderr)
                return 1
            remote_dir = os.path.dirname(remote)
            try:
                sftp.stat(remote_dir)
            except OSError:
                pass
            print(f"put {local.name} -> {remote}")
            sftp.put(str(local), remote)
    finally:
        sftp.close()

    cmd = f"chmod +x {REMOTE}/scripts/deploy_hero.sh && bash {REMOTE}/scripts/deploy_hero.sh"
    print("run deploy_hero.sh")
    _stdin, stdout, stderr = client.exec_command(cmd, timeout=120)
    out = stdout.read().decode()
    err = stderr.read().decode()
    code = stdout.channel.recv_exit_status()
    if out:
        print(out)
    if err:
        print(err, file=sys.stderr)
    client.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
