"""局域网访问自检：python check_lan.py
检查服务监听、防火墙、本机IP，并给出他人访问地址。
"""
from __future__ import annotations
import socket
import subprocess
import urllib.request
PORT = 8000
def get_lan_ip() -> str:
    """获取本机在局域网中的 IPv4 地址。"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"
def ps(cmd: str) -> str:
    """执行 PowerShell 命令并返回输出。"""
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", cmd],
            capture_output=True,
            text=True,
            timeout=40,
            encoding="utf-8",
            errors="replace",
        )
        return (r.stdout or "").strip()
    except Exception as exc:  # noqa: BLE001
        return "(查询失败: %s)" % exc
def main() -> None:
    ip = get_lan_ip()
    line = "=" * 60
    print(line)
    print("  查证工具 · 局域网访问自检")
    print(line)
    # 1) 端口监听
    listen = ps(
        "Get-NetTCPConnection -LocalPort %d -State Listen "
        "-ErrorAction SilentlyContinue | "
        "Select-Object LocalAddress,LocalPort | Format-Table -AutoSize | Out-String" % PORT
    )
    print("")
    print("[1] 端口监听状态：")
    print(listen or "  (未监听，服务可能没启动)")
    ok_listen = "0.0.0.0" in listen
    print("    结论：" + ("✅ 已监听所有网卡" if ok_listen else "❌ 未监听 0.0.0.0，请用 run_server.py 启动"))
    # 2) 本机连通性
    print("")
    print("[2] 本机连通性：")
    for host in ("127.0.0.1", ip):
        try:
            with urllib.request.urlopen("http://%s:%d/api/health" % (host, PORT), timeout=5) as resp:
                print("    %s -> ✅ OK (%s)" % (host, resp.status))
        except Exception as exc:  # noqa: BLE001
            print("    %s -> ❌ %s" % (host, exc))
    # 3) 防火墙规则
    print("")
    print("[3] 防火墙放行规则：")
    fw = ps(
        "Get-NetFirewallRule -Direction Inbound -Enabled True -ErrorAction SilentlyContinue | "
        "Where-Object { $_.DisplayName -like '*%d*' -or $_.DisplayName -like '*python*' } | "
        "Select-Object DisplayName,Action | Format-Table -AutoSize | Out-String" % PORT
    )
    print(fw or "  (未找到放行规则，可能被防火墙拦截)")
    # 4) 网络环境
    print("")
    print("[4] 网络环境：")
    print(
        ps(
            "Get-NetIPConfiguration | Where-Object {$_.IPv4Address -and "
            "$_.IPv4Address.IPAddress -notlike '169.254*'} | "
            "Select-Object InterfaceAlias,@{n='IP';e={$_.IPv4Address.IPAddress}},"
            "@{n='Gateway';e={$_.IPv4DefaultGateway.NextHop}} | "
            "Format-Table -AutoSize | Out-String"
        )
    )
    print(ps("netsh wlan show interfaces | findstr /C:\"SSID\" | Out-String"))
    print(line)
    print("  请把下面地址发给对方：http://%s:%d" % (ip, PORT))
    print("  对方必须连同一个 WiFi，且不能输 127.0.0.1 或 localhost")
    print(line)
if __name__ == "__main__":
    main()