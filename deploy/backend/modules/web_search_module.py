"""②-B 真实联网检索模块：百度百科开放接口 + 必应国内版 + 权威源定向补充。
设计原则：
1. 多源并行，任一源失败不影响整体（全部失败才降级为本地库）。
2. 结果统一归一化为 source 结构，带来源类型（encyclopedia/search/local）。
3. 权威优先：先保证权威源的数量配额，再用相关性排序；权威源不足时
   自动以 site: 官方域名做定向补充检索，避免"只见自媒体不见官方"。
4. 每条来源可解释：给出"凭什么算权威"的判定依据。
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

# 域名 → (可信度等级, 基础分, 机构类型, 归属分类)
# 顺序敏感：精确域名在前，通用后缀（gov.cn / edu.cn）在后兜底。
_DOMAIN_RULES: list[tuple[str, str, int, str, str]] = [
    # ---- 中央政府门户 ----
    ("www.gov.cn", "A", 98, "中国政府网", "政府"),
    # ---- 国务院部委与直属机构 ----
    ("mohrss.gov.cn", "A", 97, "人力资源社会保障部", "政府"),
    ("nhc.gov.cn", "A", 97, "国家卫生健康委", "政府"),
    ("moe.gov.cn", "A", 97, "教育部", "政府"),
    ("nmpa.gov.cn", "A", 97, "国家药监局", "政府"),
    ("samr.gov.cn", "A", 97, "国家市场监管总局", "政府"),
    ("stats.gov.cn", "A", 97, "国家统计局", "政府"),
    ("spp.gov.cn", "A", 96, "最高人民检察院", "政府"),
    ("court.gov.cn", "A", 97, "最高人民法院", "政府"),
    ("mof.gov.cn", "A", 96, "财政部", "政府"),
    ("mps.gov.cn", "A", 96, "公安部", "政府"),
    ("moj.gov.cn", "A", 96, "司法部", "政府"),
    ("ndrc.gov.cn", "A", 96, "国家发改委", "政府"),
    ("miit.gov.cn", "A", 96, "工业和信息化部", "政府"),
    ("mee.gov.cn", "A", 96, "生态环境部", "政府"),
    ("most.gov.cn", "A", 96, "科技部", "政府"),
    ("pbc.gov.cn", "A", 96, "中国人民银行", "政府"),
    ("nfra.gov.cn", "A", 96, "国家金融监管总局", "政府"),
    ("csrc.gov.cn", "A", 96, "证监会", "政府"),
    ("mfa.gov.cn", "A", 96, "外交部", "政府"),
    ("mod.gov.cn", "A", 95, "国防部", "政府"),
    ("moa.gov.cn", "A", 95, "农业农村部", "政府"),
    ("mofcom.gov.cn", "A", 95, "商务部", "政府"),
    ("mohurd.gov.cn", "A", 95, "住房城乡建设部", "政府"),
    ("mot.gov.cn", "A", 95, "交通运输部", "政府"),
    ("mwr.gov.cn", "A", 95, "水利部", "政府"),
    ("mct.gov.cn", "A", 95, "文化和旅游部", "政府"),
    ("mca.gov.cn", "A", 95, "民政部", "政府"),
    ("mem.gov.cn", "A", 95, "应急管理部", "政府"),
    ("nea.gov.cn", "A", 95, "国家能源局", "政府"),
    ("cma.gov.cn", "A", 95, "中国气象局", "政府"),
    ("cea.gov.cn", "A", 95, "中国地震局", "政府"),
    ("caac.gov.cn", "A", 95, "中国民航局", "政府"),
    ("sasac.gov.cn", "A", 95, "国资委", "政府"),
    ("npc.gov.cn", "A", 97, "全国人大", "政府"),
    ("cppcc.gov.cn", "A", 96, "全国政协", "政府"),
    ("nsfc.gov.cn", "A", 93, "国家自然科学基金委", "政府"),
    ("cnca.cn", "A", 92, "国家认证认可委", "政府"),
    ("gov.cn", "A", 93, "政府机构", "政府"),
    # ---- 央媒 ----
    ("news.cn", "A", 93, "新华社", "央媒"),
    ("xinhuanet.com", "A", 93, "新华社", "央媒"),
    ("people.com.cn", "A", 93, "人民日报", "央媒"),
    ("cctv.com", "A", 91, "中央广播电视总台", "央媒"),
    ("gmw.cn", "A", 89, "光明日报", "央媒"),
    ("chinanews.com.cn", "A", 89, "中国新闻社", "央媒"),
    ("chinanews.com", "A", 89, "中国新闻社", "央媒"),
    ("chinadaily.com.cn", "A", 88, "中国日报", "央媒"),
    ("81.cn", "A", 90, "中国军网", "央媒"),
    ("cri.cn", "A", 87, "中国国际广播电台", "央媒"),
    # ---- 科研与高校 ----
    ("cas.cn", "A", 94, "中国科学院", "学术"),
    ("cae.cn", "A", 92, "中国工程院", "学术"),
    ("cass.cn", "A", 93, "中国社会科学院", "学术"),
    ("ac.cn", "A", 91, "科研机构", "学术"),
    ("edu.cn", "A", 90, "高校", "学术"),
    ("cnki.net", "B", 84, "学术数据库", "学术"),
    ("wanfangdata.com.cn", "B", 84, "学术数据库", "学术"),
    ("cqvip.com", "B", 78, "学术数据库", "学术"),
    # ---- 科普与辟谣 ----
    ("piyao.org.cn", "A", 95, "中国互联网联合辟谣平台", "科普"),
    ("chinacdc.cn", "A", 94, "中国疾控中心", "科普"),
    ("kepuchina.cn", "A", 91, "科普中国", "科普"),
    ("kepu.net.cn", "A", 90, "中国科普网", "科普"),
    ("cast.org.cn", "A", 90, "中国科协", "科普"),
    # ---- 国际组织与权威期刊 ----
    ("who.int", "A", 95, "世界卫生组织", "国际"),
    ("un.org", "A", 95, "联合国", "国际"),
    ("unesco.org", "A", 93, "联合国教科文组织", "国际"),
    ("fao.org", "A", 93, "联合国粮农组织", "国际"),
    ("wmo.int", "A", 92, "世界气象组织", "国际"),
    ("ipcc.ch", "A", 94, "IPCC", "国际"),
    ("worldbank.org", "A", 92, "世界银行", "国际"),
    ("imf.org", "A", 92, "国际货币基金组织", "国际"),
    ("nejm.org", "A", 94, "国际医学期刊", "国际"),
    ("thelancet.com", "A", 94, "国际医学期刊", "国际"),
    ("science.org", "A", 93, "国际学术期刊", "国际"),
    ("nature.com", "A", 92, "国际学术期刊", "国际"),
    ("ncbi.nlm.nih.gov", "A", 93, "医学文献库", "国际"),
    ("iso.org", "A", 92, "国际标准化组织", "国际"),
    # ---- 主流媒体 ----
    ("thepaper.cn", "B", 84, "主流媒体", "媒体"),
    ("caixin.com", "B", 85, "财经媒体", "媒体"),
    ("yicai.com", "B", 82, "财经媒体", "媒体"),
    ("jiemian.com", "B", 78, "主流媒体", "媒体"),
    ("huanqiu.com", "B", 82, "主流媒体", "媒体"),
    # ---- 事实核查与百科 ----
    ("fact.qq.com", "B", 82, "事实核查", "核查"),
    ("jiuzhen.qq.com", "B", 82, "事实核查", "核查"),
    ("britannica.com", "B", 82, "百科", "百科"),
    ("baike.baidu.com", "B", 80, "百科", "百科"),
    ("wikipedia.org", "B", 80, "百科", "百科"),
    # ---- 门户 / 社区 / 自媒体 ----
    ("zhihu.com", "C", 62, "社区", "其他"),
    ("163.com", "C", 58, "门户", "其他"),
    ("sina.com.cn", "C", 58, "门户", "其他"),
    ("qq.com", "C", 56, "门户", "其他"),
    ("toutiao.com", "C", 52, "自媒体", "其他"),
    ("sohu.com", "C", 52, "自媒体", "其他"),
    ("bilibili.com", "C", 52, "视频社区", "其他"),
    ("douban.com", "C", 50, "社区", "其他"),
    ("weibo.com", "C", 50, "社交媒体", "其他"),
    ("mp.weixin.qq.com", "C", 50, "自媒体", "其他"),
    ("baijiahao.baidu.com", "C", 48, "自媒体", "其他"),
    ("zhidao.baidu.com", "C", 48, "问答社区", "其他"),
    ("tieba.baidu.com", "C", 46, "社区", "其他"),
]

_DEFAULT_RULE = ("C", 55, "一般站点", "其他")

# 定向补充检索优先探测的权威域名（按场景重排顺序）
_AUTHORITY_PROBE: list[str] = [
    "gov.cn", "mohrss.gov.cn", "nhc.gov.cn", "moe.gov.cn",
    "samr.gov.cn", "ndrc.gov.cn", "stats.gov.cn",
    "xinhuanet.com", "people.com.cn", "piyao.org.cn", "kepuchina.cn",
    "edu.cn", "ac.cn", "court.gov.cn",
]
# 学术场景优先探测
_ACADEMIC_PROBE: list[str] = [
    "edu.cn", "ac.cn", "cas.cn", "cnki.net",
    "ncbi.nlm.nih.gov", "who.int", "gov.cn", "moe.gov.cn",
]

# 场景模式配置：(权威源最小条数, 目标总条数, 相关性门槛)
_MODE_CONFIG: dict[str, tuple[int, int, float]] = {
    "daily": (4, 6, 0.16),      # 日常速查：够用就好，快
    "rigorous": (6, 8, 0.18),   # 严谨求证：权威源要足
    "study": (6, 8, 0.18),      # 学习求证：优先高校/科研/百科
    "academic": (6, 8, 0.18),   # 学术引用（study 的别名）
}

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
_LEVEL_RANK = {"A": 3, "B": 2, "C": 1, "D": 0}


def classify_domain(url: str) -> tuple[str, int, str, str]:
    """按域名给出 (可信度等级, 基础分, 机构类型, 归属分类)。"""
    host = (urlparse(url).hostname or "").lower()
    for key, level, score, kind, category in _DOMAIN_RULES:
        if host == key or host.endswith("." + key):
            return level, score, kind, category
    return _DEFAULT_RULE


def authority_reason(source: dict) -> str:
    """给出"凭什么算权威"的通俗解释，供前端展示。"""
    host = source.get("domain") or ""
    if not host:
        host = urlparse(source.get("url", "")).hostname or "未知站点"
    level = source.get("credibility", "C")
    score = source.get("credibility_score", 55)
    kind = source.get("org_type") or "一般站点"
    lvl_txt = {"A": "权威", "B": "较可靠", "C": "一般"}.get(level, "一般")
    if level == "C":
        return f"{host} 未列入权威域名库，按一般来源计（{score} 分），仅供参考，不宜单独作为依据。"
    return f"{host} 归属「{kind}」，已列入权威域名库，判定为{lvl_txt}来源（{score} 分）。"


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
    """计算来源与待核实内容的相关性（0~1）。"""
    title = source.get("title", "")
    snippet = source.get("snippet", "")
    blob = title + " " + snippet
    score = 0.0
    hit_kw = [k for k in keywords if k and k in blob]
    if keywords:
        score += 0.45 * (len(hit_kw) / len(keywords))
    if any(k and k in title for k in keywords):
        score += 0.15
    tb, sb = _bigrams(text), _bigrams(blob)
    if tb and sb:
        score += 0.30 * min(len(tb & sb) / max(len(tb), 1), 1.0)
    if _is_homepage(source.get("url", "")):
        score *= 0.25
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
    level, score, kind, category = classify_domain(url)
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
        "category": category,
        "authority_reason": authority_reason({
            "domain": urlparse(url).hostname or "baike.baidu.com",
            "credibility": level,
            "credibility_score": score,
            "org_type": kind,
        }),
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
        level, score, kind, category = classify_domain(url)
        host = urlparse(url).hostname or ""
        out.append({
            "title": title[:120],
            "url": url,
            "domain": host,
            "published_at": time.strftime("%Y-%m-%d"),
            "credibility": level,
            "credibility_score": score,
            "snippet": snippet[:300],
            "source_type": "search",
            "org_type": kind,
            "category": category,
            "authority_reason": authority_reason({
                "domain": host,
                "credibility": level,
                "credibility_score": score,
                "org_type": kind,
            }),
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


def _is_authority(s: dict) -> bool:
    return _LEVEL_RANK.get(s.get("credibility", "C"), 1) >= 2


def _probe_authority(keywords: list[str], mode: str) -> list[dict]:
    """权威源不足时的定向补充检索：site: 官方域名。"""
    if not keywords:
        return []
    study_like = mode in ("academic", "study")
    hosts = list(_ACADEMIC_PROBE) if study_like else list(_AUTHORITY_PROBE)
    if study_like:
        hosts = hosts + [h for h in _AUTHORITY_PROBE if h not in hosts]
    queries = [f"{keywords[0]} site:{h}" for h in hosts[:8]]
    out: list[dict] = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(search_bing, q, 4) for q in queries]
        for fut in futures:
            try:
                out.extend(fut.result(timeout=20))
            except Exception:
                continue
    return [s for s in _dedup(out) if _is_authority(s)]


def web_search(
    keywords: list[str],
    text: str,
    max_sources: int = 8,
    mode: str = "rigorous",
) -> dict:
    """并发多源检索 + 权威配额保障 + 相关性过滤。

    流程：常规多源检索 → 权威源计数不足则用 site: 定向补充 →
    权威优先排序 → 截取目标条数。
    """
    authority_min, target, rel_gate = _MODE_CONFIG.get(mode, _MODE_CONFIG["rigorous"])
    target = max(target, max_sources) if max_sources > target else target

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
    for s in results:
        s["relevance"] = relevance_score(s, keywords, text)
    results = [s for s in results if s["relevance"] >= rel_gate]

    # 权威配额保障：不足则定向补充官方源
    authority_now = sum(1 for s in results if _is_authority(s))
    if authority_now < authority_min:
        extra = _probe_authority(keywords, mode)
        for s in extra:
            s["relevance"] = relevance_score(s, keywords, text)
        extra = [s for s in extra if s["relevance"] >= rel_gate * 0.7]
        seen = {s["url"].rstrip("/") for s in results}
        added = [s for s in extra if s["url"].rstrip("/") not in seen]
        results.extend(added)
        trace.append({
            "channel": "authority_probe",
            "query": f"site: 官方域名补充（目标 {authority_min} 条）",
            "hits": len(added),
        })

    # 权威优先：等级 → 权威分 → 相关性
    results.sort(
        key=lambda s: (
            _LEVEL_RANK.get(s.get("credibility", "C"), 1),
            s.get("credibility_score", 55),
            s.get("relevance", 0),
        ),
        reverse=True,
    )
    results = results[:target]
    return {
        "sources": results,
        "trace": trace,
        "ok": bool(results),
        "engine": "web" if results else "none",
        "authority_count": sum(1 for s in results if _is_authority(s)),
        "authority_target": authority_min,
    }
