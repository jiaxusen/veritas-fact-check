# -*- coding: utf-8 -*-
"""把教育部《全国高等学校名单》合并进本项目的 universities.json。

用法
----
    python import_universities.py 名单.xlsx
    python import_universities.py 名单.csv
    python import_universities.py 名单.xlsx --dry-run

支持格式
--------
.xlsx  由本脚本用标准库直接解析（不需要 openpyxl / pandas）
.csv   要求 UTF-8 或 GBK，自动识别
.xls   旧二进制格式无 xlrd 无法解析，请先用 Excel 另存为 .xlsx 或 .csv

数据可在教育部「全国高等学校名单」发布页下载：
    https://www.moe.gov.cn/jyb_xxgk/s5743/s5744/A03/

合并规则
--------
1. 按校名匹配已有记录（括号统一为全角、去空白）
2. 官方名单里的「所在地」「办学层次」「主管部门」覆盖人工整理值，
   并把 geo_verified 置为 True、geo_source 标记为「教育部名单」
3. 名单中存在但本库没有的院校，作为新记录追加（不带层次标签）
4. 只更新有官方数据支撑的字段，其余字段保持原样
5. 写入前自动备份 universities.json

注意：本脚本不会删除任何已有记录。若官方名单中已不存在的院校需要清理，
请在备份后手工处理，避免误删历史数据。
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import shutil
import sys
from datetime import date
from pathlib import Path
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / "data" / "universities.json"

HEADER_ALIAS = {
    "学校名称": "name", "院校名称": "name", "名称": "name", "校名": "name",
    "主管部门": "supervisor", "主管部门名称": "supervisor",
    "所在地": "province", "所在地省": "province", "省份": "province", "省区市": "province",
    "办学层次": "school_level", "层次": "school_level",
    "备注": "note",
    "所在地市": "city", "城市": "city",
}

PROVINCE_SUFFIX = re.compile(r"(省|市|自治区|特别行政区)$")


def canon(name: str) -> str:
    """规范化校名：括号统一全角、去空白。"""
    if name is None:
        return ""
    out = name.replace("(", "（").replace(")", "）")
    out = re.sub(r"\s+", "", out)
    return out.strip()


# ---------- 读取 ----------

def read_xlsx(path: Path) -> list[list[str]]:
    """用标准库解析 xlsx，返回二维字符串表。"""
    with ZipFile(path) as z:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            xml = z.read("xl/sharedStrings.xml").decode("utf-8", "replace")
            for si in re.findall(r"<si>(.*?)</si>", xml, flags=re.S):
                shared.append("".join(re.findall(r"<t[^>]*>(.*?)</t>", si, flags=re.S)))
        name = "xl/worksheets/sheet1.xml"
        if name not in z.namelist():
            sheets = sorted(n for n in z.namelist()
                            if n.startswith("xl/worksheets/") and n.endswith(".xml"))
            if not sheets:
                raise SystemExit("未在 %s 中找到工作表" % path)
            name = sheets[0]
        xml = z.read(name).decode("utf-8", "replace")

    rows: list[list[str]] = []
    for row_xml in re.findall(r"<row[ >].*?</row>", xml, flags=re.S):
        cells: dict[int, str] = {}
        for c in re.findall(r"<c[ >].*?</c>|<c[^>]*/>", row_xml, flags=re.S):
            ref = re.search(r'r="([A-Z]+)(\d+)"', c)
            if not ref:
                continue
            col = _col_to_index(ref.group(1))
            t = re.search(r't="([^"]+)"', c)
            v = re.search(r"<v>(.*?)</v>", c, flags=re.S)
            inline = re.search(r"<t[^>]*>(.*?)</t>", c, flags=re.S)
            if t and t.group(1) == "s" and v:
                idx = int(v.group(1))
                value = shared[idx] if idx < len(shared) else ""
            elif inline is not None:
                value = inline.group(1)
            elif v is not None:
                value = v.group(1)
            else:
                value = ""
            value = value.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            cells[col] = value
        if cells:
            width = max(cells) + 1
            rows.append([cells.get(i, "") for i in range(width)])
    return rows


def _col_to_index(col: str) -> int:
    n = 0
    for ch in col:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def read_csv(path: Path) -> list[list[str]]:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "gb18030", "utf-8"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise SystemExit("无法识别 CSV 编码：%s" % path)
    return list(csv.reader(io.StringIO(text)))


def load_table(path: Path) -> tuple[list[dict], str]:
    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        rows = read_xlsx(path)
    elif suffix == ".csv":
        rows = read_csv(path)
    else:
        raise SystemExit("不支持的格式：%s（请用 .xlsx 或 .csv）" % suffix)
    if not rows:
        raise SystemExit("表格为空：%s" % path)

    # 找表头行：包含「学校名称」或「名称」的行
    header_row = None
    for i, r in enumerate(rows[:5]):
        joined = "".join(r)
        if "名称" in joined or "学校" in joined:
            header_row = i
            break
    if header_row is None:
        raise SystemExit("未找到表头，请确认文件包含「学校名称」列")

    header = [h.strip() for h in rows[header_row]]
    mapping = {}
    for i, h in enumerate(header):
        for key, field in HEADER_ALIAS.items():
            if key in h and field not in mapping:
                mapping[field] = i
                break
    if "name" not in mapping:
        raise SystemExit("未识别「学校名称」列，实际表头：%s" % header)

    out = []
    for r in rows[header_row + 1:]:
        if len(r) <= mapping["name"]:
            continue
        rec = {f: r[i].strip() if i < len(r) else "" for f, i in mapping.items()}
        if canon(rec.get("name", "")):
            out.append(rec)
    return out, header


# ---------- 合并 ----------

def normalize_province(v: str) -> str:
    v = (v or "").strip()
    return v


def merge(db: dict, table: list[dict], source_name: str) -> dict:
    recs = db.setdefault("universities", [])
    by_name = {canon(r["name"]): r for r in recs}
    added, updated = 0, 0

    for row in table:
        key = canon(row.get("name", ""))
        if not key:
            continue
        rec = by_name.get(key)
        if rec is None:
            rec = {
                "id": "",
                "name": key,
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
            recs.append(rec)
            by_name[key] = rec
            added += 1
        changed = False

        prov = normalize_province(row.get("province", ""))
        if prov and rec.get("province") != prov:
            rec["province"] = prov
            if row.get("city"):
                rec["city"] = row["city"].strip()
            rec["geo_verified"] = True
            rec["geo_source"] = source_name
            changed = True

        lv = (row.get("school_level") or "").strip()
        if lv in ("本科", "专科") and rec.get("school_level") != lv:
            rec["school_level"] = lv
            changed = True

        sup = (row.get("supervisor") or "").strip()
        if sup and rec.get("supervisor") != sup:
            rec["supervisor"] = sup
            changed = True

        note = (row.get("note") or "").strip()
        if note and "民办" in note:
            rec["nature"] = "民办"
            changed = True
        elif note and rec.get("nature") is None:
            rec["nature"] = "公办"
            changed = True

        src_field = "教育部全国高等学校名单"
        if src_field not in rec.get("sources", []):
            rec.setdefault("sources", []).append(src_field)
            changed = True
        if source_name not in rec.get("data_fields", []):
            rec.setdefault("data_fields", []).append(source_name)
            changed = True

        if changed:
            updated += 1

    return {"added": added, "updated": updated}


def renumber(db: dict) -> None:
    for i, rec in enumerate(sorted(db["universities"], key=lambda r: r["name"]), 1):
        rec["id"] = "U%04d" % i


def refresh_stats(db: dict) -> None:
    import collections
    c_tag = collections.Counter()
    c_level = collections.Counter()
    for r in db["universities"]:
        for t in r.get("tags", []):
            c_tag[t] += 1
        if r.get("school_level"):
            c_level[r["school_level"]] += 1
    db.setdefault("stats", {})
    db["stats"].update({
        "total": len(db["universities"]),
        "by_tag": dict(c_tag),
        "by_school_level": dict(c_level),
        "geo_verified": sum(1 for r in db["universities"] if r.get("geo_verified")),
        "with_disciplines": sum(1 for r in db["universities"] if r.get("dfc_disciplines")),
    })


def main() -> None:
    ap = argparse.ArgumentParser(description="导入教育部《全国高等学校名单》")
    ap.add_argument("file", help="名单文件（.xlsx 或 .csv）")
    ap.add_argument("--dry-run", action="store_true", help="只打印合并结果，不写入文件")
    ap.add_argument("--source-name", default="教育部名单",
                    help="本次导入数据的来源标记，默认「教育部名单」")
    args = ap.parse_args()

    path = Path(args.file).expanduser()
    if not path.is_file():
        raise SystemExit("文件不存在：%s" % path)

    table, header = load_table(path)
    print("表头：%s" % header)
    print("读入院校：%d 所" % len(table))
    print("样例：%s" % table[0])

    db = json.loads(DB_PATH.read_text(encoding="utf-8"))
    before = len(db.get("universities", []))
    result = merge(db, table, args.source_name)
    renumber(db)
    refresh_stats(db)

    print()
    print("合并前：%d 所" % before)
    print("新增  ：%d 所" % result["added"])
    print("更新  ：%d 所" % result["updated"])
    print("合并后：%d 所" % len(db["universities"]))
    print("可核验所在地：%d 所" % db["stats"]["geo_verified"])

    if args.dry_run:
        print("\n[dry-run] 未写入文件")
        return

    backup = DB_PATH.with_suffix(".json.bak")
    shutil.copy(DB_PATH, backup)
    print("\n已备份：%s" % backup.name)

    meta = db.setdefault("meta", {})
    meta["last_import"] = {
        "file": path.name,
        "imported_at": date.today().isoformat(),
        "rows": len(table),
        "source_label": args.source_name,
    }
    DB_PATH.write_text(json.dumps(db, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
    print("已写入：%s" % DB_PATH)


if __name__ == "__main__":
    main()
