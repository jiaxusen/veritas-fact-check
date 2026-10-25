"""⑤ 查证卡生成模块：按固定结构组装查证卡。"""
from __future__ import annotations
import random
from datetime import datetime, timedelta, timezone
CST = timezone(timedelta(hours=8))
CRED_LABEL = {"A": "权威来源", "B": "可靠来源", "C": "一般来源", "D": "存疑来源"}
TYPE_LABEL = {
    "knowledge": "通识共识",
    "encyclopedia": "百科词条",
    "search": "联网检索",
    "local": "本地知识库",
    "remote": "在线核查",
}
# 在线侧专有字段：存在时随来源一起输出，前端据此渲染「原样命中」等徽标
_REMOTE_FIELDS = (
    "evidence_score", "evidence_exact", "evidence_locator", "evidence_rank", "evidence_query",
)
def _card_id() -> str:
    now = datetime.now(CST)
    return f"VC-{now:%Y%m%d}-{random.randint(1000, 9999)}"
def build_card(
    text: str,
    keywords: list[str],
    search_result: dict,
    check_result: dict,
    verdict: dict,
    engine: str,
    elapsed_ms: int,
    remote_view: dict | None = None,
    arbitration: dict | None = None,
) -> dict:
    """组装结构化查证卡。remote_view / arbitration 为在线融合后的可选附加信息。"""
    now = datetime.now(CST)
    sources = []
    for idx, src in enumerate(search_result.get("sources", []), start=1):
        stype = src.get("source_type", "search")
        item = {
            "id": f"S{idx}",
            "title": src.get("title", ""),
            "url": src.get("url", ""),
            "domain": src.get("domain", ""),
            "published_at": src.get("published_at", "—"),
            "credibility": src.get("credibility", "C"),
            "credibility_label": CRED_LABEL.get(src.get("credibility", "C"), "一般来源"),
            "credibility_score": src.get("credibility_score", 60),
            "snippet": src.get("snippet", ""),
            "source_type": stype,
            "source_type_label": TYPE_LABEL.get(stype, "联网检索"),
            "org_type": src.get("org_type", ""),
            "relevance": src.get("relevance", 0),
        }
        for field in _REMOTE_FIELDS:
            if src.get(field) is not None:
                item[field] = src[field]
        sources.append(item)
    src_map = {s["id"]: s for s in sources}
    def _decorate(items: list[dict]) -> list[dict]:
        out = []
        for it in items:
            s = src_map.get(it["source_id"])
            out.append({
                "point": it["point"],
                "claim": it["claim"],
                "source_id": it["source_id"],
                "source_title": s["title"] if s else "通识共识条目",
                "source_url": s["url"] if s else "",
                "source_domain": s["domain"] if s else "",
                "source_type_label": s["source_type_label"] if s else "通识共识",
                "strength": it["strength"],
                "weak_support": bool(it.get("weak_support")),
            })
        return out
    support = _decorate(check_result.get("support", []))
    refute = _decorate(check_result.get("refute", []))
    disputes: list[str] = []
    if check_result.get("has_conflict"):
        disputes.append(f"支持方来源 {len(support)} 条，反对方来源 {len(refute)} 条，双方结论不一致。")
        if support:
            disputes.append(f"支持方核心主张：{support[0]['claim']}")
        if refute:
            disputes.append(f"反对方核心主张：{refute[0]['claim']}")
    risk_notes = [
        "本查证结果基于公开可检索来源自动生成，不构成法律或专业鉴定意见。",
        "来源可信度评分由域名性质、发布时间、内容一致性、证据链四维加权得出。",
    ]
    if verdict["level"] == "uncertain":
        risk_notes.append("当前证据不足或存在分歧，请勿将「存疑」直接等同于「不实」。")
    if verdict["level"] in ("mostly_true", "partly_true"):
        risk_notes.append("「基本属实 / 部分属实」表示主体成立但表述可能存在简化或细节偏差，引用时建议核对权威原文。")
    if verdict.get("caveat"):
        risk_notes.append(f"严谨性提示：{verdict['caveat']}")
    if search_result.get("insufficient"):
        risk_notes.append("本次检索有效来源偏少，结论稳定性有限。")
    if arbitration and arbitration.get("applied"):
        engine_map = {
            "confirm": "在线核查与本地结论一致，已据此上调置信度。",
            "agree": "在线核查与本地结论方向一致，互为印证。",
            "adopt_remote": "本地证据不足，本卡结论采纳在线核查结果，请重点核对在线侧来源。",
            "adopt_remote_weak_local": "本地证据薄弱，结论以在线核查为准。",
            "both_uncertain": "本地与在线核查均判为存疑，请勿据此直接定性为不实。",
            "local_priority_conflict": "在线核查与本地权威层结论不一致，已保留本地结论并下调置信度。",
            "conflict_remote_wins": "本地与在线结论冲突，因在线来源可信度更高而采纳在线结论，建议人工复核。",
            "conflict_local_wins": "本地与在线结论冲突，因本地来源可信度更高而保留本地结论，建议人工复核。",
        }
        tip = engine_map.get(arbitration.get("action", ""))
        if tip:
            risk_notes.append(tip)
        if arbitration.get("note"):
            disputes.append(f"融合裁决备注：{arbitration['note']}")
    if remote_view and remote_view.get("limitation"):
        risk_notes.append(f"在线核查局限：{remote_view['limitation']}")
    return {
        "card_id": _card_id(),
        "created_at": now.isoformat(timespec="seconds"),
        "created_at_display": now.strftime("%Y-%m-%d %H:%M:%S"),
        "input_text": text,
        "keywords": keywords,
        "verdict": {
            "level": verdict["level"],
            "label": verdict["label"],
            "color": verdict["color"],
            "confidence": verdict["confidence"],
            "summary": verdict["summary"],
            "reason": verdict["reason"],
            "breakdown": verdict.get("breakdown", []),
        },
        "evidence": {"support": support, "refute": refute},
        "evidence_stats": {
            "support_count": len(support),
            "refute_count": len(refute),
            "source_count": len(sources),
        },
        "sources": sources,
        "disputes": disputes,
        "risk_notes": risk_notes,
        "engine": engine,
        "elapsed_ms": elapsed_ms,
        "remote": remote_view,
        "arbitration": arbitration,
    }