#!/usr/bin/env python3
"""Deploy files to server via debug API hex-encoding approach."""
import os
import sys
import urllib.parse
import urllib.request

SERVER = "http://217.114.3.145:5100"
REMOTE_BASE = "/root/Egor_fix_python"
CHUNK_SIZE = 4000  # hex chars per chunk
AUTH = ("admin", "telethon2026")

import base64
_AUTH_HEADER = "Basic " + base64.b64encode(f"{AUTH[0]}:{AUTH[1]}".encode()).decode()


def run_cmd(cmd):
    """Execute command via debug API."""
    url = f"{SERVER}/cmd?q={urllib.parse.quote(cmd)}"
    req = urllib.request.Request(url, headers={"Authorization": _AUTH_HEADER})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode()
    except Exception as e:
        return f"ERROR: {e}"


def deploy_file(local_path, remote_path):
    """Deploy a single file via hex encoding."""
    with open(local_path, "rb") as f:
        content = f.read()
    local_size = len(content)
    hex_str = content.hex()
    hex_len = len(hex_str)

    print(f"  {os.path.basename(local_path)} ({local_size} bytes)...", end=" ", flush=True)

    # Clear temp file
    run_cmd("python3 -c \"f=open('/tmp/_deploy_hex','w');f.write('');f.close()\"")

    # Write hex in chunks
    offset = 0
    while offset < hex_len:
        chunk = hex_str[offset:offset + CHUNK_SIZE]
        cmd = f"python3 -c \"f=open('/tmp/_deploy_hex','a');f.write('{chunk}');f.close()\""
        run_cmd(cmd)
        offset += CHUNK_SIZE

    # Decode hex to target file
    cmd = (
        f"python3 -c \""
        f"import binascii;"
        f"h=open('/tmp/_deploy_hex').read();"
        f"data=binascii.unhexlify(h);"
        f"f=open('{remote_path}','wb');f.write(data);f.close();"
        f"print(len(data))"
        f"\""
    )
    result = run_cmd(cmd)
    # Check size
    if str(local_size) in result:
        print(f"OK ({local_size})")
    else:
        print(f"WARN - expected {local_size}, got: {result.strip()}")


FILES = [
    ("config.py", "config.py"),
    ("core/bot_fallback.py", "core/bot_fallback.py"),
    ("core/registry.py", "core/registry.py"),
    ("core/pool.py", "core/pool.py"),
    ("core/router.py", "core/router.py"),
    ("services/send_text.py", "services/send_text.py"),
    ("services/send_media.py", "services/send_media.py"),
    ("dashboard/routes.py", "dashboard/routes.py"),
    ("dashboard/templates/dashboard.html", "dashboard/templates/dashboard.html"),
    ("dashboard/static/dashboard.js", "dashboard/static/dashboard.js"),
    ("dashboard/static/dashboard.css", "dashboard/static/dashboard.css"),
]

if __name__ == "__main__":
    base_local = "/home/user/Egor_fix_python"
    print("=== Deploying files to server ===")
    for local_rel, remote_rel in FILES:
        local_path = os.path.join(base_local, local_rel)
        remote_path = os.path.join(REMOTE_BASE, remote_rel)
        deploy_file(local_path, remote_path)

    print("\n=== All files deployed ===")
    print("Restarting service...")
    result = run_cmd("systemctl restart telethon-platform")
    print(f"Restart result: {result}")
    print("Done! Wait ~30s for bridges to start.")
