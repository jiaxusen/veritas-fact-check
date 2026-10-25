"""③-C 启发式研判模块：在检索证据不足时，基于语言特征给出审慎判断。
作用：避免所有"查不到"的陈述都机械判为"存疑"。
识别维度：
1. 绝对化断言（一定/必然/唯一/绝对/100%）→ 可信度打折
2. 谣言句式（据说/网传/震惊/速转/千万别）→ 高风险
3. 科普句式（研究表明/数据显示/据…记载）→ 相对可信
4. 可证伪的具体数值 → 需要权威来源佐证
"""
from __future__ import annotations
import re
# 谣言/夸张句式
_RUMOR_PATTERNS = [
    r"震惊", r"速转", r"千万别", r"一定要看", r"99%的人", r"百分之九十九",
    r"医生都", r"专家都不敢", r"央视曝光", r"内部消息", r"紧急通知",
    r"致癌", r"有毒", r"致命", r"立刻", r"马上删", r"不转不是",
]
# 绝对化表述
_ABSOLUTE_PATTERNS = [r"一定", r"必然", r"绝对", r"唯一", r"100%", r"百分百", r"从不", r"永远"]
# 科普/严谨表述
_SCIENTIFIC_PATTERNS = [
    r"研究表明", r"数据显示", r"实验证明", r"据.{0,6}记载", r"调查显示",
    r"一般认为", r"学界", r"共识", r"标准", r"指南",
]
def analyze_tone(text: str) -> dict:
    """分析文本的语言特征，返回风险画像。"""
    norm = re.sub(r"\s+", "", text or "")
    rumor_hits = [p for p in _RUMOR_PATTERNS if re.search(p, norm)]
    absolute_hits = [p for p in _ABSOLUTE_PATTERNS if re.search(p, norm)]
    sci_hits = [p for p in _SCIENTIFIC_PATTERNS if re.search(p, norm)]
    # 风险分：谣言句式权重最高
    risk = len(rumor_hits) * 0.35 + len(absolute_hits) * 0.15 - len(sci_hits) * 0.2
    risk = max(0.0, min(risk, 1.0))
    if risk >= 0.5:
        tone = "high_risk"
        tone_label = "高风险表述"
    elif risk >= 0.2:
        tone = "caution"
        tone_label = "需谨慎对待"
    elif sci_hits:
        tone = "scientific"
        tone_label = "表述较严谨"
    else:
        tone = "neutral"
        tone_label = "中性陈述"
    return {
        "risk": round(risk, 2),
        "tone": tone,
        "tone_label": tone_label,
        "rumor_markers": rumor_hits,
        "absolute_markers": absolute_hits,
        "scientific_markers": sci_hits,
    }
def heuristic_verdict(text: str, tone: dict) -> dict | None:
    """证据不足时的启发式研判（仅在高风险时给出倾向性提示）。"""
    if tone["tone"] == "high_risk":
        return {
            "suggest": "likely_false",
            "confidence": 45,
            "summary": (
                "该表述包含明显的煽动性或绝对化用语"
                f"（{'、'.join(tone['rumor_markers'][:3])}），"
                "且未检索到权威来源支持。此类表述常见于网络谣言，建议保持警惕，"
                "并以权威机构发布的信息为准。"
            ),
            "reason": f"语言特征风险分 {tone['risk']}，命中谣言句式 {len(tone['rumor_markers'])} 处",
        }
    return None