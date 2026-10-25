"""三轮自测：基础用例（真实）/ 负面用例（谣言）/ 边界用例（信息不足）。"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pipeline import run_pipeline
CASES = [
    ("基础用例·真实信息", "地球是一个两极稍扁、赤道略鼓的球体", "属实"),
    ("基础用例·真实信息", "中国长城总长度超过2万公里", "属实"),
    ("负面用例·典型谣言", "手机整夜充电会严重损坏电池", "不实"),
    ("负面用例·典型谣言", "用微波炉加热食物会产生致癌物", "不实"),
    ("负面用例·典型谣言", "接种疫苗会导致儿童自闭症", "不实"),
    ("边界用例·信息不足", "网传某地近日出现不明飞行物并伴有异响", "存疑"),
    ("边界用例·信息不足", "听说隔壁小区有人在楼道里养了一只奇怪的动物", "存疑"),
]
def main() -> int:
    passed = 0
    failed = 0
    print("=" * 78)
    print("查证工具 · 三轮自测")
    print("=" * 78)
    for name, text, expect in CASES:
        card = run_pipeline(text)
        got = card["verdict"]["label"]
        ok = got == expect
        passed += ok
        failed += (not ok)
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {name}")
        print(f"       输入：{text}")
        print(f"       预期：{expect} ｜ 实际：{got} ｜ 置信度：{card['verdict']['confidence']}%")
        print(f"       依据：支持 {card['evidence_stats']['support_count']} 条 / "
              f"矛盾 {card['evidence_stats']['refute_count']} 条 / 来源 {card['evidence_stats']['source_count']} 条")
        # 硬约束校验：每条依据必须对应来源链接
        for bucket in ("support", "refute"):
            for item in card["evidence"][bucket]:
                assert item["source_url"], f"依据缺少来源链接：{item}"
        print()
    print("=" * 78)
    print(f"合计 {len(CASES)} 例 ｜ 通过 {passed} ｜ 失败 {failed}")
    print("=" * 78)
    return 0 if failed == 0 else 1
if __name__ == "__main__":
    raise SystemExit(main())