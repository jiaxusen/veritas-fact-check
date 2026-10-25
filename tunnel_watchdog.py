"""隧道看门狗：每30秒检查公网地址，失效则重启隧道并记录新地址。
地址实时写入 current_tunnel_url.txt，服务被杀后30秒内自动恢复。
"""
import re, subprocess, time, requests
from pathlib import Path
BASE = Path(r"D:\jqw33\Documents\68")
LOG, ERR = BASE / "tunnel.out.log", BASE / "tunnel.err.log"
URL_FILE = BASE / "current_tunnel_url.txt"
KEY = "VERITAS-2026"
def get_log_urls():
    text = ""
    for f in (LOG, ERR):
        if f.exists():
            text += f.read_text(errors="ignore")
    return list(dict.fromkeys(re.findall(r"https://[a-z0-9-]+\.trycloudflare\.com", text)))
def alive(url):
    try:
        r = requests.get(f"{url}/api/health", headers={"x-access-key": KEY}, timeout=15)
        return r.status_code == 200
    except Exception:
        return False
def restart_tunnel():
    subprocess.run(["taskkill", "/F", "/IM", "cloudflared.exe"],
                   capture_output=True, timeout=10)
    time.sleep(2)
    for f in (LOG, ERR):
        if f.exists():
            f.write_text("", encoding="utf-8")
    ps = (f'Start-Process -FilePath "{BASE}\\tools\\cloudflared.exe" '
          f'-ArgumentList "tunnel","--url","http://127.0.0.1:8000" '
          f'-WindowStyle Hidden '
          f'-RedirectStandardOutput "{LOG}" '
          f'-RedirectStandardError "{ERR}"')
    try:
        subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps],
                       capture_output=True, timeout=30)
    except subprocess.TimeoutExpired:
        pass  # Start-Process 偶发阻塞但进程已拉起，按经验继续
    url = None
    for _ in range(30):
        time.sleep(2)
        for u in get_log_urls():
            if alive(u):
                url = u
                break
        if url:
            break
    return url
def main():
    print("[tunnel-watchdog] 启动，每30秒巡检", flush=True)
    while True:
        url = URL_FILE.read_text(encoding="utf-8").strip() if URL_FILE.exists() else ""
        ok = alive(url) if url else False
        if not ok:
            # 当前记录的地址失效，找日志里其他可用地址
            for u in get_log_urls():
                if alive(u):
                    url, ok = u, True
                    break
            if not ok:
                url = restart_tunnel()
                ok = bool(url)
        if ok and url:
            URL_FILE.write_text(url, encoding="utf-8")
            print(f"[tunnel-watchdog] 在线: {url}", flush=True)
        else:
            print("[tunnel-watchdog] 本轮未恢复，下轮重试", flush=True)
        time.sleep(30)
if __name__ == "__main__":
    main()