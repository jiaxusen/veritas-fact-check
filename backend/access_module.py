"""访问台密令模块：密令生成 / 校验 / 访问令牌管理（内存存储，重启即清空）。"""
from __future__ import annotations
import secrets
import string
import time
CODE_TTL_MINUTES = 10      # 密令有效期（分钟）
TOKEN_TTL_SECONDS = 1800   # 访问令牌有效期（秒）
_CODE_ALPHABET = string.ascii_uppercase + string.digits
_codes: dict[str, float] = {}   # code -> 过期时间戳
_tokens: dict[str, float] = {}  # token -> 过期时间戳
def _cleanup() -> None:
    """清理过期密令与令牌。"""
    now = time.time()
    for code in [c for c, t in _codes.items() if t < now]:
        _codes.pop(code, None)
    for token in [t for t, e in _tokens.items() if e < now]:
        _tokens.pop(token, None)
def generate_code() -> str:
    """生成本次访问密令（VC-XXXXXX，10 分钟有效）。"""
    _cleanup()
    code = "VC-" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
    _codes[code] = time.time() + CODE_TTL_MINUTES * 60
    return code
def verify_code(code: str) -> str | None:
    """校验密令，通过则签发访问令牌。"""
    _cleanup()
    normalized = (code or "").strip().upper()
    expire = _codes.get(normalized)
    if expire is None or time.time() > expire:
        _codes.pop(normalized, None)
        return None
    token = secrets.token_urlsafe(24)
    _tokens[token] = time.time() + TOKEN_TTL_SECONDS
    return token
def owner_token() -> str:
    """本人免密令直通，直接签发访问令牌。"""
    _cleanup()
    token = secrets.token_urlsafe(24)
    _tokens[token] = time.time() + TOKEN_TTL_SECONDS
    return token
def check_token(token: str) -> bool:
    """校验访问令牌是否有效。"""
    _cleanup()
    expire = _tokens.get(token or "")
    if expire is None:
        return False
    if time.time() > expire:
        _tokens.pop(token, None)
        return False
    return True