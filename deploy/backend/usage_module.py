"""防烧钱三件套：限流 + 每日配额 + 用量日志。
设计要点：
- 限流：单身份滑动窗口（每分钟 N 次），防脚本刷接口
- 配额：单身份每日写接口次数上限，重启不丢（状态落盘）
- 日志：每次写接口调用追加 JSONL（用户/路径/状态码/耗时），可对账可审计
- 熔断：当日估算成本超线后进入降级模式（verify_llm 自动回退本地引擎）
- 身份：公网用户取访问口令前缀；本机/局域网为 privileged 身份
"""
from __future__ import annotations
import json
import threading
import time
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CONFIG_FILE = DATA_DIR / "usage.json"
LOG_FILE = DATA_DIR / "usage_log.jsonl"
STATE_FILE = DATA_DIR / "usage_state.json"
DEFAULT_CONFIG = {
    "enabled": True,
    "rate_limit_per_minute": 12,     # 单身份每分钟写接口请求数上限
    "daily_quota": 100,              # 单身份每日写接口次数（公网用户）
    "privileged_daily_quota": 500,   # 本机/局域网身份每日次数
    "cost_per_call": 0.03,           # 估算单次大模型成本（元）
    "daily_cost_limit": 50.0,        # 每日成本熔断线（元），超过进入降级
    "log_retention_days": 180,       # 日志保留天数（《网络安全法》≥6个月）
}
_lock = threading.Lock()
_rate: dict[str, deque] = defaultdict(deque)   # identity -> 时间戳窗口
_day = {"date": "", "count": defaultdict(int), "cost": 0.0}
def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")
def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        try:
            user = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(user, dict):
                cfg.update({k: v for k, v in user.items() if k in DEFAULT_CONFIG})
        except (json.JSONDecodeError, OSError):
            pass
    return cfg
def save_config(update: dict) -> dict:
    cfg = load_config()
    cfg.update({k: v for k, v in update.items() if k in DEFAULT_CONFIG})
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return cfg
def _rollover_locked() -> None:
    """跨天重置当日计数（调用方需持锁）。"""
    today = _today()
    if _day["date"] != today:
        _day["date"] = today
        _day["count"] = defaultdict(int)
        _day["cost"] = 0.0
def _load_state_locked() -> None:
    """启动时恢复当日计数，避免重启重置配额。"""
    _rollover_locked()
    if _day["date"] != _today() or _day["count"]:
        return
    if not STATE_FILE.exists():
        return
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if state.get("date") == _today():
            _day["count"] = defaultdict(int, state.get("count", {}))
            _day["cost"] = float(state.get("cost", 0.0))
    except (json.JSONDecodeError, OSError, ValueError):
        pass
def _save_state_locked() -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(
            json.dumps(
                {
                    "date": _day["date"],
                    "count": dict(_day["count"]),
                    "cost": _day["cost"],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass
_load_state_locked()
def _quota_for(identity: str, privileged: bool, cfg: dict) -> int:
    if privileged:
        return int(cfg["privileged_daily_quota"])
    return int(cfg["daily_quota"])
def guard(identity: str, privileged: bool) -> dict | None:
    """限流 + 配额校验。通过返回 None；被拦返回拒绝原因 dict。
    调用方（门禁中间件）负责把 dict 转成 429 响应。
    """
    cfg = load_config()
    if not cfg.get("enabled"):
        return None
    now = time.time()
    with _lock:
        _rollover_locked()
        # ① 滑动窗口限流
        window = _rate[identity]
        limit = int(cfg["rate_limit_per_minute"])
        while window and window[0] < now - 60:
            window.popleft()
        if len(window) >= limit:
            retry_after = int(60 - (now - window[0])) + 1
            return {"detail": "rate_limited", "retry_after": retry_after,
                    "message": f"请求过于频繁，请 {retry_after} 秒后再试"}
        # ② 每日配额
        quota = _quota_for(identity, privileged, cfg)
        used = _day["count"].get(identity, 0)
        if used >= quota:
            return {"detail": "quota_exceeded",
                    "message": f"今日额度已用完（{quota} 次/天），明天再来或升级套餐"}
        # 通过：占坑
        window.append(now)
        _day["count"][identity] = used + 1
        _day["cost"] += float(cfg["cost_per_call"])
        _save_state_locked()
    return None
def record(identity: str, path: str, status: int, elapsed_ms: int,
           privileged: bool) -> None:
    """追加一条用量日志（JSONL），并按保留天数清理旧日志。"""
    cfg = load_config()
    entry = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "identity": identity,
        "path": path,
        "status": status,
        "elapsed_ms": elapsed_ms,
        "privileged": privileged,
        "estimated_cost": round(float(cfg["cost_per_call"]), 4),
    }
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        _cleanup_logs(cfg)
    except OSError:
        pass
def _cleanup_logs(cfg: dict) -> None:
    """按保留天数清理旧日志（低频触发：每天第一次写入时执行一次）。"""
    marker = DATA_DIR / ".usage_cleaned"
    today = _today()
    try:
        if marker.exists() and marker.read_text(encoding="utf-8").strip() == today:
            return
        cutoff = time.time() - int(cfg["log_retention_days"]) * 86400
        if LOG_FILE.exists():
            kept = []
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                        ts = datetime.strptime(rec["ts"], "%Y-%m-%d %H:%M:%S")
                        if ts.timestamp() >= cutoff:
                            kept.append(line)
                    except (json.JSONDecodeError, KeyError, ValueError):
                        continue
            LOG_FILE.write_text("".join(kept), encoding="utf-8")
        marker.write_text(today, encoding="utf-8")
    except OSError:
        pass
def is_degraded() -> bool:
    """当日估算成本是否已超熔断线（超线后 verify_llm 应回退本地引擎）。"""
    cfg = load_config()
    with _lock:
        _rollover_locked()
        return _day["cost"] >= float(cfg["daily_cost_limit"])
def status_for(identity: str, privileged: bool) -> dict:
    """查询单身份的余量与限流状态。"""
    cfg = load_config()
    now = time.time()
    with _lock:
        _rollover_locked()
        window = _rate.get(identity, deque())
        recent = sum(1 for t in window if t >= now - 60)
        quota = _quota_for(identity, privileged, cfg)
        used = _day["count"].get(identity, 0)
        return {
            "identity": identity,
            "privileged": privileged,
            "enabled": bool(cfg.get("enabled")),
            "rate_limit_per_minute": int(cfg["rate_limit_per_minute"]),
            "rate_used_this_minute": recent,
            "daily_quota": quota,
            "daily_used": used,
            "daily_remaining": max(0, quota - used),
            "degraded": _day["cost"] >= float(cfg["daily_cost_limit"]),
            "today_cost_estimate": round(_day["cost"], 2),
            "today_cost_limit": float(cfg["daily_cost_limit"]),
        }
def admin_stats() -> dict:
    """管理端汇总（仅本机可访问）。"""
    cfg = load_config()
    with _lock:
        _rollover_locked()
        per_identity = dict(_day["count"])
        total = sum(per_identity.values())
        return {
            "date": _day["date"],
            "enabled": bool(cfg.get("enabled")),
            "config": cfg,
            "today_total_calls": total,
            "today_cost_estimate": round(_day["cost"], 2),
            "degraded": _day["cost"] >= float(cfg["daily_cost_limit"]),
            "today_per_identity": per_identity,
            "tracked_identities": len(per_identity),
        }
