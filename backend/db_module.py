"""SQLite 数据层：用户、会话、查证记录、用量统计。
设计要点：
- 单文件 SQLite（零成本、零运维），WAL 模式支持并发读
- 每请求独立连接（check_same_thread=False + 短连接），避免线程安全问题
- 首次启动自动建表，并把旧 history.json 迁移进来（归属 owner 用户）
"""
from __future__ import annotations
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent
# 数据目录解析：云平台部署目录通常只读，需落到可写位置
# 优先级：环境变量 DATA_DIR > 可写检测后的 backend/data > 系统临时目录
def _resolve_data_dir() -> Path:
    import os
    import tempfile
    candidates = []
    env_dir = os.environ.get("VERITAS_DATA_DIR") or os.environ.get("DATA_DIR")
    if env_dir:
        candidates.append(Path(env_dir))
    candidates.append(BASE_DIR / "data")
    candidates.append(Path(tempfile.gettempdir()) / "veritas_data")
    for cand in candidates:
        try:
            cand.mkdir(parents=True, exist_ok=True)
            probe = cand / ".write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return cand
        except (OSError, PermissionError):
            continue
    return Path(tempfile.gettempdir()) / "veritas_data"
DATA_DIR = _resolve_data_dir()
DB_FILE = DATA_DIR / "app.db"
LEGACY_HISTORY = BASE_DIR / "data" / "history.json"
_init_lock = threading.Lock()
_initialized = False
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    salt          TEXT    NOT NULL,
    plan          TEXT    NOT NULL DEFAULT 'free',
    daily_quota   INTEGER NOT NULL DEFAULT 100,
    created_at    TEXT    NOT NULL,
    last_login_at TEXT,
    disabled      INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    expires_at REAL NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS records (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    card_id    TEXT    NOT NULL,
    input_text TEXT    NOT NULL,
    label      TEXT    NOT NULL,
    level      TEXT    NOT NULL,
    confidence REAL    NOT NULL,
    created_at TEXT    NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS usage (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    day        TEXT    NOT NULL,
    calls      INTEGER NOT NULL DEFAULT 0,
    cost       REAL    NOT NULL DEFAULT 0,
    UNIQUE (user_id, day),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_records_user ON records(user_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_exp  ON sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_usage_day     ON usage(day);
"""
def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
@contextmanager
def connect():
    """短连接上下文：自动提交/回滚并关闭。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_FILE), timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
def _migrate_legacy(conn: sqlite3.Connection, owner_id: int) -> int:
    """把旧 history.json 迁移到 records（仅首次）。"""
    if not LEGACY_HISTORY.exists():
        return 0
    try:
        rows = json.loads(LEGACY_HISTORY.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return 0
    if not isinstance(rows, list) or not rows:
        return 0
    exist = conn.execute("SELECT COUNT(1) FROM records WHERE user_id = ?", (owner_id,)).fetchone()[0]
    if exist:
        return 0
    moved = 0
    for rec in rows:
        try:
            conn.execute(
                "INSERT INTO records (user_id, card_id, input_text, label, level, confidence, created_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (
                    owner_id,
                    str(rec.get("card_id", "")),
                    str(rec.get("input_text", ""))[:200],
                    str(rec.get("label", "")),
                    str(rec.get("level", "")),
                    float(rec.get("confidence", 0) or 0),
                    str(rec.get("created_at", _now())),
                ),
            )
            moved += 1
        except (sqlite3.Error, ValueError):
            continue
    return moved
def init_db() -> dict:
    """建表 + 迁移旧数据（幂等，进程内只跑一次）。"""
    global _initialized
    with _init_lock:
        if _initialized:
            return {"ok": True, "skipped": True}
        with connect() as conn:
            conn.executescript(SCHEMA)
            owner = conn.execute(
                "SELECT id FROM users WHERE username = ?", ("owner",)
            ).fetchone()
            migrated = 0
            if owner:
                migrated = _migrate_legacy(conn, owner["id"])
        _initialized = True
        return {"ok": True, "migrated_records": migrated}
def count_users() -> int:
    with connect() as conn:
        return conn.execute("SELECT COUNT(1) FROM users").fetchone()[0]

def migrate_legacy() -> dict:
    """把旧 history.json 迁到 owner 名下（可重复调用，已迁过则跳过）。"""
    with connect() as conn:
        owner = conn.execute(
            "SELECT id FROM users WHERE username = ?", ("owner",)
        ).fetchone()
        if not owner:
            return {"ok": False, "reason": "owner_not_found"}
        moved = _migrate_legacy(conn, owner["id"])
    return {"ok": True, "moved": moved}
