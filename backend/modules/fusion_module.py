"""融合模块：把在线查证台的判定 + 证据并入本地流水线。

在线侧提供的三样本地匮乏的能力：
1. 多事实点拆分判定（claims[] 逐句给出结论与依据说明）；
2. 证据打分与定位（score / exact / rank / locator —— 原样命中与原文位置可追溯）；
3. 官方与辟谣类来源的高命中检索。

融合策略（始终可解释，不做黑箱覆盖）：
- 本地命中的「通识共识」「已核实事实库」优先级最高，在线侧只做佐证或提示冲突；
- 本地未在权威层命中时，在线结论作为强证据组进入 grading；
- 若本地因来源不足判为存疑而在线给出明确结论，则采纳在线结论并注明来源；
- 两侧结论冲突且各自都有证据时，交由来源可信度更高的一侧定性，并下调置信度。
"""
from __future__ import annotations
import re
from modules.grade_module import VERDICT_META

_LEVEL_ORDER = {"false": 0, "uncertain": 1, "partly_true": 2, "mostly_true": 3, "true": 4}
_TIER = {"knowledge": 4, "local": 3, "remote": 2, "search": 1}
_POSITIVE = ("true", "mostly_true", "partly_true")
_MAX_REMOTE_SOURCES = 6
_MAX_SOURCES = 10


def _norm_url(url: str) -> str:
    """统一 URL 形态用于去重（去协议、去 www、去锚点与斜杠）。"""
    u = (url or "").strip()
    u = re.sub(r"^https?://", "", u, flags=re.I)
    u = u.split("#")[0].rstrip("/")
    u = re.sub(r"^www\.", "", u, flags=re.I)
    return u.lower()


def merge_sources(search_result: dict, remote: dict | None) -> tuple[dict, dict]:
    """把在线证据并入本地来源清单。返回 (search_result, 在线证据ID → 本地来源ID 映射)。"""
    ev_map: dict[str, str] = {}
    if not remote or not remote.get("evidences"):
        return search_result, ev_map
    sources = list(search_result.get("sources", []))
    existing = {_norm_url(s.get("url", "")) for s in sources}
    added = 0
    for ev in remote["evidences"]:
        if added >= _MAX_REMOTE_SOURCES:
            break
        key = _norm_url(ev.get("url", ""))
        if not key or key in existing:
            continue
        existing.add(key)
        sources.append({
            "title": ev.get("title", ""),
            "url": ev.get("url", ""),
            "domain": ev.get("domain", ""),
            "published_at": ev.get("published_at", "—"),
            "credibility": ev.get("credibility", "C"),
            "credibility_score": ev.get("credibility_score", 65),
            "snippet": ev.get("quote", ""),
            "source_type": "remote",
            "org_type": ev.get("type", ""),
            "relevance": ev.get("relevance", 0.6),
            "evidence_score": ev.get("score", 0),
            "evidence_exact": bool(ev.get("exact")),
            "evidence_locator": ev.get("locator", ""),
            "evidence_rank": ev.get("rank"),
            "evidence_query": ev.get("query", ""),
        })
        added += 1
    if not added:
        return search_result, ev_map

    def _rank(s: dict) -> tuple:
        tier = _TIER.get(s.get("source_type", "search"), 1)
        return (tier, s.get("relevance", 0) * 0.6 + s.get("credibility_score", 60) / 100 * 0.4)

    sources.sort(key=_rank, reverse=True)
    sources = sources[:_MAX_SOURCES]
    # 按最终顺序回填「在线证据 → 本地来源编号」映射，供核对与展示引用
    for idx, src in enumerate(sources, start=1):
        if src.get("source_type") != "remote":
            continue
        sid = f"S{idx}"
        for ev in remote["evidences"]:
            if _norm_url(ev.get("url", "")) == _norm_url(src.get("url", "")):
                ev_map[ev["id"]] = sid
                break
    search_result["sources"] = sources
    search_result["source_count"] = len(sources)
    search_result["insufficient"] = len(sources) < 2
    trace = search_result.get("trace", [])
    trace.append({
        "channel": "remote",
        "query": (remote.get("evidences") or [{}])[0].get("query", "在线核查"),
        "hits": added,
    })
    search_result["trace"] = trace
    search_result["remote"] = remote
    return search_result, ev_map


def _remote_sid_map(remote: dict | None, ev_map: dict, sources: list[dict]) -> dict[str, str]:
    """在线来源编号 → 本地来源编号 的映射表。

    在线侧的 reasoning / note 里会用 S1、S4、S5 引用它自己检索到的全部来源
    （srcCount 条），而本地卡片只保留通过核验的证据，编号不一致会产生"指向空引用"。
    这里按来源名称把在线编号翻译成卡片里真实存在的编号。
    """
    mapping: dict[str, str] = {}
    if not remote:
        return mapping
    trace = remote.get("trace") or []
    if not trace:
        return mapping
    # 在线编号 → 来源名称（trace 与 S 编号同序）
    online_names: dict[str, str] = {}
    for idx, item in enumerate(trace, start=1):
        name = str((item or {}).get("name") or "").strip()
        if name:
            online_names[str(idx)] = name
    # 本地编号 → 来源名称（只取在线证据，避免本地来源串号）
    local_names: dict[str, str] = {}
    for ev in remote.get("evidences", []):
        sid = ev_map.get(ev.get("id", ""), "")
        if sid:
            local_names[sid] = str(ev.get("name") or ev.get("title") or "").strip()
    for num, oname in online_names.items():
        best_sid, best_hit = "", 0
        for sid, lname in local_names.items():
            if not lname or not oname:
                continue
            head = oname[:12]
            hit = 1 if (oname == lname or oname in lname or lname in oname) else 0
            if not hit and head and head in lname:
                hit = 1
            if hit and len(head) >= best_hit:
                best_sid, best_hit = sid, len(head)
        if best_sid:
            mapping[num] = best_sid
    return mapping


def _rewrite_ids(text: str, sid_map: dict[str, str]) -> str:
    """把文本里的在线 S 编号替换为本地卡片编号。

    在线侧会引用它自己检索到的全部来源，但本地卡片只保留通过核验的证据，
    因此未被并入的来源编号会被直接剔除，避免前端出现指向空的引用。
    """
    raw = str(text or "")
    if not raw or not sid_map:
        return raw
    def _sub(m):
        # 在线文本里常写成「S4Cochrane」这种无分隔符形式，故不要求编号后有边界
        return sid_map.get(m.group(1), "\x00")  # 未映射的用占位符，稍后连同分隔符剔除
    out = re.sub(r"S(\d{1,2})(?!\d)", _sub, raw)
    # 剔除未映射引用，并顺带吃掉紧邻的顿号
    out = re.sub(r"[、,，]\s*\x00", "", out)
    out = re.sub(r"\x00\s*[、,，]", "", out)
    out = out.replace("\x00", "")
    # 清理残留的空括号与多余空白
    out = re.sub(r"、\s*、+", "、", out)
    out = re.sub(r"[、,，]\s*(?=[。；;])", "", out)
    out = re.sub(r"[（(]\s*[)）]", "", out)
    out = re.sub(r"^[、,，]\s*", "", out)
    out = re.sub(r"\s{2,}", " ", out)
    return out.strip()


def _strength(confidence: int, cred_score: int, exact: bool) -> float:
    base = (confidence / 100) * 0.62 + (cred_score / 100) * 0.28
    if exact:
        base += 0.06
    return round(min(0.95, max(0.35, base)), 2)


def attach_remote_claims(check_result: dict, remote: dict | None, ev_map: dict, sources: list[dict]) -> dict:
    """把在线侧的逐条事实点结论转成本地 support / refute / neutral 依据。"""
    if not remote:
        return check_result
    conf = int(remote.get("confidence", 70))
    cred_map = {s.get("url", ""): s.get("credibility_score", 65) for s in sources}
    sid_map = _remote_sid_map(remote, ev_map, sources)
    claims = list(remote.get("claims") or [])
    if not claims and remote.get("conclusion"):
        # 在线侧未拆分事实点时，用整句结论兜底
        claims = [{
            "id": "C1", "text": "", "level": remote.get("level", "uncertain"),
            "label": VERDICT_META.get(remote.get("level", "uncertain"), {}).get("label", ""),
            "note": remote.get("conclusion", ""), "source_id": (remote.get("evidences") or [{}])[0].get("id", ""),
        }]
    for claim in claims:
        level = claim.get("level", "uncertain")
        src_id = ev_map.get(claim.get("source_id", ""), "")
        target_source = None
        if src_id:
            try:
                target_source = sources[int(src_id[1:]) - 1]
            except (ValueError, IndexError):
                target_source = None
        cred = (target_source or {}).get("credibility_score", 68)
        exact = bool((target_source or {}).get("evidence_exact"))
        point = claim.get("note") or claim.get("text") or remote.get("conclusion", "")
        item = {
            "point": _rewrite_ids(point, sid_map)[:220],
            "claim": claim.get("text") or remote.get("title", ""),
            "source_id": src_id,
            "strength": _strength(conf, cred, exact),
            "overlap": 1.0 if exact else 0.8,
            "is_remote": True,
            "remote_level": level,
            "claim_id": claim.get("id", ""),
        }
        if level in ("false",):
            check_result.setdefault("refute", []).append(item)
        elif level in _POSITIVE:
            check_result.setdefault("support", []).append(item)
        else:
            check_result.setdefault("neutral", []).append(item)
    for key in ("support", "refute"):
        check_result[key] = sorted(check_result.get(key, []), key=lambda x: x["strength"], reverse=True)
    if check_result.get("support") and check_result.get("refute"):
        check_result["has_conflict"] = True
    check_result["remote"] = remote
    return check_result


def _label(level: str) -> str:
    return VERDICT_META.get(level, VERDICT_META["uncertain"])["label"]


def _evidence_credibility(check_result: dict, search_result: dict) -> list[int]:
    """返回真正参与 support / refute 的本地（非在线）来源可信度分值列表。

    只看「被引用过的来源」，避免填满来源清单却没进证据的无关检索结果虚高本地权威度。
    """
    sources = search_result.get("sources", [])
    scores: list[int] = []
    for bucket in ("support", "refute"):
        for item in check_result.get(bucket, []):
            if item.get("is_remote"):
                continue
            sid = str(item.get("source_id", ""))
            if sid.startswith(("K", "L")):
                scores.append(95 if sid.startswith("K") else 93)
                continue
            if not sid.startswith("S"):
                continue
            try:
                src = sources[int(sid[1:]) - 1]
            except (ValueError, IndexError):
                continue
            if src.get("source_type") == "remote":
                continue
            scores.append(int(src.get("credibility_score", 60)))
    return scores


def arbitrate(verdict: dict, remote: dict | None, check_result: dict, search_result: dict, mode: str = "balanced") -> tuple[dict, dict]:
    """本地结论与在线结论的裁决。返回 (最终 verdict, 裁决说明)。"""
    info = {
        "applied": False, "action": "local_only", "remote_level": None,
        "remote_confidence": None, "local_level": verdict.get("level"), "reason": "", "note": "",
    }
    if not remote:
        info["reason"] = "在线核查未参与（未配置或调用失败），结论由本地引擎独立给出"
        return verdict, info
    r_level = remote.get("level", "uncertain")
    r_conf = int(remote.get("confidence", 70))
    info.update({"applied": True, "remote_level": r_level, "remote_confidence": r_conf})
    l_level = verdict.get("level", "uncertain")
    authoritative = bool(search_result.get("knowledge") or search_result.get("local_fact"))
    gap = abs(_LEVEL_ORDER.get(l_level, 1) - _LEVEL_ORDER.get(r_level, 1))

    def _adopt_remote(reason: str, ratio: float = 0.92, floor: int = 46, cap: int = 92) -> dict:
        meta = dict(VERDICT_META.get(r_level, VERDICT_META["uncertain"]))
        conf = int(max(floor, min(cap, round(r_conf * ratio))))
        summary = remote.get("conclusion") or remote.get("accurate") or remote.get("title") or verdict.get("summary", "")
        return {
            **meta,
            "confidence": conf,
            "summary": str(summary)[:220],
            "reason": reason,
            "caveat": remote.get("limitation", ""),
        }

    local_conf = int(verdict.get("confidence", 45))
    # 只统计真正进入 support / refute 的本地来源，避免无关检索结果虚高本地权威性
    local_cred = _evidence_credibility(check_result, search_result)
    local_top = max(local_cred) if local_cred else 0
    local_items = len(local_cred)
    remote_top = max([ev.get("credibility_score", 60) for ev in remote.get("evidences", [])] or [60])

    if authoritative:
        # 本地权威层（通识共识 / 已核实事实库）优先，在线只做佐证或提示分歧
        if gap <= 1:
            verdict = dict(verdict)
            verdict["confidence"] = int(min(97, verdict.get("confidence", 80) + 4))
            verdict["reason"] = (verdict.get("reason", "") + f"；在线核查结论为「{_label(r_level)}」，与本地一致")
            info.update({"action": "confirm", "reason": "本地权威层命中，在线结论一致，置信度上调"})
        else:
            verdict = dict(verdict)
            verdict["confidence"] = int(max(52, verdict.get("confidence", 80) - 8))
            info.update({
                "action": "local_priority_conflict",
                "reason": f"本地权威层结论「{_label(l_level)}」与在线「{_label(r_level)}」不一致，仍以本地为准但下调置信度",
                "note": f"在线核查依据：{remote.get('conclusion') or remote.get('title', '')}",
            })
            if remote.get("limitation"):
                info["note"] += f"；在线侧局限说明：{remote['limitation']}"
        return verdict, info

    # 本地落为存疑意味着本地没给出结论，此时在线只要有明确结论就采纳
    if l_level == "uncertain":
        if r_level == "uncertain":
            info.update({
                "action": "both_uncertain",
                "reason": "本地与在线均判为存疑，维持存疑结论",
                "note": remote.get("conclusion") or "",
            })
            return verdict, info
        verdict = _adopt_remote(
            f"本地未取得有效证据支持结论，采纳在线核查结论「{_label(r_level)}」（{r_conf}%），并保留其局限说明"
        )
        info.update({"action": "adopt_remote", "reason": "本地落为存疑而在线给出明确结论，采纳在线结论"})
        return verdict, info

    # 相邻档位：方向一致但严谨度不同，取更保守的一侧
    if gap <= 1:
        if l_level == r_level:
            verdict = dict(verdict)
            verdict["confidence"] = int(min(96, local_conf + 5))
            verdict["reason"] = (verdict.get("reason", "") + f"；在线核查结论同为「{_label(r_level)}」（{r_conf}%）")
            info.update({"action": "agree", "reason": "本地与在线结论一致，互为印证"})
            return verdict, info
        conservative = l_level if _LEVEL_ORDER.get(l_level, 1) < _LEVEL_ORDER.get(r_level, 1) else r_level
        meta = dict(VERDICT_META.get(conservative, VERDICT_META["uncertain"]))
        conf = int(max(52, min(90, round((local_conf + r_conf) / 2 * 0.96))))
        summary = remote.get("conclusion") or remote.get("accurate") or verdict.get("summary", "")
        verdict = {
            **meta,
            "confidence": conf,
            "summary": str(summary)[:220] if conservative == r_level else str(verdict.get("summary", ""))[:220],
            "reason": f"本地判为「{_label(l_level)}」（{local_conf}%），在线判为「{_label(r_level)}」（{r_conf}%），"
                      f"方向一致但严谨度不同，取更保守的「{_label(conservative)}」",
            "caveat": remote.get("limitation", ""),
        }
        info.update({
            "action": "merge_conservative",
            "reason": f"两侧相差 {gap} 档且方向一致，取更保守的「{_label(conservative)}」",
        })
        return verdict, info

    # 差距 ≥ 2 档：冲突处理，先看本地证据是否真的撑得住结论
    if local_items < 2 or local_top < 70:
        verdict = _adopt_remote(
            f"本地有效依据不足（{local_items} 条，最高可信度 {local_top or '—'}），"
            f"采纳在线核查结论「{_label(r_level)}」（{r_conf}%）",
            ratio=0.86, floor=44, cap=86,
        )
        info.update({"action": "adopt_remote_weak_local", "reason": "本地证据不足以支撑结论，改采在线结论"})
        return verdict, info
    if remote_top >= local_top:
        verdict = _adopt_remote(
            f"两侧结论冲突（本地「{_label(l_level)}」/ 在线「{_label(r_level)}」），"
            f"在线来源可信度更高（{remote_top} vs {local_top}），采纳在线结论并下调置信度",
            ratio=0.82, floor=42, cap=84,
        )
        info.update({"action": "conflict_remote_wins", "reason": "来源可信度对比后采纳在线结论"})
    else:
        meta = dict(VERDICT_META.get(l_level, VERDICT_META["uncertain"]))
        verdict = {
            **meta,
            "confidence": int(max(45, round(local_conf * 0.85))),
            "summary": f"本地与在线核查结论冲突：本地判为「{_label(l_level)}」，在线判为「{_label(r_level)}」，已按本地来源可信度更高（{local_top} vs {remote_top}）处理。",
            "reason": f"两侧结论相差 {gap} 档，本地来源可信度更高，保留本地结论并下调置信度",
            "caveat": remote.get("limitation", ""),
        }
        info.update({"action": "conflict_local_wins", "reason": "来源可信度对比后保留本地结论"})
    if remote.get("limitation"):
        info["note"] = f"在线侧局限说明：{remote['limitation']}"
    return verdict, info


def build_remote_view(remote: dict | None, ev_map: dict, sources: list[dict]) -> dict | None:
    """组装给前端渲染的「在线核查」区块。"""
    if not remote:
        return None
    def _src(eid: str) -> dict:
        sid = ev_map.get(eid, "")
        try:
            return sources[int(sid[1:]) - 1] if sid else {}
        except (ValueError, IndexError):
            return {}
    sid_map = _remote_sid_map(remote, ev_map, sources)
    claims = []
    for c in remote.get("claims", []):
        s = _src(c.get("source_id", ""))
        claims.append({
            "id": c.get("id", ""),
            "text": c.get("text", ""),
            "level": c.get("level", "uncertain"),
            "label": c.get("label") or _label(c.get("level", "uncertain")),
            "note": _rewrite_ids(c.get("note", ""), sid_map),
            "source_title": s.get("title", ""),
            "source_url": s.get("url", ""),
            "source_domain": s.get("domain", ""),
        })
    evidences = []
    for ev in remote.get("evidences", [])[:8]:
        sid = ev_map.get(ev["id"], "")
        evidences.append({
            "id": ev["id"],
            "source_id": sid,
            "title": ev.get("title", ""),
            "site": ev.get("site", ""),
            "url": ev.get("url", ""),
            "domain": ev.get("domain", ""),
            "type": ev.get("type", ""),
            "quote": ev.get("quote", ""),
            "date": ev.get("published_at", "—"),
            "query": ev.get("query", ""),
            "locator": ev.get("locator", ""),
            "score": ev.get("score", 0),
            "exact": bool(ev.get("exact")),
            "credibility": ev.get("credibility", "C"),
            "in_card": bool(sid),
        })
    return {
        "provider": remote.get("provider", "在线查证引擎"),
        "level": remote.get("level", "uncertain"),
        "label": _label(remote.get("level", "uncertain")),
        "confidence": remote.get("confidence", 0),
        "truth_score": remote.get("truth_score"),
        "title": remote.get("title", ""),
        "conclusion": _rewrite_ids(remote.get("conclusion", ""), sid_map),
        "accurate": _rewrite_ids(remote.get("accurate", ""), sid_map),
        "limitation": remote.get("limitation", ""),
        "reasoning": _rewrite_ids(remote.get("reasoning", ""), sid_map),
        "share": _rewrite_ids(remote.get("share", ""), sid_map),
        "src_count": remote.get("src_count", len(evidences)),
        "elapsed_ms": remote.get("elapsed_ms", 0),
        "pipeline": remote.get("pipeline", {}),
        "claims": claims,
        "evidences": evidences,
    }
