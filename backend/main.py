"""查证工具 · 后端服务（FastAPI）
启动：uvicorn main:app --reload --port 8000
"""
from __future__ import annotations
import base64
import json
import time
from pathlib import Path
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import access_module
import db_module
import llm_engine
import usage_module
import user_module
from concurrent.futures import ThreadPoolExecutor
from modules.card_module import build_card
from modules.grade_module import grade
from modules.input_module import InputError, validate_text
from modules.keyword_module import extract_keywords
from modules.output_module import render_card_html
from modules.refute_module import build_script
from modules.search_module import search
from modules.split_module import aggregate, split_claims
from modules.verify_module import cross_check
from modules import (
    auth_module,
    extract_module,
    fusion_module,
    remote_module,
    screen_module,
)
from pipeline import fuse, remote_collect, remote_submit, run_pipeline
BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR.parent / "frontend"
HISTORY_FILE = BASE_DIR / "data" / "history.json"
app = FastAPI(title="查证工具 API", version="2.0.0")
try:
    db_module.init_db()          # 建表
    user_module.ensure_owner()   # 确保 owner 存在
    db_module.migrate_legacy()   # 再把旧 history.json 迁到 owner 名下
except Exception as _db_exc:
    print(f"[warn] 数据库初始化失败: {_db_exc}")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
def _identity_of(request: Request, key: str) -> tuple[str, bool]:
    """防烧钱身份：公网取口令前缀，本机/局域网为 privileged。"""
    if auth_module.is_private_host(request.url.hostname or ""):
        return "local", True
    return (key[:16] or "anonymous"), False
async def _metered_call(request: Request, call_next, identity: str, privileged: bool):
    """执行请求并记录用量日志（仅 API 写接口）。"""
    started = time.perf_counter()
    resp = await call_next(request)
    if request.method == "POST" and request.url.path.startswith("/api/"):
        usage_module.record(
            identity=identity,
            path=request.url.path,
            status=resp.status_code,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            privileged=privileged,
        )
    return resp


# ---- 公网访问口令 ----
# 定义位置在 CORSMiddleware 之后 → 位于中间件栈最外层，
# 未授权的公网请求在到达任何路由前即被拦截。
@app.middleware("http")
async def access_gate(request: Request, call_next):
    cfg = auth_module.load_config()
    if not cfg.get("enabled"):
        return await call_next(request)

    key = (
        request.query_params.get("key")
        or request.cookies.get(auth_module.COOKIE_NAME)
        or request.headers.get("x-access-key")
        or ""
    )

    if auth_module.check_key(key):
        path = request.url.path
        # 页面请求带 key 参数时：写入 cookie 后重定向，避免口令残留在地址栏
        if (
            request.method == "GET"
            and request.query_params.get("key")
            and not path.startswith("/api/")
        ):
            params = {k: v for k, v in request.query_params.items() if k != "key"}
            resp = RedirectResponse(
                str(request.url.replace_query_params(**params)), status_code=307
            )
        else:
            # 防烧钱三件套：限流 + 配额（仅 API 写接口）
            if request.method == "POST" and request.url.path.startswith("/api/"):
                identity, privileged = _identity_of(request, key)
                blocked = usage_module.guard(identity, privileged)
                if blocked is not None:
                    return JSONResponse(
                        status_code=429,
                        content=blocked,
                        headers={"Retry-After": str(blocked.get("retry_after", 60))},
                    )
                resp = await _metered_call(request, call_next, identity, privileged)
            else:
                resp = await call_next(request)
        resp.set_cookie(
            auth_module.COOKIE_NAME,
            key,
            max_age=auth_module.COOKIE_TTL,
            httponly=True,
            samesite="lax",
        )
        return resp

    # 预检请求交给 CORS 中间件处理
    if request.method == "OPTIONS":
        return await call_next(request)

    # 本机 / 局域网免密
    if cfg.get("public_only", True) and auth_module.is_private_host(
        request.url.hostname or ""
    ):
        if request.method == "POST" and request.url.path.startswith("/api/"):
            identity, privileged = _identity_of(request, key)
            blocked = usage_module.guard(identity, privileged)
            if blocked is not None:
                return JSONResponse(
                    status_code=429,
                    content=blocked,
                    headers={"Retry-After": str(blocked.get("retry_after", 60))},
                )
            return await _metered_call(request, call_next, identity, privileged)
        return await call_next(request)

    if request.url.path.startswith("/api/"):
        return JSONResponse(
            status_code=401, content={"detail": "access_key_required"}
        )
    return HTMLResponse(
        status_code=200,
        content=auth_module.login_page(
            redirect_to=request.url.path,
            error="1" if request.query_params.get("key") else "",
        ),
    )


class VerifyRequest(BaseModel):
    text: str = Field(..., description="待核实文本")
    mode: str = Field("balanced", description="核查模式：balanced 均衡 / strict 严谨 / loose 宽松")
    engine: str = Field("auto", description="引擎：auto 自动（在线融合，失败降级）/ local 本地 / fusion 融合 / remote 在线优先")
    scene: str = Field("rigorous", description="场景：daily 日常速查 / rigorous 严谨求证 / study 学习求证")


def _safe_mode(mode: str) -> str:
    return mode if mode in ("balanced", "strict", "loose") else "balanced"


def _safe_engine(engine: str) -> str:
    """引擎白名单；非法值回落 auto。"""
    value = str(engine or "auto").lower()
    return value if value in ("auto", "local", "fusion", "remote") else "auto"


def _safe_scene(scene: str) -> str:
    """场景白名单：daily 日常速查 / rigorous 严谨求证 / study 学习求证。"""
    value = str(scene or "rigorous").lower()
    return value if value in ("daily", "rigorous", "study", "academic") else "rigorous"


def _run(text: str, engine: str, mode: str, scene: str = "rigorous") -> dict:
    """调用主流程。pipeline 版本尚未支持 scene 时自动降级调用。"""
    try:
        return run_pipeline(text, engine=engine, mode=mode, scene=scene)
    except TypeError:
        return run_pipeline(text, engine=engine, mode=mode)
class BatchRequest(BaseModel):
    texts: list[str] = Field(..., description="待核实文本列表")
class OcrRequest(BaseModel):
    name: str = Field("clipboard.png", description="文件名，用于判定类型")
    data: str = Field(..., description="图片 base64，可带 data:image/...;base64, 前缀")
class AccessCodeRequest(BaseModel):
    code: str = Field(..., description="访问密令")
def _current_user(request: Request | None) -> dict | None:
    """从请求中解析登录用户（Bearer / X-User-Token / Cookie）。"""
    if request is None:
        return None
    auth = request.headers.get("authorization") or ""
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    token = token or (request.headers.get("x-user-token") or "")
    if not token:
        token = request.cookies.get("user_token") or ""
    return user_module.user_by_token(token)
def _owner_id() -> int | None:
    """owner 账号 id（未登录请求的记录归属）。"""
    try:
        with db_module.connect() as conn:
            row = conn.execute("SELECT id FROM users WHERE username = ?", ("owner",)).fetchone()
            return row["id"] if row else None
    except Exception:
        return None
def _append_history(card: dict, request: Request | None = None) -> None:
    """写入查证记录：登录用户归属自己，未登录归 owner。"""
    user = _current_user(request)
    user_id = user["id"] if user else _owner_id()
    if not user_id:
        return
    try:
        with db_module.connect() as conn:
            conn.execute(
                "INSERT INTO records (user_id, card_id, input_text, label, level, confidence, created_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (
                    user_id,
                    card["card_id"],
                    str(card["input_text"])[:200],
                    card["verdict"]["label"],
                    card["verdict"]["level"],
                    float(card["verdict"]["confidence"] or 0),
                    card.get("created_at_display") or time.strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
    except Exception:
        pass
@app.get("/api/health")
def health():
    remote = remote_module.status()
    features = ["web_search", "knowledge_base", "local_facts", "5_level_verdict", "segment_verify"]
    if remote["enabled"]:
        features.append("remote_fusion")
    return {
        "status": "ok",
        "engine": "llm" if llm_engine.is_llm_available() else "local",
        "version": "2.1.0",
        "remote": remote,
        "features": features,
    }


@app.get("/api/remote/status")
def remote_status():
    """在线查证台连通性与调用统计。"""
    cfg = remote_module.load_config()
    st = remote_module.status()
    return {**st, "timeout": cfg.get("timeout"), "cache_ttl": cfg.get("cache_ttl")}


@app.post("/api/remote/probe")
def remote_probe(req: VerifyRequest):
    """手动探测一次在线查证（用于确认远端是否可用，结果不入历史）。"""
    result = remote_module.verify_remote(req.text)
    if not result:
        return {"ok": False, "error": remote_module.status().get("last_error") or "在线查证失败"}
    return {"ok": True, "result": fusion_module.build_remote_view(result, {}, [])}


@app.post("/api/input/extract")
def input_extract(file: UploadFile = File(...)):
    """① 输入模块 · 附件提取。

    图片 → Windows 系统 OCR；TXT / MD / CSV / PDF / DOCX / XLSX → 本地解析。
    返回的 text 直接回填给输入框，之后仍走正常的长度与空值校验。

    注意：这里必须是同步 def——系统 OCR 内部要用 asyncio.run() 起独立事件循环，
    若写成 async def，路由会在 uvicorn 的主循环里执行，asyncio.run() 直接抛错。
    """
    data = file.file.read()
    return extract_module.extract(file.filename or "attachment", data)


@app.post("/api/input/ocr")
def input_ocr(req: OcrRequest):
    """① 输入模块 · 截图 / 剪贴板图片识别（base64 入参）。"""
    raw = (req.data or "").strip()
    if raw.startswith("data:") and "," in raw:
        raw = raw.split(",", 1)[1]
    try:
        blob = base64.b64decode(raw, validate=False)
    except Exception:
        raise HTTPException(status_code=400, detail="图片数据格式错误，无法解析") from None
    if not blob:
        raise HTTPException(status_code=400, detail="图片内容为空")
    return extract_module.ocr_bytes(req.name or "clipboard.png", blob)


@app.get("/api/screen/capture")
def screen_capture(request: Request):
    """① 输入模块 · 屏幕抓取（手动截图）。

    服务端直接截全屏，返回图片给前端，由用户拖拽框选后再送 OCR。
    出于隐私考虑，来自公网的请求一律拒绝——屏幕画面不外传。
    """
    if not auth_module.is_private_host(request.url.hostname or ""):
        raise HTTPException(status_code=403, detail="screen_capture_local_only")
    return screen_module.capture()


@app.post("/api/verify")
def verify(req: VerifyRequest, request: Request):
    try:
        card = _run(
            req.text,
            _safe_engine(req.engine),
            _safe_mode(req.mode),
            _safe_scene(getattr(req, "scene", "rigorous")),
        )
    except InputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _append_history(card, request)
    return card


@app.post("/api/verify/segment")
def verify_segment(req: VerifyRequest, request: Request):
    """长段拆解核验：按句拆成事实点后逐句查证，回答「哪一句不实」。

    只有拆出 2 条及以上事实点时才进入逐句模式，否则退化为整段查证。
    逐句查证会按句调用引擎，默认（auto）走本地流水以保护在线额度；
    显式选择 fusion / remote 时才对每一句启用在线融合。
    """
    mode = _safe_mode(req.mode)
    engine = _safe_engine(req.engine)
    scene = _safe_scene(getattr(req, "scene", "rigorous"))
    seg_engine = engine if engine in ("fusion", "remote") else "local"
    items = split_claims(req.text)
    if len(items) < 2:
        try:
            card = _run(req.text, engine, mode, scene)
        except InputError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        _append_history(card, request)
        return {"segmented": False, "mode": mode, "engine": engine, "segments": [], "aggregate": None, "card": card}
    started = time.perf_counter()
    workers = 3 if seg_engine == "local" else 2
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_run, it["text"], seg_engine, mode) for it in items]
        cards = [f.result() for f in futures]
    segments = []
    for it, card in zip(items, cards):
        v = card["verdict"]
        segments.append({
            "index": it["index"],
            "text": it["text"],
            "start": it["start"],
            "end": it["end"],
            "verdict": {
                "level": v["level"], "label": v["label"], "color": v["color"],
                "confidence": v["confidence"], "summary": v["summary"],
            },
            "source_count": card["evidence_stats"]["source_count"],
            "top_source": (card["sources"][0]["domain"] if card["sources"] else ""),
        })
    agg = aggregate(segments)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return {
        "segmented": True,
        "mode": mode,
        "engine": seg_engine,
        "input_text": req.text,
        "segments": segments,
        "aggregate": agg,
        "elapsed_ms": elapsed_ms,
    }
@app.post("/api/refute/script")
def refute_script(req: VerifyRequest, request: Request):
    """根据查证结果生成可直接转发的辟谣 / 澄清话术。"""
    mode = _safe_mode(req.mode)
    card = _run(req.text, _safe_engine(req.engine), mode)
    _append_history(card, request)
    return {"card": card, **build_script(card, mode)}


@app.post("/api/verify/llm")
def verify_llm(req: VerifyRequest, request: Request):
    """大模型增强查证：LLM 提取关键词 + 联网检索 + LLM 语义核对。
    未配置密钥时自动回退本地引擎。
    """
    mode = _safe_mode(req.mode)
    if not llm_engine.is_llm_available() or usage_module.is_degraded():
        try:
            # 不能硬编码降级为 local，否则勾选大模型时在线融合会被一并丢弃
            card = _run(req.text, _safe_engine(req.engine), mode)
        except InputError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        card["engine_note"] = (
            "今日成本已达熔断线，已自动降级为本地查证引擎"
            if usage_module.is_degraded()
            else "未配置大模型密钥，已自动使用本地查证引擎"
        )
        _append_history(card, request)
        return card
    started = time.perf_counter()
    try:
        validated = validate_text(req.text)
    except InputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # 在线查证与本地大模型流程并行发起（此前该分支未接融合，是查不到在线证据的根因）
    future, cfg, _remote_disabled = remote_submit(validated.text, _safe_engine(req.engine))
    # 关键词：LLM 优先，失败回退规则提取
    keywords = llm_engine.llm_extract_keywords(validated.text) or extract_keywords(validated.text)
    search_result = search(keywords, validated.text)
    check_result = llm_engine.llm_cross_check(validated.text, search_result["sources"]) \
        or cross_check(validated.text, search_result, search_result.get("knowledge"))
    # 通识层优先于 LLM 分级（避免模型"幻觉"推翻考古共识）
    if search_result.get("knowledge"):
        check_result["knowledge"] = search_result["knowledge"]
    try:
        verdict = grade(check_result, search_result, mode=mode)
    except TypeError:
        verdict = grade(check_result, search_result)
    # 并入在线证据并与本地结论仲裁
    remote, remote_error = remote_collect(future, cfg)
    search_result, check_result, verdict, arbitration, ev_map = fuse(
        remote, search_result, check_result, verdict, mode=mode
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    card = build_card(
        text=validated.text,
        keywords=keywords,
        search_result=search_result,
        check_result=check_result,
        verdict=verdict,
        engine="llm",
        elapsed_ms=elapsed_ms,
        remote_view=fusion_module.build_remote_view(remote, ev_map, search_result["sources"]) if remote else None,
        arbitration=arbitration,
    )
    card["remote_used"] = bool(remote)
    card["engine_requested"] = _safe_engine(req.engine)
    if remote_error:
        card["remote_error"] = remote_error
        card["risk_notes"].append(
            f"在线核查未成功参与本次查证（{remote_error}），结论由本地引擎独立给出。"
        )
    card["mode"] = mode
    card["input_warnings"] = validated.warnings
    card["search_trace"] = search_result.get("trace", [])
    card["queries"] = search_result.get("queries", [])
    if search_result.get("knowledge"):
        k = search_result["knowledge"]
        card["knowledge"] = {
            "id": k["id"], "name": k["name"], "consensus": k["consensus"],
            "explain": k["explain"], "caveat": k.get("caveat", ""),
        }
    _append_history(card, request)
    return card
@app.post("/api/verify/batch")
def verify_batch(req: BatchRequest):
    if not req.texts:
        raise HTTPException(status_code=400, detail="请至少提供一条待核实文本")
    if len(req.texts) > 10:
        raise HTTPException(status_code=400, detail="单次批量查证不超过 10 条")
    results = []
    for text in req.texts:
        try:
            card = run_pipeline(text, engine="local")
            results.append({"ok": True, "card": card})
        except InputError as exc:
            results.append({"ok": False, "text": text, "error": str(exc)})
    return {"total": len(results), "results": results}
@app.get("/api/card/{card_id}/html", response_class=HTMLResponse)
def card_html(card_id: str):
    records = []
    try:
        with db_module.connect() as conn:
            rows = conn.execute(
                "SELECT card_id, input_text, label, confidence FROM records WHERE card_id = ? LIMIT 1",
                (card_id,),
            ).fetchall()
            records = [dict(r) for r in rows]
    except Exception:
        records = []
    for rec in records:
        if rec["card_id"] == card_id:
            return HTMLResponse(
                f"<html><body style='background:#070B14;color:#E6F1FF;font-family:sans-serif'>"
                f"<h2>查证卡 {card_id}</h2><p>{rec['input_text']}</p>"
                f"<p>结论：{rec['label']} · 置信度 {rec['confidence']}%</p></body></html>"
            )
    raise HTTPException(status_code=404, detail="查证卡不存在")
@app.post("/api/access/generate")
def access_generate():
    """生成本次访问密令（10 分钟有效）。"""
    code = access_module.generate_code()
    return {"code": code, "ttl_minutes": access_module.CODE_TTL_MINUTES}
@app.post("/api/access/verify")
def access_verify(req: AccessCodeRequest):
    """校验密令，通过则签发访问令牌。"""
    token = access_module.verify_code(req.code)
    if not token:
        raise HTTPException(status_code=403, detail="密令无效或已过期，请联系开发者获取新密令")
    return {"token": token, "expires_in": access_module.TOKEN_TTL_SECONDS}
@app.post("/api/access/owner")
def access_owner():
    """本人免密令直通。"""
    return {"token": access_module.owner_token(), "expires_in": access_module.TOKEN_TTL_SECONDS}
@app.post("/api/access/check")
def access_check(req: AccessCodeRequest):
    """校验访问令牌（code 字段承载令牌）。"""
    return {"valid": access_module.check_token(req.code)}
@app.get("/api/history")
def history(request: Request, limit: int = 50):
    """当前用户的历史查证记录（未登录则返回 owner 的）。"""
    user = _current_user(request)
    user_id = user["id"] if user else _owner_id()
    if not user_id:
        return {"records": []}
    limit = max(1, min(int(limit or 50), 200))
    try:
        with db_module.connect() as conn:
            rows = conn.execute(
                "SELECT card_id, created_at, input_text, label, level, confidence"
                " FROM records WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return {"records": [dict(r) for r in rows]}
    except Exception:
        return {"records": []}
class RegisterRequest(BaseModel):
    username: str = Field(..., description="用户名 3~20 位")
    password: str = Field(..., description="密码 6~64 位")
class LoginRequest(BaseModel):
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")
@app.post("/api/user/register")
def user_register(req: RegisterRequest):
    """注册新用户（默认免费版，每日 100 次额度）。"""
    try:
        info = user_module.register(req.username, req.password)
    except user_module.UserError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    return {"ok": True, "user": info}
@app.post("/api/user/login")
def user_login(req: LoginRequest):
    """登录并签发令牌（7 天有效）。"""
    try:
        result = user_module.login(req.username, req.password)
    except user_module.UserError as exc:
        raise HTTPException(status_code=401, detail=exc.message) from exc
    return {"ok": True, **result}
@app.post("/api/user/logout")
def user_logout(request: Request):
    """登出，令牌立即失效。"""
    auth = request.headers.get("authorization") or ""
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    token = token or (request.headers.get("x-user-token") or "")
    return {"ok": user_module.logout(token)}
@app.get("/api/user/me")
def user_me(request: Request):
    """当前登录用户信息 + 额度余量。"""
    user = _current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="未登录或登录已过期")
    identity, privileged = _identity_of(request, "")
    usage = usage_module.status_for(f"user:{user['id']}", privileged)
    return {"ok": True, "user": user, "usage": usage}
@app.get("/api/usage/status")
def usage_status(request: Request):
    """当前身份的额度余量与限流状态。"""
    key = (
        request.query_params.get("key")
        or request.cookies.get(auth_module.COOKIE_NAME)
        or request.headers.get("x-access-key")
        or ""
    )
    identity, privileged = _identity_of(request, key)
    return usage_module.status_for(identity, privileged)
@app.get("/api/usage/admin")
def usage_admin(request: Request):
    """用量汇总（仅本机/局域网可访问）。"""
    if not auth_module.is_private_host(request.url.hostname or ""):
        raise HTTPException(status_code=403, detail="admin_local_only")
    return usage_module.admin_stats()
@app.post("/api/usage/config")
def usage_config_update(request: Request, update: dict):
    """更新防烧钱配置（仅本机/局域网可访问）。"""
    if not auth_module.is_private_host(request.url.hostname or ""):
        raise HTTPException(status_code=403, detail="admin_local_only")
    return usage_module.save_config(update)
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")