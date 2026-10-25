"""大模型引擎适配层：配置密钥后自动启用真实检索 + 三段式提示词核对。
未配置密钥时，自动回退到本地查证引擎（pipeline.run_pipeline）。
"""
from __future__ import annotations
import json
import os
import re
SEARCH_PROMPT = """你是查证助手。请从下面的待核实文本中提取核心实体与搜索关键词。
要求：只输出 JSON 数组，1-3 个关键词，不要解释。
待核实文本：{text}"""
CHECK_PROMPT = """你是事实核查员。给定原文与候选来源，请逐条比对。
要求：只输出 JSON，格式为
{{"support":[{{"point":"支持要点","source_index":1}}],"refute":[{{"point":"矛盾要点","source_index":2}}]}}
若某方向无证据，对应数组留空。不要编造来源。
原文：{text}
来源列表：
{sources}"""
GRADE_PROMPT = """你是可信度分级员。根据核对结果给出结论。
要求：只输出 JSON，格式为
{{"level":"true|false|uncertain","confidence":0-100,"summary":"一句话说明","reason":"判定理由"}}
分级规则：多个可信来源一致支持→true；多个可信来源一致否定→false；证据不足或冲突→uncertain。
核对结果：{check}"""
def is_llm_available() -> bool:
    provider = os.getenv("MODEL_PROVIDER", "openai").upper()
    return bool(os.getenv(f"{provider}_API_KEY")) and bool(os.getenv(f"{provider}_BASE_URL"))
def _client():
    from openai import OpenAI
    provider = os.getenv("MODEL_PROVIDER", "openai").upper()
    return OpenAI(
        api_key=os.getenv(f"{provider}_API_KEY"),
        base_url=os.getenv(f"{provider}_BASE_URL"),
    )
def _model() -> str:
    provider = os.getenv("MODEL_PROVIDER", "openai").upper()
    return os.getenv(f"{provider}_MODEL") or os.getenv(f"{provider}_FAST_MODEL") or "gpt-4o-mini"
def _ask(prompt: str) -> str:
    resp = _client().chat.completions.create(
        model=_model(),
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    return resp.choices[0].message.content or ""
def _parse_json(raw: str):
    match = re.search(r"[\[{].*[\]}]", raw, re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
def llm_extract_keywords(text: str) -> list[str] | None:
    data = _parse_json(_ask(SEARCH_PROMPT.format(text=text)))
    if isinstance(data, list) and data:
        return [str(k) for k in data][:3]
    return None
def llm_cross_check(text: str, sources: list[dict]) -> dict | None:
    listing = "\n".join(
        f"[{i}] {s['title']} | {s['domain']} | {s['published_at']} | {s['snippet']}"
        for i, s in enumerate(sources, start=1)
    )
    data = _parse_json(_ask(CHECK_PROMPT.format(text=text, sources=listing)))
    if not isinstance(data, dict):
        return None
    def _norm(items, bucket):
        out = []
        for it in items or []:
            idx = int(it.get("source_index", 1)) - 1
            if 0 <= idx < len(sources):
                out.append({
                    "point": str(it.get("point", "")),
                    "claim": sources[idx]["snippet"][:60],
                    "source_id": f"S{idx + 1}",
                    "strength": 0.9 if bucket == "support" else 0.9,
                })
        return out
    return {
        "support": _norm(data.get("support"), "support"),
        "refute": _norm(data.get("refute"), "refute"),
        "neutral": [],
        "has_conflict": bool(data.get("support")) and bool(data.get("refute")),
        "candidate_count": len(sources),
    }
def llm_grade(check_result: dict, search_result: dict) -> dict | None:
    from modules.grade_module import VERDICT_META
    data = _parse_json(_ask(GRADE_PROMPT.format(check=json.dumps(check_result, ensure_ascii=False))))
    if not isinstance(data, dict):
        return None
    level = data.get("level", "uncertain")
    if level not in VERDICT_META:
        level = "uncertain"
    meta = VERDICT_META[level]
    return {
        **meta,
        "confidence": int(data.get("confidence", 50)),
        "summary": str(data.get("summary", "")),
        "reason": str(data.get("reason", "")),
    }