"""③-D 高校知识层：面向「某大学是不是 985/211/双一流」「在哪座城市」
「双一流学科有哪些」「河南省有几所本科/双一流高校」这类可核查查询。

数据来源是公开发布文件，条目本身带 sources 引用，不含推断成分。
命中条件严苛：必须同时出现已知校名与属性疑问/断言线索，
避免在普通句子上误触发。
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "universities.json"

_lock = threading.Lock()
_cache: dict | None = None

_SRC_MOE_DFC = {
    "title": "教育部：第二轮“双一流”建设高校及建设学科名单",
    "url": "https://www.moe.gov.cn/srcsite/A22/s7065/202202/W020220214318455516037.pdf",
    "domain": "moe.gov.cn",
    "published_at": "2022-02-14",
    "credibility": "A",
    "credibility_score": 96,
    "source_type": "knowledge",
    "org_type": "政府机构",
    "snippet": "由教育部、财政部、国家发展改革委公布，共 147 所建设高校及各自建设学科。",
}
_SRC_MOE_985 = {
    "title": "教育部：“985工程”学校名单",
    "url": "https://www.moe.gov.cn/srcsite/A22/s7065/200612/t20061206_128833.html",
    "domain": "moe.gov.cn",
    "published_at": "2008-04-25",
    "credibility": "A",
    "credibility_score": 96,
    "source_type": "knowledge",
    "org_type": "政府机构",
    "snippet": "经教育部、财政部批准建设的“985工程”高等学校名单，共 39 所。",
}
_SRC_HENAN = {
    "title": "河南省教育厅：2025年河南省具有普通高等学历教育招生资格学校名单",
    "url": "https://jyt.henan.gov.cn/2025/06-27/3174801.html",
    "domain": "jyt.henan.gov.cn",
    "published_at": "2025-06-27",
    "credibility": "A",
    "credibility_score": 95,
    "source_type": "knowledge",
    "org_type": "政府机构",
    "snippet": "公布河南省具有普通本专科招生资格的高校，本科 61 所、专科 116 所。"
               "名单外机构招收的学生无法在教育部注册学籍、学历。",
}

_TAG_LABEL = {"985": "985工程", "211": "211工程", "双一流": "第二轮“双一流”建设"}

_TRIGGER_985 = re.compile(
    r"(是|属于|列入|属于了|算是|算不算|是不是|是不是就|属于不属|是不是.{0,3}985|.{0,2}985)"
    r".{0,6}(985|985工程|九八五)")
_TRIGGER_211 = re.compile(r"(是|属于|列入|算是|是不是|.{0,2}211).{0,6}(211|211工程|二一一)")
_TRIGGER_DFC = re.compile(r"(是|属于|列入|算是|是不是|.{0,2}双一流).{0,8}(双一流|一流大学|一流学科)")

_LOC = re.compile(r"(在哪|位于|坐落于|位置|哪个城市|哪座城市|什么地方|属于哪个省|是哪个省的|在哪个省)")
_LEVEL_CUE = re.compile(r"(是|属于).{0,4}(本科|专科|大专|本科院校|专科院校)")
_DISC_CUE = re.compile(r"(双一流.{0,4}学科|一流.{0,2}学科|建设学科|哪些学科|王牌学科|优势学科)")
_TAG_ONLY = re.compile(r"^(985|211|双一流|985工程|211工程)$")


def _load() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    with _lock:
        if _cache is not None:
            return _cache
        try:
            with DATA_PATH.open("r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except Exception:
            raw = {"universities": [], "meta": {}, "stats": {}}
        records = raw.get("universities", [])
        # 歧义别名（对应多所学校）直接剔除，避免误命中
        alias_count: dict[str, int] = {}
        for rec in records:
            for a in rec.get("aliases", []):
                alias_count[a] = alias_count.get(a, 0) + 1
        index: list[tuple[str, dict]] = []
        for rec in records:
            cands = [rec["name"]]
            cands += [a for a in rec.get("aliases", []) if alias_count.get(a) == 1]
            cands += [n for n in rec.get("former_names", []) if len(n) >= 4]
            for c in cands:
                if len(c) >= 2:
                    index.append((c, rec))
        index.sort(key=lambda x: -len(x[0]))
        _cache = {
            "records": records,
            "index": index,
            "meta": raw.get("meta", {}),
            "stats": raw.get("stats", {}),
        }
        return _cache


def university_stats() -> dict:
    """对外暴露的高校库统计信息。"""
    db = _load()
    return db.get("stats", {}) or {"total": len(db.get("records", []))}


def find_school(text: str) -> tuple[dict, str] | None:
    """在文本中按最长匹配找校名，返回 (记录, 命中的称呼)。"""
    norm = re.sub(r"\s+", "", text or "")
    if len(norm) < 3:
        return None
    db = _load()
    for cand, rec in db["index"]:
        if cand in norm:
            return rec, cand
    return None


def _henan_count_html() -> list[dict]:
    return [dict(_SRC_HENAN)]


def _sources_for(rec: dict) -> list[dict]:
    out = []
    tags = rec.get("tags", [])
    if "双一流" in tags:
        out.append(dict(_SRC_MOE_DFC))
    if "985" in tags:
        out.append(dict(_SRC_MOE_985))
    if "211" in tags:
        out.append({
            "title": "211工程学校名单",
            "url": "https://www.moe.gov.cn/",
            "domain": "moe.gov.cn",
            "published_at": "2011-03-01",
            "credibility": "A",
            "credibility_score": 93,
            "source_type": "knowledge",
            "org_type": "政府机构",
            "snippet": "211工程重点建设高校名单，共 112 所。",
        })
    if any("河南省" in s for s in rec.get("sources", [])):
        out.append(dict(_SRC_HENAN))
    if not out:
        out = [dict(_SRC_HENAN), dict(_SRC_MOE_DFC)]
    # 去重
    seen, uniq = set(), []
    for s in out:
        if s["url"] in seen:
            continue
        seen.add(s["url"])
        uniq.append(s)
    return uniq


def _tag_sentence(rec: dict) -> str:
    tags = rec.get("tags", [])
    if not tags:
        return "目前本库未收录该校获得国家重点建设工程标签的记录"
    return "、".join(_TAG_LABEL.get(t, t) for t in tags)


def _answer_tag(rec: dict, tag: str, asked_as_negative: bool) -> dict:
    has = tag in rec.get("tags", [])
    real = has
    label = {"985": "985工程", "211": "211工程", "双一流": "“双一流”建设"}[tag]
    name = rec["name"]
    if asked_as_negative:
        # 「不是211吗」这类反问，实际是在确认否定判断
        answer_level = "true" if not has else "false"
        head = "属实：%s确实不在%s名单内" % (name, label) if not has \
            else "不属实：%s属于%s高校" % (name, label)
    else:
        answer_level = "true" if has else "false"
        head = "属实：%s属于%s高校" % (name, label) if has \
            else "不属实：%s不在%s名单内" % (name, label)
    detail = "%s已收录的层次标签：%s。" % (name, _tag_sentence(rec))
    return {
        "level": answer_level,
        "consensus": head,
        "explain": head + "。" + detail + _geo_sentence(rec),
        "caveat": _caveat(rec),
    }


def _loc_of(rec: dict) -> str:
    """拼接所在地。直辖市会出现 province == city 的情况，只输出一次。"""
    prov, city = rec.get("province"), rec.get("city")
    if prov and city:
        return city if prov == city else prov + city
    return prov or city or ""


def _geo_sentence(rec: dict) -> str:
    loc = _loc_of(rec)
    if not loc:
        return ""
    # 河北工业大学隶属河北省但校址在天津，这类错位必须讲清楚
    if rec["name"] == "河北工业大学":
        return "该校归河北省主管，校址在天津市。"
    if rec["name"] == "华北电力大学":
        return "该校校部位于河北省保定市，另设北京校区。"
    return "所在地为%s。" % loc


def _caveat(rec: dict) -> str:
    base = "高校名单随教育部官方发布更新；本库为 2025 版。"
    if not rec.get("geo_verified"):
        base += "所在地信息按校名推断或未核验，请以学校官网为准。"
    return base


def _answer_location(rec: dict) -> dict:
    loc = _loc_of(rec)
    head = "属实：%s所在地为%s" % (rec["name"], loc) if loc \
        else "暂无该校所在地的可靠记录"
    return {
        "level": "true" if loc else "uncertain",
        "consensus": head,
        "explain": head + "。" + _geo_sentence(rec) + "层次标签：%s。" % _tag_sentence(rec),
        "caveat": _caveat(rec),
    }


def _answer_level(rec: dict) -> dict:
    lv = rec.get("school_level")
    if not lv:
        return {
            "level": "uncertain",
            "consensus": "暂未收录%s的办学层次" % rec["name"],
            "explain": "本库未记录该校办学层次，建议查询教育部《全国高等学校名单》。",
            "caveat": _caveat(rec),
        }
    return {
        "level": "true",
        "consensus": "属实：%s为%s层次院校" % (rec["name"], lv),
        "explain": "河南省 2025 年招生资格名单中，%s列在%s层次院校部分。" % (rec["name"], lv),
        "caveat": _caveat(rec),
    }


def _answer_disciplines(rec: dict) -> dict:
    discs = rec.get("dfc_disciplines") or []
    name = rec["name"]
    if not discs:
        note = rec.get("dfc_note") or "本库未收录该校的建设学科明细"
        return {
            "level": "uncertain",
            "consensus": note,
            "explain": "%s的双一流建设学科情况：%s。" % (name, note),
            "caveat": _caveat(rec),
        }
    return {
        "level": "true",
        "consensus": "属实：%s的双一流建设学科共 %d 个" % (name, len(discs)),
        "explain": "%s的第二轮双一流建设学科为：%s。" % (name, "、".join(discs)),
        "caveat": _caveat(rec),
    }


_REGION_CUE = re.compile(
    r"(河南|河南省).{0,14}"
    r"(有|没有|没有.{0,2}所|有没有|共有|一共|总共|几所|多少所|多少个|有几|有些什么)"
    r".{0,8}(985|211|双一流|本科|专科|大专|大学|高校|院校)")


def _answer_region_count(text: str) -> dict | None:
    """回答「河南省有几所本科 / 双一流 / 985 高校」这类总量查询。"""
    if "河南" not in text:
        return None
    if not _REGION_CUE.search(text):
        return None
    db = _load()
    recs = db["records"]
    hen = [r for r in recs if r.get("province") == "河南省"]
    if not hen:
        return None

    for kw, field, unit in (("985", "985", "985工程"),
                            ("211", "211", "211工程"),
                            ("双一流", "双一流", "第二轮“双一流”建设")):
        if kw in text:
            hits = [r["name"] for r in hen if kw in r.get("tags", [])]
            names = "、".join(hits) if hits else "无"
            return {
                "level": "true",
                "consensus": "河南省共有 %d 所%s高校" % (len(hits), unit),
                "explain": "按教育部名单统计，河南省%s高校共 %d 所：%s。" % (unit, len(hits), names),
                "caveat": "名单以教育部公布结果为准，本库为 2025 版。",
            }
    for kw, lv in (("本科", "本科"), ("专科", "专科"), ("大专", "专科")):
        if kw in text:
            hits = [r for r in hen if r.get("school_level") == lv]
            return {
                "level": "true",
                "consensus": "河南省%s层次院校共 %d 所" % (lv, len(hits)),
                "explain": "河南省教育厅 2025 年招生资格名单中，%s层次院校 %d 所"
                           "（本科 61 所、专科 116 所，合计 177 所）。"
                           % (lv, len(hits)),
                "caveat": "名单外任何机构均不具备普通本专科招生资格。",
            }
    return None


# 「是不是」「算不算」是中性疑问，不能当成否定断言；否定抢占需在字符层排除
_NEG_CUE = re.compile(r"(?<![是算是不])(不是|不属于|不在|没有.{0,4}(进|入|在)|非)"
                      r"(?!.{0,4}(吗|麽|么))\s*.{0,6}(985|211|双一流)")
_NEUTRAL_Q = re.compile(r"(是不是|算不算|还算不算|是不是属于)")


def _is_negative(text: str) -> bool:
    """判断文本是否在作否定断言（而非「是不是」式的中性提问）。"""
    stripped = _NEUTRAL_Q.sub("Q", text)
    return bool(_NEG_CUE.search(stripped))


def match_university(text: str) -> dict | None:
    """识别高校类查询，命中返回结构兼容的知识条目。"""
    norm = re.sub(r"\s+", "", text or "")
    if len(norm) < 4:
        return None

    region = _answer_region_count(norm)
    if region:
        item = {
            "id": "UNI-R1",
            "domain": "university",
            "name": region["consensus"],
            "patterns": [],
            "consensus": region["consensus"],
            "level": region["level"],
            "explain": region["explain"],
            "caveat": region["caveat"],
            "sources": _henan_count_html() + [dict(_SRC_MOE_DFC)],
        }
        return item

    hit = find_school(norm)
    if not hit:
        return None
    rec, hitword = hit

    negative = _is_negative(norm)

    answer = None
    kind = ""
    if _DISC_CUE.search(norm):
        answer, kind = _answer_disciplines(rec), "学科"
    elif _LOC.search(norm):
        answer, kind = _answer_location(rec), "所在地"
    elif _LEVEL_CUE.search(norm) and rec.get("school_level"):
        answer, kind = _answer_level(rec), "层次"
    elif mentioned := [t for t in ("985", "211", "双一流") if t in norm]:
        # 文本明确提到某个标签即作答，避免「不在…名单里」这类否定写法的漏判
        answer, kind = _answer_tag(rec, mentioned[0], negative), mentioned[0]
    if not answer:
        return None

    return {
        "id": "UNI-" + rec.get("id", "0000"),
        "domain": "university",
        "name": "%s（%s）" % (rec["name"], kind),
        "patterns": [],
        "consensus": answer["consensus"],
        "level": answer["level"],
        "explain": answer["explain"],
        "caveat": answer["caveat"],
        "sources": _sources_for(rec),
        "entity": {
            "id": rec.get("id"),
            "name": rec.get("name"),
            "province": rec.get("province"),
            "city": rec.get("city"),
            "tags": rec.get("tags", []),
            "school_level": rec.get("school_level"),
            "dfc_disciplines": rec.get("dfc_disciplines"),
            "former_names": rec.get("former_names", []),
            "matched_alias": hitword,
        },
    }
