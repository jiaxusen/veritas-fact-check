"""②-B 真实联网检索模块：百度百科开放接口 + 必应国内版 + 本地知识库兜底。
设计原则：
1. 多源并行，任一源失败不影响整体（全部失败才降级为本地库）。
2. 结果统一归一化为 source 结构，带来源类型（encyclopedia/search/local）。
3. 相关性 + 可信度双重排序：先剔除与主题无关的"权威噪音"，再按可信度排序。
"""
from __future__ import annotations
import html as html_lib
import re
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
import requests
UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}
# 域名 → (可信度等级, 基础分, 机构类型)
_DOMAIN_RULES: list[tuple[str, str, int, str]] = [
    ("baike.baidu.com", "B", 84, "百科"),
    ("wikipedia.org", "B", 84, "百科"),
    ("gov.cn", "A", 95, "政府机构"),
    ("edu.cn", "A", 92, "高校/科研"),
    ("ac.cn", "A", 92, "科研机构"),
    ("cas.cn", "A", 94, "中科院"),
    ("cass.cn", "A", 93, "社科院"),
    ("xinhuanet.com", "A", 92, "央媒"),
    ("people.com.cn", "A", 92, "央媒"),
    ("cctv.com", "A", 90, "央媒"),
    ("chinanews.com", "A", 88, "央媒"),
    ("gmw.cn", "A", 88, "央媒"),
    ("thepaper.cn", "B", 84, "主流媒体"),
    ("kepu.net.cn", "A", 90, "科普"),
    ("kepuchina.cn", "A", 90, "科普"),
    ("piyao.org.cn", "A", 93, "辟谣平台"),
    ("fact.qq.com", "B", 80, "事实核查"),
    ("jiuzhen.qq.com", "B", 80, "事实核查"),
    ("zhihu.com", "C", 62, "社区"),
    ("toutiao.com", "C", 55, "自媒体"),
    ("sohu.com", "C", 55, "自媒体"),
    ("163.com", "C", 60, "门户"),
    ("sina.com.cn", "C", 60, "门户"),
    ("qq.com", "C", 58, "门户"),
    ("douban.com", "C", 52, "社区"),
    ("baijiahao.baidu.com", "C", 50, "自媒体"),
]
_DEFAULT_RULE = ("C", 55, "一般站点")
# 明显与事实核查无关的噪音域名/标题关键词
_NOISE_HOSTS = ("cnxiangyan.com", "taobao.com", "tmall.com", "jd.com", "1688.com")
_NOISE_TITLE = ("香烟", "价格表", "优惠券", "招聘", "下载", "小说", "直播", "游戏", "彩票")
# 站点首页特征：这类页面几乎不含具体论据，属于"权威噪音"
_HOMEPAGE_PATTERNS = (
    r"^https?://[^/]+/?$",
    r"^https?://[^/]+/index\.(html?|php|aspx?)$",
    r"^https?://[^/]+/(cn|zh)/?$",
)
_STOP_CHARS = set("的了是在和与也都就会有着这那个什么怎么吗呢吧啊我你他它")
def classify_domain(url: str) -> tuple[str, int, str]:
    """按域名给出可信度等级、基础分与机构类型。"""
    host = (urlparse(url).hostname or "").lower()
    for key, level, score, kind in _DOMAIN_RULES:
        if host == key or host.endswith("." + key):
            return level, score, kind
    return _DEFAULT_RULE
def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()
def _is_noise(title: str, url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if any(h in host for h in _NOISE_HOSTS):
        return True
    return any(k in title for k in _NOISE_TITLE)
def _is_homepage(url: str) -> bool:
    """判断是否为站点首页（无具体内容页）。"""
    return any(re.match(p, url) for p in _HOMEPAGE_PATTERNS)
def _bigrams(text: str) -> set[str]:
    """中文二元组，用于轻量相关性计算。"""
    chars = [c for c in text if "\u4e00" <= c <= "\u9fa5" or c.isalnum()]
    return {chars[i] + chars[i + 1] for i in range(len(chars) - 1)}
def relevance_score(source: dict, keywords: list[str], text: str) -> float:
    """计算来源与待核实内容的相关性（0~1）。
    综合：关键词命中、标题命中、摘要与原文的二元组重合度、是否首页。
    """
    title = source.get("title", "")
    snippet = source.get("snippet", "")
    blob = title + " " + snippet
    score = 0.0
    # 1) 关键词命中（权重最高）
    hit_kw = [k for k in keywords if k and k in blob]
    if keywords:
        score += 0.45 * (len(hit_kw) / len(keywords))
    # 2) 标题命中额外加权
    if any(k and k in title for k in keywords):
        score += 0.15
    # 3) 摘要与原文的语义重合
    tb, sb = _bigrams(text), _bigrams(blob)
    if tb and sb:
        score += 0.30 * min(len(tb & sb) / max(len(tb), 1), 1.0)
    # 4) 首页惩罚
    if _is_homepage(source.get("url", "")):
        score *= 0.25
    # 5) 摘要过短惩罚
    if len(snippet) < 40:
        score *= 0.6
    return round(min(score, 1.0), 3)
# ---------------------------------------------------------------- 百度百科
def search_baike(keyword: str) -> list[dict]:
    """百度百科开放接口，返回词条摘要（权威度较高）。"""
    try:
        resp = requests.get(
            "https://baike.baidu.com/api/openapi/BaikeLemmaCardApi",
            params={
                "scope": 103,
                "format": "json",
                "appid": 379020,
                "bk_key": keyword,
                "bk_length": 800,
            },
            headers=UA,
            timeout=8,
        )
        data = resp.json()
    except Exception:
        return []
    abstract = _clean(data.get("abstract") or data.get("desc") or "")
    if len(abstract) < 20:
        return []
    url = data.get("url") or f"https://baike.baidu.com/item/{keyword}"
    if url.startswith("http://"):
        url = "https://" + url[len("http://"):]
    level, score, kind = classify_domain(url)
    return [{
        "title": f"{data.get('key') or keyword} - 百度百科",
        "url": url,
        "domain": urlparse(url).hostname or "baike.baidu.com",
        "published_at": time.strftime("%Y-%m-%d"),
        "credibility": level,
        "credibility_score": score,
        "snippet": abstract[:300],
        "source_type": "encyclopedia",
        "org_type": kind,
        "raw_len": len(abstract),
    }]
# ---------------------------------------------------------------- 必应国内版
def search_bing(query: str, limit: int = 8) -> list[dict]:
    """必应国内版网页检索，解析 b_algo 结果块。"""
    try:
        resp = requests.get(
            "https://cn.bing.com/search",
            params={"q": query, "ensearch": "0"},
            headers=UA,
            timeout=12,
        )
        html = resp.text
    except Exception:
        return []
    out: list[dict] = []
    for block in re.findall(r'<li class="b_algo".*?</li>', html, re.S):
        m = re.search(r'<h2>.*?<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not m:
            continue
        url, title = m.group(1), _clean(m.group(2))
        if not url.startswith("http") or not title:
            continue
        sn = re.search(r"<p[^>]*>(.*?)</p>", block, re.S)
        snippet = _clean(sn.group(1)) if sn else ""
        if len(snippet) < 15 or _is_noise(title, url):
            continue
        level, score, kind = classify_domain(url)
        out.append({
            "title": title[:120],
            "url": url,
            "domain": urlparse(url).hostname or "",
            "published_at": time.strftime("%Y-%m-%d"),
            "credibility": level,
            "credibility_score": score,
            "snippet": snippet[:300],
            "source_type": "search",
            "org_type": kind,
            "raw_len": len(snippet),
        })
        if len(out) >= limit:
            break
    return out
# ---------------------------------------------------------------- 聚合检索
def _dedup(sources: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for s in sources:
        key = s["url"].rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out
def web_search(keywords: list[str], text: str, max_sources: int = 8) -> dict:
    """并发多源检索 + 相关性过滤 + 可信度排序。
    返回结构：
        {"sources": [...], "trace": [...], "ok": bool, "engine": "web|none"}
    """
    queries: list[str] = []
    for kw in keywords[:3]:
        if kw and kw not in queries:
            queries.append(kw)
    if text and len(text) <= 40 and text not in queries:
        queries.append(text)
    if keywords:
        q = f"{keywords[0]} 是什么 依据"
        if q not in queries:
            queries.append(q)
    queries = queries[:5]
    tasks: list[tuple[str, str]] = []
    for kw in keywords[:2]:
        tasks.append(("baike", kw))
    for q in queries:
        tasks.append(("bing", q))
    results: list[dict] = []
    trace: list[dict] = []
    def _run(kind: str, q: str) -> tuple[str, str, list[dict]]:
        if kind == "baike":
            return kind, q, search_baike(q)
        return kind, q, search_bing(q)
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(_run, k, q) for k, q in tasks]
        for fut in futures:
            try:
                kind, q, items = fut.result(timeout=20)
            except Exception:
                continue
            trace.append({"channel": kind, "query": q, "hits": len(items)})
            results.extend(items)
    results = _dedup(results)
    # 相关性打分并过滤低相关结果
    for s in results:
        s["relevance"] = relevance_score(s, keywords, text)
    results = [s for s in results if s["relevance"] >= 0.18]
    # 综合排序：相关性为主，可信度为辅（避免"权威但无关"占位）
    results.sort(
        key=lambda s: (s["relevance"] * 0.65 + (s["credibility_score"] / 100) * 0.35),
        reverse=True,
    )
    results = results[:max_sources]
    return {
        "sources": results,
        "trace": trace,
        "ok": bool(results),
        "engine": "web" if results else "none",
    }