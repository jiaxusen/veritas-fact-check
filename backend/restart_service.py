"""重启查证服务：停止旧进程 → PowerShell Start-Process 独立启动 → 验证。"""
import os
import subprocess
import time
import urllib.request
BACKEND = r"D:\jqw33\Documents\68\backend"
OUT_LOG = os.path.join(BACKEND, "server.out.log")
ERR_LOG = os.path.join(BACKEND, "server.err.log")
# 1) 停止占用 8000 端口的旧进程
ps_kill = (
    "$conns = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue; "
    "if ($conns) { $conns | Select-Object -ExpandProperty OwningProcess -Unique | "
    "ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }; 'KILLED' } else { 'NONE' }"
)
res = subprocess.run(
    ["powershell.exe", "-NoProfile", "-Command", ps_kill],
    capture_output=True, text=True, timeout=30,
)
print("kill:", res.stdout.strip(), res.stderr.strip()[:200])
time.sleep(2)
# 2) 清理旧日志
for path in (OUT_LOG, ERR_LOG):
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass
# 3) PowerShell Start-Process 独立启动
ps_start = (
    "Start-Process -FilePath 'python' "
    "-ArgumentList '-m','uvicorn','main:app','--host','0.0.0.0','--port','8000' "
    f"-WorkingDirectory '{BACKEND}' "
    f"-RedirectStandardOutput '{OUT_LOG}' "
    f"-RedirectStandardError '{ERR_LOG}' "
    "-WindowStyle Hidden"
)
res = subprocess.run(
    ["powershell.exe", "-NoProfile", "-Command", ps_start],
    capture_output=True, text=True, timeout=45,
)
print("start rc:", res.returncode, res.stderr.strip()[:300])
# 4) 验证端口与新接口
up = False
for i in range(20):
    time.sleep(1)
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=3) as r:
            print("health:", r.read().decode())
            up = True
            break
    except Exception as exc:
        if i == 19:
            print("last error:", exc)
print("SERVICE_UP:", up)
if up:
    # 验证访问台页面与门禁接口
    with urllib.request.urlopen("http://127.0.0.1:8000/access.html", timeout=10) as r:
        body = r.read().decode("utf-8", errors="replace")
    print("ACCESS_PAGE:", "PASS" if ("J2026" in body and "访问台" in body) else "FAIL", f"({len(body)} bytes)")
    req = urllib.request.Request(
        "http://127.0.0.1:8000/api/access/generate", data=b"{}", method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        print("GENERATE:", r.read().decode())
if not up and os.path.exists(ERR_LOG):
    print("--- server.err.log ---")
    print(open(ERR_LOG, encoding="utf-8", errors="replace").read()[-2000:])