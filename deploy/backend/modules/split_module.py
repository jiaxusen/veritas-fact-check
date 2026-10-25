"""①-B 事实点拆分模块：把长文本拆成可独立核查的事实句。

解决的问题：一段话里半真半假时，整段只能给一个「存疑」结论，用户看不出错在哪一句。
例如：「河南财大有实验楼，还有空中操场」应拆为两句分别核验。

设计要点：
1. 按句末标点与分句逗号切分，保留每句在原文中的偏移量，供前端回指高亮；
2. 过短片段（无独立语义）合并到前一句，避免产生噪音任务；
3. 单句文本直接返回整句，不额外拆分。
"""
from __future__ import annotations
import re

MIN_SEGMENT = 6          # 低于该长度视为无独立语义
MAX_SEGMENTS = 6         # 单次最多核查的事实点数，控制耗时
SPLIT_RE = re.compile(r"[。！？；!?;…]+|(?<=[，,])(?=.{12,})")

LEVEL_ORDER = {"false": 0, "uncertain": 1, "partly_true": 2, "mostly_true": 3, "true": 4}


def split_claims(text: str) -> list[dict]:
    """拆分为事实点列表，每项含文本内容与在原文中的起止偏移。"""
    raw = (text or "").strip()
    if not raw:
        return []
    pieces: list[tuple[int, int]] = []
    start = 0
    for m in SPLIT_RE.finditer(raw):
        end = m.end()
        if end - start >= MIN_SEGMENT:
            pieces.append((start, end))
            start = end
    if start < len(raw):
        pieces.append((start, len(raw)))

    # 过短片段合并到前一片段
    merged: list[tuple[int, int]] = []
    for piece in pieces:
        if merged and piece[1] - piece[0] < MIN_SEGMENT:
            merged[-1] = (merged[-1][0], piece[1])
        else:
            merged.append(piece)

    items = []
    for s, e in merged:
        seg = raw[s:e].strip(" ，,、")
        if len(seg) < MIN_SEGMENT:
            continue
        offset = raw.find(seg, s)
        if offset < 0:
            offset = s
        items.append({"index": len(items), "text": seg, "start": offset, "end": offset + len(seg)})
    return items[:MAX_SEGMENTS]


def aggregate(segments: list[dict]) -> dict:
    """由各事实点结论聚合出整段结论：取最严重的一档，置信度取均值。"""
    if not segments:
        return {"level": "uncertain", "label": "存疑", "confidence": 0, "segments": []}
    worst = min(segments, key=lambda x: LEVEL_ORDER.get(x["verdict"]["level"], 1))
    avg = round(sum(s["verdict"]["confidence"] for s in segments) / len(segments))
    counter: dict[str, int] = {}
    for s in segments:
        counter[s["verdict"]["level"]] = counter.get(s["verdict"]["level"], 0) + 1
    return {
        "level": worst["verdict"]["level"],
        "label": worst["verdict"]["label"],
        "confidence": avg,
        "distribution": counter,
        "weakest": worst["text"],
    }
