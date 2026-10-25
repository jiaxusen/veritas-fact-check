"""③ 信息核对模块：对比原文与来源，抽取支持 / 矛盾 / 中立证据。
关键设计：
1. 否定判定必须"否定信号词 + 与原文语义重合"同时成立。
2. 通识共识条目 / 本地已核实事实作为最高强度证据。
3. 语义重合度低的来源归入中立，不参与真伪判定。
"""
from __future__ import annotations
import re
_NEGATIVE_CUES = (
    "并非如此", "不是真的", "并无此事", "没有证据", "缺乏依据", "纯属谣言",
    "不实信息", "错误说法", "常见误区", "辟谣", "不成立", "无科学依据",
    "以讹传讹", "夸大其词", "系谣言", "假的", "myth", "debunk", "false claim",
)
_POSITIVE_CUES = (
    "证实", "表明", "显示", "实证", "确认", "证明", "研究显示", "数据表明",
    "结论是", "已列入", "公认", "共识", "据记载", "考古发现",
)
# 标题层面的"求证/辟谣语境"：这类页面本身不构成支持证据
_QUERY_TITLE_CUES = (
    "吗", "？", "?", "真的", "是真是假", "真相", "辟谣", "谣言", "会不会",
    "可信", "传闻", "据说", "疑问", "解密", "究竟",
)
# 事实核查 / 辟谣类专业来源：其内容天然倾向于否证待核实说法
_CHECK_ORG_TYPES = ("辟谣平台", "事实核查")


def _authoritative_refute(src: dict, overlap: float) -> bool:
    """专业辟谣/核查来源且语义重合时，视为反证。"""
    if src.get("org_type") in _CHECK_ORG_TYPES and overlap >= 0.2:
        return True
    return False
def _tokens(text: str) -> set[str]:
    chars = [c for c in text if "\u4e00" <= c <= "\u9fa5" or c.isalnum()]
    grams = {chars[i] + chars[i + 1] for i in range(len(chars) - 1)}
    nums = set(re.findall(r"\d+(?:\.\d+)?", text))
    words = set(re.findall(r"[A-Za-z]{3,}", text.lower()))
    return grams | nums | words
def _overlap(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta)
def _has_cue(text: str, cues: tuple[str, ...]) -> bool:
    low = text.lower()
    return any(c.lower() in low for c in cues)
def cross_check(text: str, search_result: dict, knowledge: dict | None = None) -> dict:
    """核对原文与检索结果，输出结构化核对结果。"""
    sources = search_result.get("sources", [])
    local_fact = search_result.get("local_fact")
    support: list[dict] = []
    refute: list[dict] = []
    neutral: list[dict] = []
    for idx, src in enumerate(sources, start=1):
        sid = f"S{idx}"
        snippet = src.get("snippet", "")
        title = src.get("title", "")
        overlap = _overlap(text, snippet)
        cred = src.get("credibility_score", 60) / 100
        base = 0.35 + overlap * 0.5 + cred * 0.15
        weak_support = False
        # 求证式标题（ "…会致癌吗" ）不足以支撑任何结论，直接归为中立
        is_query_title = _has_cue(title, _QUERY_TITLE_CUES)
        if is_query_title and overlap < 0.5:
            neutral.append({
                "point": snippet[:120],
                "claim": "该来源为求证式内容，未给出确定结论",
                "source_id": sid,
                "strength": round(base * 0.5, 2),
                "overlap": round(overlap, 3),
            })
            continue
        if _authoritative_refute(src, overlap) or (
            _has_cue(snippet, _NEGATIVE_CUES) and overlap >= 0.2
        ):
            bucket = refute
            base += 0.12
        elif _has_cue(snippet, _POSITIVE_CUES) and overlap >= 0.15:
            bucket = support
            base += 0.08
        elif is_query_title and overlap >= 0.5:
            neutral.append({
                "point": snippet[:120],
                "claim": "该来源为求证式内容，未给出确定结论",
                "source_id": sid,
                "strength": round(base * 0.5, 2),
                "overlap": round(overlap, 3),
            })
            continue
        elif overlap >= 0.45:
            # 语义高度重合但无显性肯定信号：记为「弱支持」
            # 它只能作为旁证，不足以推翻本地已核实事实库的结论
            bucket = support
            base = min(base, 0.72)
            weak_support = True
        elif overlap >= 0.28:
            neutral.append({
                "point": snippet[:120],
                "claim": "与原文主题相关，但未给出明确的肯定或否定表述",
                "source_id": sid,
                "strength": round(base * 0.6, 2),
                "overlap": round(overlap, 3),
            })
            continue
        else:
            bucket = neutral
            base *= 0.7
        bucket.append({
            "point": snippet[:120],
            "claim": snippet[:60],
            "source_id": sid,
            "strength": round(min(base, 0.98), 2),
            "overlap": round(overlap, 3),
            "weak_support": weak_support,
        })
    # 通识条目：最高强度支持
    if knowledge:
        for i, ks in enumerate(knowledge.get("sources", []), start=1):
            support.append({
                "point": ks.get("snippet", "")[:120],
                "claim": knowledge.get("consensus", ""),
                "source_id": f"K{i}",
                "strength": 0.95,
                "overlap": 1.0,
                "is_knowledge": True,
            })
    # 本地已核实事实：按既定 verdict 归类为支持或反驳
    if local_fact:
        fv = local_fact.get("verdict", "true")
        target = support if fv == "true" else refute
        for src in local_fact.get("sources", []):
            target.append({
                "point": src.get("snippet", "")[:120],
                "claim": local_fact.get("claim", "")[:60],
                "source_id": f"L{len(target) + 1}",
                "strength": 0.93,
                "overlap": 1.0,
                "is_local": True,
            })
    support.sort(key=lambda x: x["strength"], reverse=True)
    refute.sort(key=lambda x: x["strength"], reverse=True)
    return {
        "support": support,
        "refute": refute,
        "neutral": neutral,
        "has_conflict": bool(support) and bool(refute),
        "candidate_count": len(sources),
        "knowledge": knowledge,
        "local_fact": local_fact,
    }