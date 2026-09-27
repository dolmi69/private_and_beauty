"""Run the Telegram demo locally with an account-free Cloudflare HTTPS tunnel.

Install cloudflared first, then run this file with the project's virtualenv Python.
Keep this process running; Ctrl+C stops its server, tunnel and bot together.
"""
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
LOGS = ROOT / ".artifacts"
LOGS.mkdir(exist_ok=True)
bundled = ROOT.parent / ".artifacts" / "cloudflared.exe"
cloudflared = shutil.which("cloudflared") or (str(bundled) if bundled.exists() else None)
if not cloudflared:
    sys.exit("Install cloudflared: https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/downloads/")

children = []
handles = []
env = os.environ.copy()
flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def launch(args, name):
    output = open(LOGS / (name + ".log"), "w", encoding="utf-8")
    handles.append(output)
    child = subprocess.Popen(args, cwd=ROOT, env=env, stdout=output,
                             stderr=subprocess.STDOUT, creationflags=flags)
    children.append(child)
    return child


try:
    tunnel = launch([cloudflared, "tunnel", "--url", "http://127.0.0.1:8002",
                     "--protocol", "http2"], "tunnel")
    deadline = time.monotonic() + 60
    url = None
    while time.monotonic() < deadline:
        match = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com",
                          (LOGS / "tunnel.log").read_text(encoding="utf-8", errors="replace"))
        if match:
            url = match.group()
            break
        if tunnel.poll() is not None:
            raise RuntimeError("Tunnel stopped. See .artifacts/tunnel.log")
        time.sleep(1)
    if not url:
        raise RuntimeError("Tunnel did not provide a URL within 60 seconds.")
    env["TELEGRAM_PREVIEW_HOST"] = url.removeprefix("https://")
    env["TELEGRAM_PREVIEW_SECRET"] = secrets.token_urlsafe(48)
    env["TELEGRAM_MINI_APP_URL"] = url
    server = launch([sys.executable, "manage.py", "runserver", "127.0.0.1:8002",
                     "--noreload", "--settings=config.telegram_preview"], "preview")
    time.sleep(2)
    if server.poll() is not None:
        raise RuntimeError("Server did not start. Check port 8002 and .artifacts/preview.log")
    subprocess.run([sys.executable, "manage.py", "run_telegram_bot", "--configure", "--check"],
                   cwd=ROOT, env=env, check=True)
    bot = launch([sys.executable, "manage.py", "run_telegram_bot"], "bot")
    print("Open https://t.me/hospitalpobot and press Start / Clinic.")
    print("Temporary URL:", url)
    print("Keep this window open. Ctrl+C stops the demo. Admin remains local only.")
    while all(child.poll() is None for child in children):
        time.sleep(1)
    raise RuntimeError("A demo process stopped. Check .artifacts logs.")
except KeyboardInterrupt:
    print("Stopping demo...")
finally:
    for child in reversed(children):
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
    for handle in handles:
        handle.close()
