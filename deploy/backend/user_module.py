"""用户体系：注册 / 登录 / 会话令牌 / 密码加密。
安全设计：
- 密码用 PBKDF2-HMAC-SHA256（标准库 hashlib，20万次迭代），每用户独立随机盐
- 令牌为 secrets.token_urlsafe(32)，存库并带过期时间（默认 7 天）
- 登录失败不区分「用户不存在」和「密码错误」，避免账号枚举
"""
from __future__ import annotations
import hashlib
import re
import secrets
import time
from datetime import datetime
import db_module
PBKDF2_ROUNDS = 200_000
TOKEN_TTL_SECONDS = 7 * 24 * 3600
MIN_PASSWORD = 6
MAX_PASSWORD = 64
USERNAME_RE = re.compile(r"^[A-Za-z0-9_\u4e00-\u9fa5]{3,20}$")
class UserError(Exception):
    """用户操作异常，携带可直接展示给用户的中文提示。"""
    def __init__(self, message: str, code: str = "user_error"):
        super().__init__(message)
        self.message = message
        self.code = code
def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ROUNDS
    ).hex()
def _validate(username: str, password: str) -> None:
    if not USERNAME_RE.match(username or ""):
        raise UserError("用户名需 3~20 位，仅支持中英文、数字和下划线", "invalid_username")
    if not (MIN_PASSWORD <= len(password or "") <= MAX_PASSWORD):
        raise UserError(f"密码长度需 {MIN_PASSWORD}~{MAX_PASSWORD} 位", "invalid_password")
def register(username: str, password: str, plan: str = "free",
             daily_quota: int = 100) -> dict:
    """注册新用户，返回用户信息（不含密码）。"""
    username = (username or "").strip()
    _validate(username, password)
    salt = secrets.token_hex(16)
    pw_hash = _hash_password(password, salt)
    with db_module.connect() as conn:
        exists = conn.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()
        if exists:
            raise UserError("该用户名已被注册", "username_taken")
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, salt, plan, daily_quota, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (username, pw_hash, salt, plan, int(daily_quota), _now()),
        )
        user_id = cur.lastrowid
    return {"id": user_id, "username": username, "plan": plan,
            "daily_quota": int(daily_quota), "created_at": _now()}
def login(username: str, password: str) -> dict:
    """校验账号密码，成功则签发令牌。"""
    username = (username or "").strip()
    with db_module.connect() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash, salt, plan, daily_quota, disabled"
            " FROM users WHERE username = ?", (username,)
        ).fetchone()
        if row is None:
            raise UserError("用户名或密码不正确", "bad_credentials")
        if row["disabled"]:
            raise UserError("该账号已被停用，请联系管理员", "account_disabled")
        if not secrets.compare_digest(_hash_password(password or "", row["salt"]),
                                      row["password_hash"]):
            raise UserError("用户名或密码不正确", "bad_credentials")
        token = secrets.token_urlsafe(32)
        expires = time.time() + TOKEN_TTL_SECONDS
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?,?,?,?)",
            (token, row["id"], _now(), expires),
        )
        conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (_now(), row["id"]))
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (time.time(),))
    return {
        "token": token,
        "expires_in": TOKEN_TTL_SECONDS,
        "user": {"id": row["id"], "username": row["username"],
                 "plan": row["plan"], "daily_quota": row["daily_quota"]},
    }
def user_by_token(token: str) -> dict | None:
    """按令牌取用户；过期或不存在返回 None。"""
    if not token:
        return None
    with db_module.connect() as conn:
        row = conn.execute(
            "SELECT u.id, u.username, u.plan, u.daily_quota, u.disabled, s.expires_at"
            " FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ?",
            (token,),
        ).fetchone()
        if row is None:
            return None
        if row["expires_at"] < time.time():
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            return None
        if row["disabled"]:
            return None
        return {"id": row["id"], "username": row["username"],
                "plan": row["plan"], "daily_quota": row["daily_quota"]}
def logout(token: str) -> bool:
    with db_module.connect() as conn:
        cur = conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        return cur.rowcount > 0
def ensure_owner(password: str = "VERITAS-2026") -> dict | None:
    """确保 owner 账号存在（用于迁移旧数据归属），已存在则跳过。"""
    with db_module.connect() as conn:
        row = conn.execute("SELECT id, username FROM users WHERE username = ?",
                           ("owner",)).fetchone()
        if row:
            return {"id": row["id"], "username": row["username"], "created": False}
    info = register("owner", password, plan="owner", daily_quota=500)
    return {**info, "created": True}
