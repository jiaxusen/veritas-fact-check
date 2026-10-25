"""本地启动脚本：python run_server.py
监听 0.0.0.0，局域网内其他设备可通过 http://<本机IP>:8000 访问。
"""
from __future__ import annotations
import socket
import uvicorn


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


if __name__ == "__main__":
    lan_ip = get_lan_ip()
    print("=" * 56)
    print("  查证工具服务启动中（监听所有网卡 0.0.0.0:8000）")
    print(f"  本机访问：http://127.0.0.1:8000")
    print(f"  他人访问：http://{lan_ip}:8000   <-- 把这个发给别人")
    print("  注意：对方必须与本机处于同一局域网(WiFi)")
    print("=" * 56)
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False, log_level="info")
