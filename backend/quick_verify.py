import subprocess, time, urllib.request
# 确认端口并启动（如未启动）
try:
    with urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=3) as r:
        print("ALREADY_UP:", r.read().decode())
except Exception:
    ps = ("Start-Process -FilePath 'python' -ArgumentList '-m','uvicorn','main:app','--host','127.0.0.1','--port','8000' "
          "-WorkingDirectory 'D:\\jqw33\\Documents\\68\\backend' "
          "-RedirectStandardOutput 'D:\\jqw33\\Documents\\68\\backend\\server.out.log' "
          "-RedirectStandardError 'D:\\jqw33\\Documents\\68\\backend\\server.err.log' -WindowStyle Hidden")
    subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=40)
    for i in range(15):
        time.sleep(1)
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=3) as r:
                print("STARTED:", r.read().decode()); break
        except Exception:
            pass
# 快速验证访问台与门禁接口
with urllib.request.urlopen("http://127.0.0.1:8000/access.html", timeout=10) as r:
    body = r.read().decode("utf-8", errors="replace")
print("ACCESS_PAGE:", "PASS" if "J2026" in body and "访问台" in body else "FAIL")
req = urllib.request.Request("http://127.0.0.1:8000/api/access/generate", data=b"{}", method="POST",
                             headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=10) as r:
    print("GENERATE:", r.read().decode())
with urllib.request.urlopen("http://127.0.0.1:8000/", timeout=10) as r:
    print("FRONTEND: PASS" if r.status == 200 else "FAIL")