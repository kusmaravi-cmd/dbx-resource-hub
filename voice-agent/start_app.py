"""Databricks Apps entrypoint: one container, two processes (DIVA skill pattern).

1. Bind the stdlib web tier to DATABRICKS_APP_PORT within seconds (health check).
2. Behind it, build the LiveKit worker's isolated venv at /tmp/agent-venv from agent-requirements.txt
   (kept out of the platform env, whose preinstalled packages collide with the pinned LiveKit stack),
   fetch the VAD model files, then start the worker. It registers with LiveKit ~30-60 s after deploy.
"""
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).parent
os.chdir(ROOT)
os.environ.setdefault("DATABRICKS_APP_PORT", "8000")
os.environ["PYTHONUNBUFFERED"] = "1"

# Auth: with a PAT secret attached (DATABRICKS_TOKEN), drop the injected service-principal OAuth creds so
# the SDK has exactly one auth method. Without a PAT, keep them: the app runs as its service principal.
if os.environ.get("DATABRICKS_TOKEN"):
    os.environ.pop("DATABRICKS_CLIENT_ID", None)
    os.environ.pop("DATABRICKS_CLIENT_SECRET", None)
    auth_mode = "PAT"
else:
    auth_mode = "app service principal"

_host = os.environ.get("DATABRICKS_HOST", "")
if _host and not _host.startswith("http"):
    os.environ["DATABRICKS_HOST"] = f"https://{_host}"


def log(msg: str) -> None:
    print(f"[boot] {msg}", flush=True)


log(f"python {sys.version.split()[0]}; auth: {auth_mode}")
web = subprocess.Popen([sys.executable, "app/web_server.py"])
agent_proc = None


def _step(desc, cmd):
    print(f"[agent-boot] {desc} @ {time.strftime('%H:%M:%S')}", flush=True)
    res = subprocess.run(cmd, capture_output=True, text=True)
    tail = "\n".join((res.stdout + "\n" + res.stderr).strip().splitlines()[-10:])
    if res.returncode != 0:
        print(f"[agent-boot] step failed (exit {res.returncode}):\n{tail}", flush=True)
        raise RuntimeError(f"{desc} failed")
    if tail:
        print(tail, flush=True)


def boot_agent():
    global agent_proc
    venv_py = "/tmp/agent-venv/bin/python"
    try:
        _step("creating isolated venv", [sys.executable, "-m", "venv", "/tmp/agent-venv"])
        if shutil.which("uv"):
            _step("installing agent deps (uv)", ["uv", "pip", "install", "--python", venv_py,
                                                 "-r", "agent-requirements.txt"])
        else:
            _step("installing agent deps (pip, the long step)",
                  [venv_py, "-m", "pip", "install", "--no-cache-dir", "--prefer-binary", "--progress-bar", "off",
                   "-r", "agent-requirements.txt"])
        os.environ.setdefault("HF_HOME", "/tmp/hf")
        _step("downloading model files", [venv_py, "app/agent.py", "download-files"])
        print(f"[agent-boot] starting worker @ {time.strftime('%H:%M:%S')}", flush=True)
        agent_proc = subprocess.Popen([venv_py, "app/agent.py", "start"])
    except Exception as exc:  # never take the web tier down with the worker
        print(f"[agent-boot] FAILED: {exc}", flush=True)


if os.environ.get("HUB_DISABLE_AGENT") != "1":
    threading.Thread(target=boot_agent, daemon=True).start()


def shutdown(signum, _frame):
    log(f"signal {signum}; stopping")
    for proc in (agent_proc, web):
        if proc is not None and proc.poll() is None:
            proc.terminate()
    deadline = time.time() + 5
    for proc in (agent_proc, web):
        while proc is not None and proc.poll() is None and time.time() < deadline:
            time.sleep(0.2)
        if proc is not None and proc.poll() is None:
            proc.kill()
    sys.exit(0)


signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT, shutdown)
sys.exit(web.wait())  # the app lives and dies with the web tier
