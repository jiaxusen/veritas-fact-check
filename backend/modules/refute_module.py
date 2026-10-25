"""⑥-B 辟谣话术生成模块：把查证卡转成可直接转发的一段话。

用途：查完之后不只是自己知道，还要能一句话说清楚「为什么不真 / 依据是什么」。
优先使用规则模板（离线可用、可控），模板所需字段缺失时降级为要点式输出。
"""
from __future__ import annotations

MODE_TIP = {
    "balanced": "建议以权威来源发布的原文为准。",
    "strict": "当前为严谨模式，缺少权威来源时不轻易采信。",
    "loose": "当前为宽松模式，证据门槛较低，结论仅供参考。",
}


def build_script(card: dict, mode: str = "balanced") -> dict:
    """根据查证卡生成辟谣 / 澄清话术。"""
    text = (card.get("input_text") or "").strip()
    v = card.get("verdict", {})
    level = v.get("level", "uncertain")
    label = v.get("label", "存疑")
    conf = v.get("confidence", 0)
    summary = v.get("summary", "")
    sources = card.get("sources", []) or []
    top_src = sources[0] if sources else None
    refute = (card.get("evidence", {}) or {}).get("refute", []) or []
    support = (card.get("evidence", {}) or {}).get("support", []) or []

    head = f"关于「{text}」的说法"
    tail = MODE_TIP.get(mode, MODE_TIP["balanced"])

    if level in ("false",):
        key = refute[0]["point"] if refute else summary
        body = (
            f"{head}，核查结论为【{label}】（置信度 {conf}%）。{key}"
            f"权威依据见 {top_src['domain'] if top_src else '来源清单'}，请勿轻信或转发。"
        )
        action = "可直接转发本条澄清，或附上查证卡编号供对方核对。"
    elif level in ("uncertain",):
        body = (
            f"{head}，目前核查结论为【{label}】（置信度 {conf}%），"
            f"即现有公开资料不足以证实或证伪。原因：{summary}。{tail}"
        )
        action = "在获得更具体的时间、地点、机构等信息后再次查证，暂不建议定性。"
    elif level in ("partly_true", "mostly_true"):
        body = (
            f"{head}，核查结论为【{label}】（置信度 {conf}%）：主体成立但表述存在偏差。{summary}。{tail}"
        )
        action = "引用时建议附上原始出处，避免二次传播中被简化。"
    else:
        key = support[0]["point"] if support else summary
        body = f"{head}，核查结论为【{label}】（置信度 {conf}%）。{key}{tail}"
        action = "属实信息可正常传播，建议同时附上来源链接便于他人复核。"

    points = [
        f"结论：{label}（置信度 {conf}%）",
        f"卡片编号：{card.get('card_id', '—')}",
    ]
    if refute:
        points.append(f"关键反证：{refute[0]['point'][:60]}")
    if top_src:
        points.append(f"首选来源：{top_src.get('title', '')}（{top_src.get('domain', '')}）")

    return {"script": body, "action": action, "points": points}
