# -*- coding: utf-8 -*-
"""生成 universities.json

数据来源（全部为可核查的公开发布件）：
1. 教育部《关于公布第二轮“双一流”建设高校及建设学科名单的通知》附件
   —— 提供 147 所建设高校及其建设学科
2. 教育部《“985工程”学校名单》 —— 39 所
3. 《985、211工程学校名单》 —— 211 工程 112 所
4. 河南省教育厅《2025 年河南省具有普通高等学历教育招生资格学校名单》
   —— 河南省本科 61 所、专科 116 所

省份/城市/院校类型为辅助定位信息，字段 geo_verified=false，
查证结论不应单独依赖该字段。
"""

import io
import json
import re
import sys
import zipfile
import collections
import datetime
import os

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = r"C:\Users\jqw33\AppData\Local\Temp"
sys.path.insert(0, TMP)

import uni_meta as M
import uni_henan as H


def canon(s):
    """统一校名：括号统一为全角，去除空白差异。

    教育部原始文件使用全角括号（如「中国石油大学（华东）」），
    而部分名录使用半角，不统一会生成重复记录。
    """
    s = s.replace("(", "（").replace(")", "）").replace("(", "（").replace(")", "）")
    return s.strip()


def parse_docx(path):
    """解析双一流名单 docx，返回 [(校名, 学科文本)]"""
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    paras = re.findall(r"<w:p[ >].*?</w:p>", xml, flags=re.S)
    rows = []
    for p in paras:
        txt = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", p, flags=re.S))
        txt = txt.replace("&amp;", "&").strip()
        if not txt or txt.startswith("附件") or txt.startswith("第二轮") or txt.startswith("（按"):
            continue
        if "：" not in txt and ":" not in txt:
            continue
        name, _, rest = re.split(r"[：:]", txt, maxsplit=1)[0], None, txt.split("：", 1)[1] if "：" in txt else txt.split(":", 1)[1]
        rows.append((canon(name), rest.strip()))
    return rows


def split_disciplines(raw):
    if raw.startswith("（自主确定"):
        return [], raw
    return [x.strip() for x in re.split(r"[、,，]", raw) if x.strip()], None


def load_geo():
    geo = {}
    for line in M.GEO.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split("|")
        if len(parts) < 4:
            raise ValueError("GEO 行格式错误: " + line)
        name, prov, city, utype = canon(parts[0]), parts[1].strip(), parts[2].strip(), parts[3].strip()
        aliases = [canon(a) for a in parts[4].split(",")] if len(parts) > 4 and parts[4].strip() else []
        geo[name] = {"province": prov, "city": city, "type": utype, "aliases": aliases}
    return geo


def load_set(text):
    return [x for x in text.split() if x]


def norm_paren(name):
    """把全角括号内的曾用名拆出来，返回 (正名, 曾用名 or None)"""
    m = re.search(r"（原(.+?)）$", name)
    if m:
        return name[: m.start()].strip(), m.group(1).strip()
    return name, None


def build():
    geo = load_geo()
    set985 = {canon(x) for x in load_set(M.S985)}
    set211 = {canon(M.ALIAS_211.get(x, x)) for x in load_set(M.S211)}

    rows = parse_docx(os.path.join(TMP, "ts.docx"))
    if len(rows) != 147:
        print("!! 双一流名单解析出 %d 条，预期 147 条" % len(rows))

    uni = collections.OrderedDict()

    def get(name):
        if name not in uni:
            rec = {
                "id": "",
                "name": name,
                "aliases": [],
                "province": None,
                "city": None,
                "type": None,
                "school_level": None,
                "tags": [],
                "dfc_disciplines": None,
                "dfc_note": None,
                "former_names": [],
                "sources": [],
                "geo_verified": False,
                "geo_source": None,
                "data_fields": [],
            }
            rec.update({k: v for k, v in geo.get(name, {}).items() if k != "aliases"})
            rec["aliases"] = list(geo.get(name, {}).get("aliases", []))
            if geo.get(name):
                rec["geo_verified"] = True
                rec["geo_source"] = "整理"
            uni[name] = rec
        return uni[name]

    for name, raw in rows:
        rec = get(name)
        rec["tags"].append("双一流")
        discs, note = split_disciplines(raw)
        if discs:
            rec["dfc_disciplines"] = discs
        if note:
            rec["dfc_note"] = note
        rec["sources"].append("教育部第二轮双一流名单")
        rec["data_fields"].append("双一流建设学科")

    for name in sorted(set985):
        get(name)["tags"].append("985")
        r = uni.get(name)
        if r and "教育部985工程名单" not in r["sources"]:
            r["sources"].append("教育部985工程名单")

    for name in sorted(set211):
        rec = get(name)
        rec["tags"].append("211")
        if "211工程名单" not in rec["sources"]:
            rec["sources"].append("211工程名单")

    for raw in H.BENKE.split():
        name, old = norm_paren(canon(raw))
        rec = get(name)
        rec["province"] = rec["province"] or "河南省"
        rec["school_level"] = "本科"
        if old:
            rec["former_names"].append(old)
        src = "河南省2025年招生资格名单"
        if src not in rec["sources"]:
            rec["sources"].append(src)
        if "河南省名单（层次）" not in rec["data_fields"]:
            rec["data_fields"].append("河南省名单（层次）")

    for raw in H.ZHUANKE.split():
        name, old = norm_paren(canon(raw))
        rec = get(name)
        rec["province"] = rec["province"] or "河南省"
        rec["school_level"] = rec["school_level"] or "专科"
        if old:
            rec["former_names"].append(old)
        src = "河南省2025年招生资格名单"
        if src not in rec["sources"]:
            rec["sources"].append(src)

    # 河南高校的城市：仅从校名前缀安全推断
    for rec in uni.values():
        if rec["city"] or rec["province"] != "河南省":
            continue
        name = rec["name"]
        if name in H.CITY_OVERRIDE:
            rec["city"] = H.CITY_OVERRIDE[name] + "市"
            rec["geo_source"] = "整理"
            continue
        hit = None
        for prefix, city in H.PREFIX_CITY.items():
            if name.startswith(prefix):
                hit = city
                break
        if hit is None:
            for county, city in H.COUNTY_TO_CITY.items():
                if name.startswith(county):
                    hit = city
                    break
        if hit:
            rec["city"] = hit + "市"
            rec["geo_source"] = "校名推断"

    records = []
    for i, (name, rec) in enumerate(sorted(uni.items()), 1):
        rec["id"] = "U%04d" % i
        order = ["985", "211", "双一流"]
        rec["tags"] = [t for t in order if t in rec["tags"]] + [t for t in rec["tags"] if t not in order]
        rec["sources"] = sorted(set(rec["sources"]))
        rec["data_fields"] = sorted(set(rec["data_fields"]))
        records.append(rec)

    return records


def main():
    records = build()
    out = {
        "schema_version": "1.0",
        "generated_at": datetime.date.today().isoformat(),
        "meta": {
            "description": "高校知识库。仅收录有公开发布文件可核查的数据，"
                           "未覆盖全国普通高等学校全量名单，可通过 import_universities.py "
                           "导入教育部《全国高等学校名单》补齐。",
            "national_total_hint": "截至2025年6月20日，全国普通高等学校2919所"
                                   "（本科1365所、高职专科1554所），另有成人高校248所。",
            "sources": [
                {
                    "name": "关于公布第二轮“双一流”建设高校及建设学科名单的通知",
                    "publisher": "教育部、财政部、国家发展改革委",
                    "url": "https://www.moe.gov.cn/srcsite/A22/s7065/202202/W020220214318455516037.pdf",
                    "published_at": "2022-02-14",
                    "provides": ["双一流建设高校名单", "双一流建设学科"],
                },
                {
                    "name": "“985工程”学校名单",
                    "publisher": "教育部",
                    "url": "https://www.moe.gov.cn/srcsite/A22/s7065/200612/t20061206_128833.html",
                    "provides": ["985工程39所"],
                },
                {
                    "name": "985、211工程学校名单",
                    "publisher": "211工程名录公开发布件",
                    "provides": ["211工程112所"],
                },
                {
                    "name": "2025年河南省具有普通高等学历教育招生资格学校名单",
                    "publisher": "河南省教育厅",
                    "url": "https://jyt.henan.gov.cn/2025/06-27/3174801.html",
                    "published_at": H.PUBLISHED_AT,
                    "provides": ["河南省本科61所", "河南省专科116所"],
                },
            ],
            "field_notes": {
                "geo_verified": "false 表示省份/城市为按校名推断或未核验，不可作为查证结论依据",
                "dfc_disciplines": "第二轮双一流建设学科；自行公布学科的学校该字段为空，见 dfc_note",
                "school_level": "办学层次：本科 / 专科，来自河南省名单",
                "tags": "层次标签：985 / 211 / 双一流",
            },
        },
        "stats": {},
        "universities": records,
    }

    c_level = collections.Counter()
    c_tag = collections.Counter()
    c_prov = collections.Counter()
    for r in records:
        if r["school_level"]:
            c_level[r["school_level"]] += 1
        for t in r["tags"]:
            c_tag[t] += 1
        c_prov[r["province"] or "未知"] += 1

    out["stats"] = {
        "total": len(records),
        "by_tag": dict(c_tag),
        "by_school_level": dict(c_level),
        "by_province_top": dict(c_prov.most_common(12)),
        "geo_verified": sum(1 for r in records if r["geo_verified"]),
        "with_disciplines": sum(1 for r in records if r["dfc_disciplines"]),
    }

    dest = os.path.join(HERE, "data", "universities.json")
    io.open(dest, "w", encoding="utf-8", newline="\n").write(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    print("已生成:", dest)
    print("记录数:", len(records))
    print("标签统计:", dict(c_tag))
    print("层次统计:", dict(c_level))
    print("省份 Top:", dict(c_prov.most_common(8)))
    print("含建设学科:", out["stats"]["with_disciplines"])


if __name__ == "__main__":
    main()
