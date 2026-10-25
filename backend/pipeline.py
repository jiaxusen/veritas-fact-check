"""查证主流程编排：输入 → 关键词 → 检索 → 核对 → 分级 → 查证卡。

支持三种引擎：
- local  ：纯本地流水线（通识共识 / 领域层 / 高校层 / 本地事实库 / 联网检索）；
- fusion ：本地流水线 + 在线查证台（并行调用，证据与结论融合后仲裁）；
- auto   ：优先尝试在线融合，在线不可用时自动降级为 local（默认）。
"""
from __future__ import annotations
import time
from concurrent.futures import ThreadPoolExecutor

from modules.card_module import build_card
from modules.fusion_module import arbitrate, attach_remote_claims, build_remote_view, merge_sources
from modules.grade_module import grade
from modules.heuristic_module import analyze_tone, heuristic_verdict
from modules.input_module import InputError, validate_text
from modules.keyword_module import extract_keywords
from modules.remote_module import is_enabled, load_config, status, verify_remote
from modules.search_module import search
from modules.verify_module import cross_check

REMOTE_ENGINES = ("auto", "fusion", "remote")
_REMOTE_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="remote-verify")


def _remote_budget(cfg: dict) -> float:
    """在线调用的等待上限：单次超时 × 重试次数 + 余量。"""
    try:
        return float(cfg.get("timeout", 45)) * (int(cfg.get("retries", 2)) + 1) + 8
    except (TypeError, ValueError):
        return 120.0


def remote_submit(text: str, engine: str = "auto") -> tuple[object | None, dict, str]:
    """在线程池里发起在线查证调用，立即返回 future，便于与本地检索并行。

    返回 (future, config, disabled_reason)。future 为 None 表示本次不启用在线。
    """
    if str(engine).lower() not in REMOTE_ENGINES or not is_enabled():
        return None, {}, "未启用在线融合"
    cfg = load_config()
    return _REMOTE_POOL.submit(verify_remote, text), cfg, ""


def remote_collect(future: object | None, cfg: dict) -> tuple[dict | None, str]:
    """收回在线调用结果，任何异常都降级为「未参与」，不阻断本地流程。"""
    if future is None:
        return None, ""
    try:
        remote = future.result(timeout=_remote_budget(cfg))
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"
    if remote is None:
        return None, status().get("last_error") or "在线查证台未返回可用结果"
    return remote, ""


def fuse(remote: dict | None, search_result: dict, check_result: dict,
         verdict: dict, mode: str = "balanced") -> tuple[dict, dict, dict, dict | None, dict]:
    """把在线结果与本地中间量融合：并入来源、附加在线事实点、仲裁结论。

    返回 (search_result, check_result, verdict, arbitration, ev_map)。
    """
    if not remote:
        return search_result, check_result, verdict, None, {}
    search_result, ev_map = merge_sources(search_result, remote)
    check_result = attach_remote_claims(check_result, remote, ev_map, search_result["sources"])
    verdict, arbitration = arbitrate(verdict, remote, check_result, search_result, mode=mode)
    return search_result, check_result, verdict, arbitration, ev_map


def _backfill_source_meta(sources: list[dict]) -> None:
    """为缺少归属分类/权威依据的来源补齐字段（融合路径重建来源后会缺失）。"""
    for s in sources:
        if not isinstance(s, dict):
            continue
        if s.get("category") and s.get("authority_reason"):
            continue
        if not s.get("category") or not s.get("authority_reason"):
            from modules.web_search_module import classify_domain
            level, score, kind, category = classify_domain(s.get("url", ""))
            if not s.get("credibility"):
                s["credibility"] = level
            if not s.get("credibility_score"):
                s["credibility_score"] = score
            if not s.get("org_type"):
                s["org_type"] = kind
            if not s.get("category"):
                s["category"] = category
        if not s.get("authority_reason"):
            from modules.web_search_module import authority_reason
            s["authority_reason"] = authority_reason(s)


def run_pipeline(
    raw_text: str,
    engine: str = "local",
    mode: str = "balanced",
    scene: str = "rigorous",
    **kwargs,
) -> dict:
    """执行一次完整查证，返回查证卡数据。

    engine: local 本地 / fusion 本地+在线融合 / auto 自动（在线不可用时降级）。
    mode  : balanced 均衡 / strict 严谨 / loose 宽松。
    scene : daily 日常速查 / rigorous 严谨求证 / study 学习求证。
    兼容说明：签名保留 **kwargs，避免上游传入额外参数时报 TypeError。
    """
    started = time.perf_counter()
    want_remote = str(engine).lower() in REMOTE_ENGINES and is_enabled()
    cfg = load_config() if want_remote else {}
    # ① 输入校验
    validated = validate_text(raw_text)
    # ② 关键词提取
    keywords = extract_keywords(validated.text)
    # ③ 在线查证与本地检索并行发起，避免串行等待
    remote_future = None
    if want_remote:
        remote_future = _REMOTE_POOL.submit(verify_remote, validated.text)
    search_result = search(keywords, validated.text, scene=scene)
    # ④ 合并在线结果
    remote = None
    remote_error = ""
    if remote_future is not None:
        try:
            remote = remote_future.result(timeout=_remote_budget(cfg))
        except Exception as exc:  # 在线失败一律降级，不阻断本地流程
            remote = None
            remote_error = f"{type(exc).__name__}: {exc}"
        if remote is None and not remote_error:
            remote_error = status().get("last_error") or "在线查证台未返回可用结果"
    ev_map: dict[str, str] = {}
    if remote:
        search_result, ev_map = merge_sources(search_result, remote)
    # ⑤ 核对（本地来源 + 在线证据 + 在线逐条事实点结论）
    check_result = cross_check(validated.text, search_result, search_result.get("knowledge"))
    if remote:
        check_result = attach_remote_claims(check_result, remote, ev_map, search_result["sources"])
    # ⑥ 语言特征分析（证据不足时的兜底研判）
    tone = analyze_tone(validated.text)
    check_result["tone"] = tone
    # ⑦ 分级（grade 未实现 mode 时自动降级，保证不因签名差异中断）
    try:
        verdict = grade(check_result, search_result, mode=mode)
    except TypeError:
        verdict = grade(check_result, search_result)
    # ⑧ 本地 / 在线结论仲裁
    arbitration = None
    if remote:
        verdict, arbitration = arbitrate(verdict, remote, check_result, search_result, mode=mode)
    # 若判为存疑且语言高风险，追加启发式提示
    if verdict["level"] == "uncertain":
        hint = heuristic_verdict(validated.text, tone)
        if hint:
            verdict["summary"] = hint["summary"]
            verdict["reason"] = hint["reason"] + "；" + verdict.get("reason", "")
            verdict["heuristic"] = True
    # ⑨ 生成查证卡
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    engine_used = "fusion" if remote else ("local" if str(engine).lower() != "llm" else "llm")
    card = build_card(
        text=validated.text,
        keywords=keywords,
        search_result=search_result,
        check_result=check_result,
        verdict=verdict,
        engine=engine_used,
        elapsed_ms=elapsed_ms,
        remote_view=build_remote_view(remote, ev_map, search_result["sources"]) if remote else None,
        arbitration=arbitration,
    )
    card["input_warnings"] = validated.warnings
    card["search_trace"] = search_result.get("trace", [])
    card["queries"] = search_result.get("queries", [])
    card["tone"] = tone
    card["mode"] = mode
    card["scene"] = scene
    # 融合路径会重建来源，这里统一回填可解释字段，保证前端展示不缺项
    _backfill_source_meta(card.get("sources") or [])
    comp: dict[str, int] = {}
    auth = 0
    for s in card.get("sources") or []:
        comp[s.get("category") or "其他"] = comp.get(s.get("category") or "其他", 0) + 1
        if (s.get("credibility") or "C") in ("A", "B"):
            auth += 1
    card["authority_count"] = auth
    card["authority_target"] = search_result.get("authority_target", 6)
    card["composition"] = comp
    card["engine_requested"] = str(engine).lower()
    card["remote_used"] = bool(remote)
    if want_remote and not remote:
        card["remote_error"] = remote_error
        card["risk_notes"].append(
            f"在线核查未成功参与本次查证（{remote_error}），结论由本地引擎独立给出。"
        )
    if search_result.get("knowledge"):
        card["knowledge"] = {
            "id": search_result["knowledge"]["id"],
            "name": search_result["knowledge"]["name"],
            "consensus": search_result["knowledge"]["consensus"],
            "explain": search_result["knowledge"]["explain"],
            "caveat": search_result["knowledge"].get("caveat", ""),
        }
    return card
