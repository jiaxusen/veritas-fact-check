"""在线查证桥接模块：调用远端查证台（博查检索 + 深度判定模型），输出归一化结果。

设计要点：
1. 全部用标准库 / requests 兼容写法，远端不可用时静默返回 None，由上层降级到本地引擎。
2. 远端偶发返回空响应或 5xx（观测到 554），因此需要重试 + 退避。
3. 结果做短时缓存，同一段文本重复查证不重复消耗远端额度。
4. 远端 evidences 带 score / exact / rank / locator，是本地匮乏的"证据打分与定位"能力，
   归一化后可直接作为本地 source 使用。
"""
from __future__ import annotations
import json
import os
import time
import threading
import hashlib
from pathlib import Path
from urllib.parse import urlencode, urlparse

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "data" / "remote.json"

DEFAULT_CONFIG = {
    "enabled": True,
    "base_url": "https://chazheng-ai.app.workbuddy.host",
    "sharecode": "YEQ2COGZKU",
    "pass": "VERITAS-2026",
    "endpoint": "/api/verify",
    "timeout": 45,
    "retries": 2,
    "backoff": 1.2,
    "cache_ttl": 900,
    "max_text_len": 600,
    "min_score": 25,
}

# 远端 verdict 取值可能是英文档位或中文标签，统一映射到本地五档
_LEVEL_MAP = {
    "true": "true", "real": "true", "verified": "true", "correct": "true",
    "mostly_true": "mostly_true", "mostly-true": "mostly_true", "largely_true": "mostly_true",
    "partly_true": "partly_true", "partial": "partly_true", "mixed": "partly_true",
    "half_true": "partly_true", "misleading": "partly_true",
    "uncertain": "uncertain", "unverified": "uncertain", "unknown": "uncertain",
    "no_evidence": "uncertain", "inconclusive": "uncertain",
    "false": "false", "fake": "false", "wrong": "false", "debunked": "false",
    "pseudo": "false",
    "属实": "true", "真实": "true", "基本属实": "mostly_true", "大体属实": "mostly_true",
    "部分属实": "partly_true", "部分真实": "partly_true", "有失偏颇": "partly_true",
    "片面": "partly_true", "存疑": "uncertain", "无法证实": "uncertain", "证据不足": "uncertain",
    "不实": "false", "虚假": "false", "谣言": "false", "伪科学": "false", "有误": "partly_true",
}

# 远端证据类型 → 本地可信度档位与分值（顺序敏感：命中在前）
_TYPE_CRED = (
    ("官方", "A", 96),
    ("政府", "A", 96),
    ("部委", "A", 95),
    ("权威", "A", 93),
    ("学术", "A", 92),
    ("期刊", "A", 92),
    ("论文", "A", 90),
    ("媒体", "B", 84),
    ("报刊", "B", 84),
    ("新闻", "B", 84),
    ("电视台", "B", 85),
    ("科普", "B", 80),
    ("百科", "B", 80),
    ("机构", "B", 78),
    ("企业", "C", 66),
    ("自媒体", "C", 58),
    ("社交", "D", 40),
    ("论坛", "D", 40),
    ("贴吧", "D", 35),
)
# 域名级权威判定优先级高于"普通网页"类型标注：gov.cn、辟谣平台、高校院所、主流媒体站点
# 注意：这里只放"权威加成"规则，普通域名不拦截，交回来源类型判定，避免误杀
_DOMAIN_CRED = (
    ((".gov.cn", ".gov.", "gov.cn"), "A", 96),
    (("piyao.org.cn", "piyao.", "factcheck", "fact-check"), "A", 94),
    ((".edu.cn", ".ac.cn", ".edu.", "cas.cn"), "A", 92),
    (("kepuchina.cn", "kepu.", "chinadaily.com.cn", "stdaily.com"), "A", 88),
    (("people.com.cn", "xinhuanet.com", "news.cn", "cctv.com", "cnr.cn",
      "chinanews.com.cn", "gmw.cn", "huanqiu.com", "thepaper.cn", "cctv.cn"), "A", 90),
)
_DEFAULT_CRED = ("C", 65)


def _cred_of(etype: str, url: str = "") -> tuple[str, int]:
    host = _domain(url)
    text = str(etype or "")
    # 官方 / 权威类标注本身就是强信号，优先于域名判断
    for kw, grade, score in _TYPE_CRED[:6]:
        if kw in text:
            return grade, score
    for suffixes, grade, score in _DOMAIN_CRED:
        if any(host.endswith(s) if s.startswith(".") else s in host for s in suffixes):
            return grade, score
    for kw, grade, score in _TYPE_CRED:
        if kw in text:
            return grade, score
    return _DEFAULT_CRED

_LOCK = threading.Lock()
_CACHE: dict[str, tuple[float, dict | None]] = {}
_STATE = {"ok_at": 0.0, "error": "", "calls": 0, "hits": 0}


def load_config() -> dict:
    """读取远端配置：配置文件优先，环境变量可覆盖关键项。"""
    cfg = dict(DEFAULT_CONFIG)
    try:
        if CONFIG_PATH.exists():
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                cfg.update({k: v for k, v in raw.items() if v is not None})
    except Exception:
        pass
    env_map = {
        "VERITAS_REMOTE_URL": "base_url",
        "CHAZHENG_BASE_URL": "base_url",
        "CHAZHENG_SHARECODE": "sharecode",
        "CHAZHENG_PASS": "pass",
    }
    for env_key, cfg_key in env_map.items():
        val = os.environ.get(env_key)
        if val:
            cfg[cfg_key] = val.strip()
    if os.environ.get("VERITAS_REMOTE_OFF"):
        cfg["enabled"] = False
    cfg["base_url"] = str(cfg.get("base_url", "")).rstrip("/")
    return cfg


def status() -> dict:
    """供健康检查使用：是否可用、最近成功时间、最近错误。"""
    cfg = load_config()
    configured = bool(cfg["base_url"]) and bool(cfg["sharecode"])
    return {
        "configured": configured,
        "enabled": bool(cfg["enabled"]) and configured,
        "provider": cfg["base_url"],
        "reachable": _STATE["ok_at"] > 0,
        "last_ok_at": _STATE["ok_at"] or None,
        "last_error": _STATE["error"] or None,
        "calls": _STATE["calls"],
        "cache_entries": len(_CACHE),
    }


def is_enabled() -> bool:
    return bool(status()["enabled"])


def _cache_key(text: str) -> str:
    return hashlib.sha1(text.strip().encode("utf-8")).hexdigest()


def _cache_get(text: str, ttl: float):
    if ttl <= 0:
        return None
    key = _cache_key(text)
    with _LOCK:
        item = _CACHE.get(key)
    if not item:
        return None
    ts, value = item
    if time.time() - ts > ttl:
        with _LOCK:
            _CACHE.pop(key, None)
        return None
    _STATE["hits"] += 1
    return value


def _cache_put(text: str, value) -> None:
    with _LOCK:
        _CACHE[_cache_key(text)] = (time.time(), value)
        # 缓存上限保护
        if len(_CACHE) > 200:
            oldest = sorted(_CACHE.items(), key=lambda kv: kv[1][0])[:60]
            for k, _ in oldest:
                _CACHE.pop(k, None)


def _post(url: str, payload: dict, timeout: float) -> tuple[int, str]:
    """发送 POST。requests 可用则用它，否则退化为标准库实现。

    显式绕开系统代理：本机常驻 CLI 代理（如 127.0.0.1:5xxxx）会把出网请求
    拦到代理上，导致服务进程内调用在线查证台失败，而命令行直连却正常。
    """
    try:
        import requests  # type: ignore
    except Exception:
        requests = None
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if requests is not None:
        try:
            session = requests.Session()
            session.trust_env = False           # 不读 http_proxy/https_proxy
            session.proxies = {"http": "", "https": ""}
            try:
                resp = session.post(url, json=payload, headers=headers, timeout=timeout)
                return resp.status_code, resp.text or ""
            finally:
                session.close()
        except Exception:
            # requests 侧异常时继续尝试标准库实现，而不是直接抛出
            pass
    import urllib.request
    import urllib.error
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST"
    )
    try:
        with opener.open(req, timeout=timeout) as fh:
            return fh.status, fh.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:  # 4xx / 5xx 仍可能携带正文
        try:
            body = exc.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        return exc.code, body
    except Exception as exc:
        raise OSError(str(exc)) from exc


def _norm_level(raw) -> str:
    key = str(raw or "").strip().lower()
    if key in _LEVEL_MAP:
        return _LEVEL_MAP[key]
    return _LEVEL_MAP.get(str(raw or "").strip(), "uncertain")


def _domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def _norm_evidences(raw_list: list, min_score: float) -> list[dict]:
    out: list[dict] = []
    for i, item in enumerate(raw_list or [], start=1):
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        score = item.get("score")
        try:
            score = float(score)
        except (TypeError, ValueError):
            score = 60.0
        if score < min_score:
            continue
        etype = str(item.get("type") or "网络来源")
        grade, base_score = _cred_of(etype, url)
        exact = bool(item.get("exact"))
        quote = str(item.get("quote") or "").strip()
        # 原文原样命中是最高等级的引文形态，额外加分；评分同时折算成相关性
        cred_score = int(min(98, base_score + (4 if exact else 0)))
        relevance = round(min(1.0, score / 100 * 0.9 + (0.12 if exact else 0)), 3)
        out.append({
            "id": f"R{i}",
            "title": str(item.get("title") or item.get("name") or "未命名来源").strip(),
            "site": str(item.get("site") or item.get("name") or "").strip(),
            # 保留在线侧原始来源名，用于把在线编号翻译成卡片编号
            "name": str(item.get("name") or item.get("site") or "").strip(),
            "url": url,
            "domain": _domain(url),
            "published_at": str(item.get("published") or item.get("date") or "—"),
            "type": etype,
            "org_type": etype,
            "quote": quote,
            "snippet": quote,
            "query": str(item.get("query") or ""),
            "locator": str(item.get("locator") or ""),
            "score": score,
            "exact": exact,
            "rank": item.get("rank"),
            "credibility": grade,
            "credibility_score": cred_score,
            "relevance": relevance,
        })
    out.sort(key=lambda x: (x["exact"], x["score"], x["credibility_score"]), reverse=True)
    return out


def _tokens(text: str) -> set[str]:
    return {text[i:i + 2] for i in range(len(text) - 1)} or {text}


def _pick_source_id(note: str, evidences: list[dict]) -> str:
    """按 2-gram 重合度为 claim 的说明挑选最贴切的一条证据。"""
    if not evidences:
        return ""
    nt = _tokens(str(note or ""))
    best, best_score = evidences[0]["id"], 0.0
    for ev in evidences:
        pool = str(ev.get("quote") or "") + str(ev.get("title") or "")
        pt = _tokens(pool)
        if not nt or not pt:
            continue
        ov = len(nt & pt) / max(1, len(nt))
        if ov > best_score:
            best, best_score = ev["id"], ov
    return best


# 在线侧 claim.verdict 是自由中文标签（如"夸大""偷换概念""缺乏依据"），按语义落到五档。
# 顺序敏感：先判明确否定，再判"部分"，最后才是肯定，避免"部分属实"被误判为属实。
_LABEL_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("不实", "虚假", "谣言", "伪科学", "不存在", "不成立", "已辟谣", "错误", "虚构", "并非属实"), "false"),
    (("部分", "夸大", "偷换", "断章取义", "片面", "误导", "不准确", "过时", "以偏概全",
      "混淆", "不严谨", "笼统", "过于绝对", "缺少限定"), "partly_true"),
    (("缺乏依据", "无依据", "缺乏证据", "无法证实", "无法核实", "无法判断", "证据不足",
      "存疑", "不确定", "待核实", "尚未证实"), "uncertain"),
    (("属实", "真实", "成立", "正确", "无误", "有据"), "true"),
    (("基本", "大体", "原则", "总体"), "mostly_true"),
)


def _parse_label(raw: str) -> str | None:
    """把自由中文结论标签解析为本地档位，无法识别时返回 None。"""
    text = str(raw or "").strip()
    if not text:
        return None
    if text.lower() in _LEVEL_MAP:
        return _LEVEL_MAP[text.lower()]
    if text in _LEVEL_MAP:
        return _LEVEL_MAP[text]
    for keywords, level in _LABEL_RULES:
        if any(k in text for k in keywords):
            return level
    return None


def _norm_claims(raw_list: list, evidences: list[dict], fallback_level: str = "uncertain") -> list[dict]:
    out: list[dict] = []
    for i, item in enumerate(raw_list or [], start=1):
        if not isinstance(item, dict):
            continue
        note = str(item.get("note") or "").strip()
        raw_verdict = str(item.get("verdict") or "").strip()
        # 标签无法识别时退回整体结论，而不是一律记为存疑
        level = _parse_label(raw_verdict) or _norm_level(item.get("verdict")) or fallback_level
        out.append({
            "id": f"C{i}",
            "text": str(item.get("text") or "").strip(),
            "level": level,
            "label": raw_verdict or level,
            "note": note,
            "source_id": _pick_source_id(note, evidences),
        })
    return out


def _norm(result: dict, elapsed_ms: int, cfg: dict) -> dict | None:
    if not isinstance(result, dict):
        return None
    evidences = _norm_evidences(result.get("evidences") or [], float(cfg.get("min_score", 25)))
    if not evidences:
        single = result.get("evidence")
        if isinstance(single, dict):
            evidences = _norm_evidences([single], 0)
    level = _norm_level(result.get("verdict"))
    claims = _norm_claims(result.get("claims") or [], evidences, level)
    conf = result.get("confidence")
    try:
        conf = float(conf)
    except (TypeError, ValueError):
        conf = 0.6
    confidence = int(round(conf * 100)) if conf <= 1 else int(round(conf))
    confidence = max(10, min(99, confidence))
    pipe = result.get("pipeline") if isinstance(result.get("pipeline"), dict) else {}
    return {
        "ok": True,
        "provider": urlparse(cfg["base_url"]).netloc or cfg["base_url"],
        "level": level,
        "confidence": confidence,
        "truth_score": result.get("truthScore"),
        "question": bool(result.get("question")),
        "title": str(result.get("title") or "").strip(),
        "conclusion": str(result.get("conclusion") or "").strip(),
        "accurate": str(result.get("accurate") or "").strip(),
        "limitation": str(result.get("limitation") or "").strip(),
        "reasoning": str(result.get("reasoning") or "").strip(),
        "share": str(result.get("share") or "").strip(),
        "src_count": result.get("srcCount") or len(evidences),
        "claims": claims,
        "evidences": evidences,
        "trace": result.get("trace") if isinstance(result.get("trace"), list) else [],
        "pipeline": {
            "claims": pipe.get("claims"),
            "queries": pipe.get("queries"),
            "sources": pipe.get("sources"),
            "pages": pipe.get("pages"),
            "verified": pipe.get("verified"),
            "search_failed": pipe.get("searchFailed"),
            "ms": pipe.get("ms"),
        },
        "elapsed_ms": elapsed_ms,
    }


def verify_remote(text: str, timeout: float | None = None, use_cache: bool = True) -> dict | None:
    """调用远端查证台。失败返回 None，调用方自行降级。"""
    cfg = load_config()
    if not cfg["enabled"] or not cfg["base_url"] or not cfg["sharecode"]:
        return None
    clean = (text or "").strip()
    if not clean:
        return None
    if len(clean) > int(cfg.get("max_text_len", 600)):
        clean = clean[: int(cfg["max_text_len"])]
    if use_cache:
        cached = _cache_get(clean, float(cfg.get("cache_ttl", 900)))
        if cached is not None:
            return cached if cached.get("ok") else None

    query = urlencode({"sharecode": cfg["sharecode"], "pass": cfg.get("pass") or ""})
    url = f"{cfg['base_url']}{cfg.get('endpoint') or '/api/verify'}?{query}"
    attempts = max(1, int(cfg.get("retries", 2)) + 1)
    timeout = float(timeout or cfg.get("timeout", 45))
    result: dict | None = None
    started = time.perf_counter()
    last_err = ""
    for i in range(attempts):
        _STATE["calls"] += 1
        try:
            code, body = _post(url, {"text": clean}, timeout)
        except Exception as exc:
            last_err = f"{type(exc).__name__}: {exc}"
            time.sleep(float(cfg.get("backoff", 1.2)) * (i + 1))
            continue
        if code >= 500 or not body.strip():
            # 远端冷启动或额度抖动：空正文与 5xx 都可重试
            last_err = f"HTTP {code} 空响应" if not body.strip() else f"HTTP {code}"
            time.sleep(float(cfg.get("backoff", 1.2)) * (i + 1))
            continue
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            last_err = "响应非 JSON"
            break
        if not isinstance(data, dict) or not data.get("verdict"):
            last_err = "响应缺少判定字段"
            break
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        result = _norm(data, elapsed_ms, cfg)
        break
    if result is None:
        _STATE["error"] = last_err or "未知错误"
        _cache_put(clean, {"ok": False})
        return None
    _STATE["ok_at"] = time.time()
    _STATE["error"] = ""
    _cache_put(clean, result)
    return result


if __name__ == "__main__":  # 手动自测
    demo = "喝碱性水可以改善体质，预防癌症"
    out = verify_remote(demo)
    print(json.dumps(status(), ensure_ascii=False, indent=2))
    if out:
        print(out["level"], out["confidence"], out["title"])
        for c in out["claims"]:
            print(" -", c["label"], c["text"])
        for e in out["evidences"]:
            print(" *", e["type"], e["score"], e["exact"], e["domain"])
    else:
        print("远端不可用：", status()["last_error"])
