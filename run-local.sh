#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "${PYTHON_BIN:-python3}" - "$project_root" "$@" <<'PYTHON'
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time

if sys.version_info < (3, 10):
    sys.exit("Python 3.10 or newer is required. Set PYTHON_BIN to a supported interpreter.")

root = Path(sys.argv[1])
arguments = sys.argv[2:]
if arguments not in ([], ["--check"]):
    sys.exit("Usage: ./run-local.sh [--check]")

node = shutil.which(os.environ.get("NODE_BIN", "node"))
if not node:
    sys.exit("Node.js is unavailable. Install Node.js 22.14+ or set NODE_BIN.")
try:
    version = subprocess.check_output([node, "--version"], text=True).strip().lstrip("v")
    if tuple(int(part) for part in version.split(".")[:3]) < (22, 14, 0):
        raise ValueError()
except (ValueError, subprocess.CalledProcessError):
    sys.exit("Node.js 22.14 or newer is required.")

next_cli = root / "web/node_modules/next/dist/bin/next"
monitor = root / "monitor/service.py"
prisma_client = root / "web/node_modules/.prisma/client/index.js"
if not next_cli.is_file() or not prisma_client.is_file():
    sys.exit("Install web dependencies first: cd web && npm ci && npx prisma generate")
if not monitor.is_file():
    sys.exit("Missing monitor/service.py. Run this helper from a complete Datum Work checkout.")

try:
    web_port = int(os.environ.get("WEB_PORT", "3000"))
    monitor_port = int(os.environ.get("DATUM_MONITOR_PORT", "8810"))
    if not all(1 <= port <= 65535 for port in (web_port, monitor_port)):
        raise ValueError()
except ValueError:
    sys.exit("WEB_PORT and DATUM_MONITOR_PORT must be integers from 1 to 65535.")
if web_port == monitor_port:
    sys.exit("WEB_PORT and DATUM_MONITOR_PORT must be different.")
for label, port in (("Web", web_port), ("Monitor", monitor_port)):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            sys.exit(f"{label} port {port} is occupied. Stop that service or select another port.")

monitor_url = f"http://127.0.0.1:{monitor_port}"
print(f"Datum Work: http://127.0.0.1:{web_port}", flush=True)
print(f"Monitor: {monitor_url}", flush=True)
if arguments == ["--check"]:
    print("Local setup is ready; no services started.")
    sys.exit(0)

environment = os.environ.copy()
environment.update({
    "DATUM_MONITOR_HOST": "127.0.0.1",
    "DATUM_MONITOR_PORT": str(monitor_port),
    "DATUM_MONITOR_URL": monitor_url,
    "ENABLE_HISTORICAL_DATA": "true",
})
children = []

def stop(signum, _frame):
    raise SystemExit(128 + signum)

signal.signal(signal.SIGINT, stop)
signal.signal(signal.SIGTERM, stop)
try:
    children.append(subprocess.Popen([sys.executable, "-u", str(monitor)], cwd=root, env=environment, start_new_session=True))
    children.append(subprocess.Popen([node, str(next_cli), "dev", "--hostname", "127.0.0.1", "--port", str(web_port)], cwd=root / "web", env=environment, start_new_session=True))
    while True:
        for child in children:
            if child.poll() is not None:
                sys.exit(child.returncode or 1)
        time.sleep(0.2)
finally:
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    for child in children:
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    for child in children:
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()
PYTHON
