"""② 全网检索模块（增强版）：关键词 → 联网多源检索 → 通识层 → 领域层 → 高校层 → 本地谣言库 → 归一化。
优先级：通识共识 > 领域/高校知识层 > 本地已核实谣言库 > 联网检索结果。
本地库是人工校验过的结论，对典型谣言比联网噪音更可靠。
"""
from __future__ import annotations
import json
from pathlib import Path
from modules.keyword_module import build_queries, extract_keywords
from modules.knowledge_module import knowledge_sources, match_knowledge
from modules.domain_module import match_domain
from modules.university_module import match_university
from modules.web_search_module import web_search
DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "sources.json"
_CRED_RANK = {"A": 3, "B": 2, "C": 1, "D": 0}
def _load_db() -> dict:
    try:
        with DATA_PATH.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {"facts": [], "fallback_sources": []}
def _local_search(keywords: list[str], text: str) -> tuple[list[dict], dict | None]:
    """本地已核实事实库检索。返回 (来源列表, 命中的事实条目)。"""
    db = _load_db()
    best_fact: dict | None = None
    best_hits = 0
    for fact in db.get("facts", []):
        ents = fact.get("entities", [])
        hits = sum(1 for k in keywords if k in ents or k in fact.get("claim", ""))
        # 原文直接包含实体也算命中
        hits += sum(1 for ent in ents if ent in text and ent not in keywords)
        if hits > best_hits:
            best_hits = hits
            best_fact = fact
    if not best_fact or best_hits < 2:
        return [], None
    out: list[dict] = []
    for src in best_fact.get("sources", []):
        item = dict(src)
        item["source_type"] = "local"
        item["org_type"] = "已核实事实库"
        item["relevance"] = 0.9
        out.append(item)
    return out, best_fact
def search(keywords: list[str], text: str) -> dict:
    """执行检索：通识层 + 领域扩展层 + 本地事实库 + 联网检索，分层合并。"""
    # 主通识库优先；未命中依次交由七大领域层、高校层
    knowledge = match_knowledge(text)
    if not knowledge:
        knowledge = match_domain(text)
    if not knowledge:
        knowledge = match_university(text)
    local_sources, local_fact = _local_search(keywords, text)
    web = web_search(keywords, text, max_sources=8)
    sources: list[dict] = []
    trace: list[dict] = []
    # ① 通识层（最高优先）
    if knowledge:
        ks = knowledge_sources(knowledge)
        for s in ks:
            s["relevance"] = 1.0
        sources.extend(ks)
        trace.append({"channel": "knowledge", "query": knowledge["name"], "hits": len(ks)})
    # ② 本地已核实事实库
    if local_sources:
        sources.extend(local_sources)
        trace.append({
            "channel": "local",
            "query": local_fact.get("topic", "本地事实库"),
            "hits": len(local_sources),
        })
    # ③ 联网检索
    sources.extend(web["sources"])
    trace.extend(web["trace"])
    # ④ 去重
    seen: set[str] = set()
    filtered: list[dict] = []
    for src in sources:
        key = src.get("url", "").rstrip("/")
        if not key or key in seen:
            continue
        if _CRED_RANK.get(src.get("credibility", "C"), 1) < 1:
            continue
        seen.add(key)
        filtered.append(src)
    # ⑤ 排序：通识 > 本地事实 > 相关性+可信度
    def _rank(s: dict) -> tuple:
        stype = s.get("source_type", "search")
        tier = {"knowledge": 3, "local": 2}.get(stype, 1)
        return (tier, s.get("relevance", 0) * 0.6 + s.get("credibility_score", 60) / 100 * 0.4)
    filtered.sort(key=_rank, reverse=True)
    filtered = filtered[:8]
    return {
        "keywords": keywords,
        "queries": build_queries(keywords, text),
        "candidates": [],
        "sources": filtered,
        "insufficient": len(filtered) < 2,
        "source_count": len(filtered),
        "knowledge": knowledge,
        "local_fact": local_fact,
        "trace": trace,
        "engine": web["engine"],
    }