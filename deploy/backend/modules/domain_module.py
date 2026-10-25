"""③-C 领域知识层：覆盖「人 / 动物 / 人与动物 / 人与生活 / 人与自然 / 人与社会 / 社会与国家」
七大领域的通识共识条目。作为通识层的第二梯队，仅在 knowledge_module 未命中时参与匹配。
数据存放于 data/domains.json，不改动通识层主库的既有条目。
"""
from __future__ import annotations
import json
import re
import threading
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "domains.json"

_lock = threading.Lock()
_cache: dict | None = None


def _load() -> dict:
    """加载领域知识库（进程内缓存）。"""
    global _cache
    if _cache is not None:
        return _cache
    with _lock:
        if _cache is not None:
            return _cache
        try:
            with DATA_PATH.open("r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except Exception:
            raw = {"domains": [], "entries": []}
        entries = []
        for item in raw.get("entries", []):
            try:
                item["_compiled"] = [re.compile(p) for p in item.get("patterns", [])]
            except re.error:
                item["_compiled"] = []
            entries.append(item)
        _cache = {
            "domains": raw.get("domains", []),
            "entries": entries,
        }
        return _cache


def domain_stats() -> dict:
    """统计各领域条目数量，用于健康自检与前端展示。"""
    db = _load()
    counts: dict[str, int] = {}
    for item in db["entries"]:
        key = item.get("domain", "other")
        counts[key] = counts.get(key, 0) + 1
    names = {d["key"]: d.get("name", d["key"]) for d in db["domains"]}
    return {
        "total": len(db["entries"]),
        "domains": [
            {"key": k, "name": names.get(k, k), "count": v}
            for k, v in counts.items()
        ],
    }


def match_domain(text: str) -> dict | None:
    """匹配领域知识库，命中返回条目（结构兼容 knowledge 条目）。"""
    norm = re.sub(r"\s+", "", text or "")
    if len(norm) < 4:
        return None
    db = _load()
    # 先按原文命中，全部遍历取首个匹配；条目顺序即优先级
    for item in db["entries"]:
        for pat, compiled in zip(item.get("patterns", []), item.get("_compiled", [])):
            try:
                hit = compiled.search(norm) is not None
            except Exception:
                hit = False
            if hit:
                return item
    return None
