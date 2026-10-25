"""公网访问口令。

仅在「非本机 / 非局域网」来源（即通过 Cloudflare 公网域名访问）时要求口令，
本机 127.0.0.1 与局域网 192.168.x.x 一律免密直通。

配置：backend/data/auth.json，可用环境变量 VERITAS_ACCESS_KEY 覆盖。
"""
from __future__ import annotations
import ipaddress
import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
AUTH_FILE = BASE_DIR / "data" / "auth.json"
COOKIE_NAME = "vlab_key"
COOKIE_TTL = 60 * 60 * 24 * 30  # 30 天

DEFAULT_CONFIG = {
    "enabled": True,
    "key": "VERITAS-2026",
    "public_only": True,
    "extra_public_hosts": [],
    "extra_private_hosts": [],
}

_PRIVATE_SUFFIX = (".local", ".localdomain", ".home.arpa", ".lan")


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if AUTH_FILE.exists():
        try:
            cfg.update(json.loads(AUTH_FILE.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    env_key = os.environ.get("VERITAS_ACCESS_KEY")
    if env_key:
        cfg["key"] = env_key
    cfg["enabled"] = bool(cfg.get("enabled", True)) and bool(cfg.get("key"))
    return cfg


def check_key(key: str) -> bool:
    cfg = load_config()
    expect = str(cfg.get("key") or "")
    return bool(expect) and str(key or "") == expect


def is_private_host(host: str) -> bool:
    """判断访问来源是否属于本机 / 局域网。"""
    host = (host or "").strip().strip("[]").lower()
    if not host:
        return True
    if host in ("localhost", "::1", "0.0.0.0"):
        return True
    for suffix in _PRIVATE_SUFFIX:
        if host.endswith(suffix):
            return True
    cfg = load_config()
    for h in cfg.get("extra_private_hosts") or []:
        if host == str(h).lower():
            return True
    for h in cfg.get("extra_public_hosts") or []:
        if host == str(h).lower():
            return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # 非 IP（域名）一律视为公网来源
        return False
    return bool(
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
    )


def login_page(redirect_to: str = "/", error: str = "") -> str:
    tip = "<p class='err'>口令不正确，请重试。</p>" if error else ""
    target = redirect_to if redirect_to.startswith("/") else "/"
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>访问验证 · 查证台</title>
<style>
  *{{box-sizing:border-box}}
  body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
       background:#070B14;color:#E6F1FF;font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif}}
  .box{{width:min(92vw,380px);padding:32px 28px;border-radius:16px;
        background:#0E1524;border:1px solid rgba(110,231,183,.18)}}
  h1{{margin:0 0 6px;font-size:19px;letter-spacing:.5px}}
  p.sub{{margin:0 0 20px;font-size:13px;color:#8AA0BF;line-height:1.6}}
  input{{width:100%;padding:11px 13px;font-size:15px;border-radius:10px;
         background:#070B14;border:1px solid rgba(230,241,255,.16);color:#E6F1FF;outline:none}}
  input:focus{{border-color:#6EE7B7}}
  button{{width:100%;margin-top:12px;padding:11px;font-size:15px;font-weight:600;border:0;border-radius:10px;
          background:linear-gradient(135deg,#6EE7B7,#38BDF8);color:#06231B;cursor:pointer}}
  .err{{margin:0 0 14px;font-size:13px;color:#FCA5A5}}
</style>
</head>
<body>
  <form class="box" method="get" action="{target}">
    <h1>查证台 · 访问验证</h1>
    <p class="sub">该站点为个人自建服务，请输入访问口令。<br>本机与局域网访问无需口令。</p>
    {tip}
    <input name="key" type="password" placeholder="访问口令" autocomplete="off" autofocus>
    <button type="submit">进入</button>
  </form>
</body>
</html>"""
