"""④ 可信度分级模块：支持五档结论 + 三档核查模式。
true        属实
mostly_true 基本属实（学界共识 / 主流表述）
partly_true 部分属实（有真实成分但表述不严谨）
uncertain   存疑（证据不足或存在分歧）
false       不实
mode: balanced 均衡 / strict 严谨（更高证据门槛）/ loose 宽松（更低门槛）
"""
from __future__ import annotations
VERDICT_META = {
    "true": {"level": "true", "label": "属实", "color": "#22D39A"},
    "mostly_true": {"level": "mostly_true", "label": "基本属实", "color": "#3DDC97"},
    "partly_true": {"level": "partly_true", "label": "部分属实", "color": "#7ED957"},
    "uncertain": {"level": "uncertain", "label": "存疑", "color": "#FFB020"},
    "false": {"level": "false", "label": "不实", "color": "#FF4D6D"},
}
# 各模式的最小来源数阈值
_MIN_SOURCES = {"balanced": 2, "strict": 3, "loose": 1}
def _weighted(items: list[dict], sources: list[dict]) -> float:
    """按来源可信度加权证据强度。source_id 形如 S1 / K1 / L1。"""
    if not items:
        return 0.0
    total = 0.0
    for it in items:
        sid = str(it.get("source_id", ""))
        cred = 0.6
        if sid.startswith("K"):
            cred = 0.95
        elif sid.startswith("L"):
            cred = 0.93
        elif sid.startswith("S"):
            try:
                idx = int(sid[1:]) - 1
                if 0 <= idx < len(sources):
                    cred = sources[idx].get("credibility_score", 60) / 100
            except (ValueError, IndexError):
                pass
        total += it["strength"] * (0.5 + cred * 0.5)
    return total
def grade(check_result: dict, search_result: dict, mode: str = "balanced") -> dict:
    """根据核对结果判定可信度（五档）。"""
    if mode not in _MIN_SOURCES:
        mode = "balanced"
    min_src = _MIN_SOURCES[mode]
    support = check_result.get("support", [])
    refute = check_result.get("refute", [])
    sources = search_result.get("sources", [])
    source_count = search_result.get("source_count", len(sources))
    knowledge = check_result.get("knowledge")
    local_fact = check_result.get("local_fact")
    # ① 通识共识优先：直接采信知识库既定档位
    if knowledge:
        level = knowledge.get("level", "mostly_true")
        if level not in VERDICT_META:
            level = "mostly_true"
        conf_map = {"true": 92, "mostly_true": 86, "partly_true": 78, "false": 86, "uncertain": 55}
        if mode == "strict" and level in ("true", "false"):
            conf_map[level] = max(conf_map[level] - 4, 70)
        return {
            **VERDICT_META[level],
            "confidence": conf_map.get(level, 80),
            "summary": knowledge.get("explain", "")[:200],
            "reason": (
                f"命中通识共识条目「{knowledge.get('name')}」"
                f"（{knowledge.get('consensus')}），并检索到 {source_count} 条相关来源佐证"
            ),
            "knowledge_id": knowledge.get("id"),
            "caveat": knowledge.get("caveat", ""),
        }
    # ② 本地已核实事实库命中 → 采信既定结论
    if local_fact:
        strong_refute = [r for r in refute if r["strength"] >= 0.7 and not r.get("is_local")]
        strong_support = [s for s in support if s["strength"] >= 0.7 and not s.get("is_local")]
        fv = local_fact.get("verdict", "true")
        if fv == "false" and not strong_support:
            return {
                **VERDICT_META["false"],
                "confidence": 88,
                "summary": local_fact.get("explain") or f"该说法与已核实事实库中的结论相反：{local_fact.get('claim', '')}",
                "reason": f"命中已核实事实库条目「{local_fact.get('topic')}」，结论为不实",
                "knowledge_id": local_fact.get("id"),
            }
        if fv == "true" and not strong_refute:
            return {
                **VERDICT_META["true"],
                "confidence": 88,
                "summary": local_fact.get("explain") or f"该说法与已核实事实库中的结论一致：{local_fact.get('claim', '')}",
                "reason": f"命中已核实事实库条目「{local_fact.get('topic')}」，结论为属实",
                "knowledge_id": local_fact.get("id"),
            }
    s_score = _weighted(support, sources)
    r_score = _weighted(refute, sources)
    # ③ 来源不足（阈值随模式变化）
    if source_count < min_src or (not support and not refute):
        return {
            **VERDICT_META["uncertain"],
            "confidence": 32,
            "summary": "可核验来源不足，暂无法给出确定结论，建议补充更具体的信息后再查证。",
            "reason": f"有效来源 {source_count} 条，低于当前模式判定阈值（{min_src} 条）",
        }
    # ④ 支持与矛盾并存且强度接近
    if support and refute:
        gap = abs(s_score - r_score)
        if gap < 0.35:
            return {
                **VERDICT_META["uncertain"],
                "confidence": 48,
                "summary": "不同来源存在明显分歧，支持与矛盾证据并存，暂判定为存疑。",
                "reason": f"支持证据 {len(support)} 条 / 矛盾证据 {len(refute)} 条，强度接近",
            }
    # ⑤ 支持占优
    if s_score > r_score:
        strong = [i for i in support if i["strength"] >= 0.75]
        need_strong = 3 if mode == "strict" else 2
        if len(strong) >= need_strong:
            conf = int(min(78 + s_score * 6, 96))
            return {
                **VERDICT_META["true"],
                "confidence": conf,
                "summary": f"检索到 {len(support)} 条来源支持该说法，其中 {len(strong)} 条为高强度证据，未发现有效反驳。",
                "reason": f"支持证据加权强度 {s_score:.2f}，矛盾证据 {r_score:.2f}",
            }
        conf = int(min(62 + s_score * 6, 82))
        return {
            **VERDICT_META["mostly_true"],
            "confidence": conf,
            "summary": f"检索到 {len(support)} 条来源总体支持该说法，但证据强度中等，建议结合权威原文确认细节。",
            "reason": f"支持证据加权强度 {s_score:.2f}，高强度证据 {len(strong)} 条",
        }
    # ⑥ 反驳占优
    if r_score > s_score:
        conf = int(min(75 + r_score * 6, 96))
        return {
            **VERDICT_META["false"],
            "confidence": conf,
            "summary": f"检索到 {len(refute)} 条来源否定该说法，矛盾证据充分。",
            "reason": f"矛盾证据加权强度 {r_score:.2f}，支持证据 {s_score:.2f}",
        }
    return {
        **VERDICT_META["uncertain"],
        "confidence": 40,
        "summary": "证据强度不足，暂无法判定真伪。",
        "reason": "支持与矛盾证据均不足以支撑结论",
    }