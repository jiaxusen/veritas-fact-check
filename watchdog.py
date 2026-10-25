"""后端守护进程。

每隔一段时间探测 127.0.0.1:8000，无响应就把 uvicorn 重新拉起来。
用于解决服务「静默消失」（无异常日志、进程直接被外部杀掉）的问题。

启动：./.venv/Scripts/python.exe watchdog.py
"""
from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent / "backend"
PY = BASE / ".venv" / "Scripts" / "python.exe"
PORT = 8000
INTERVAL = 15  # 探测间隔（秒）


def alive() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=2):
            return True
    except OSError:
        return False


def main() -> None:
    if not PY.exists():
        print(f"[watchdog] python not found: {PY}", flush=True)
        sys.exit(1)

    proc: subprocess.Popen | None = None
    log_path = BASE / "server8000.log"
    err_path = BASE / "server8000.err.log"

    print(f"[watchdog] watching http://127.0.0.1:{PORT}", flush=True)
    while True:
        try:
            if not alive():
                if proc is not None and proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                with open(log_path, "a", encoding="utf-8", errors="ignore") as log, \
                        open(err_path, "a", encoding="utf-8", errors="ignore") as err:
                    proc = subprocess.Popen(
                        [
                            str(PY), "-m", "uvicorn", "main:app",
                            "--host", "0.0.0.0", "--port", str(PORT),
                        ],
                        cwd=str(BASE),
                        stdout=log,
                        stderr=err,
                        stdin=subprocess.DEVNULL,
                    )
                print(f"[watchdog] restarted, pid={proc.pid}", flush=True)
        except Exception as e:  # 守护自身异常不能退出
            print(f"[watchdog] error: {e}", flush=True)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
