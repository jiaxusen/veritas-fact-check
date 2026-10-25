"""接口层端到端测试：使用 FastAPI TestClient，不依赖端口占用。"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fastapi.testclient import TestClient
from main import app
def main() -> int:
    client = TestClient(app)
    ok = 0
    fail = 0
    def check(name, cond, detail=""):
        nonlocal ok, fail
        if cond:
            ok += 1
            print(f"[PASS] {name} {detail}")
        else:
            fail += 1
            print(f"[FAIL] {name} {detail}")
    print("=" * 70)
    print("接口层端到端测试")
    print("=" * 70)
    # 1. 健康检查
    r = client.get("/api/health")
    check("GET /api/health", r.status_code == 200 and r.json()["status"] == "ok", str(r.json()))
    # 2. 正常查证（谣言）
    r = client.post("/api/verify", json={"text": "手机整夜充电会严重损坏电池"})
    d = r.json()
    check("POST /api/verify 谣言", r.status_code == 200 and d["verdict"]["label"] == "不实",
          f"→ {d['verdict']['label']} {d['verdict']['confidence']}%")
    check("  依据均带来源链接", all(i["source_url"] for i in d["evidence"]["refute"]))
    check("  来源含域名与时间", all(s["domain"] and s["published_at"] for s in d["sources"]))
    # 3. 正常查证（真实）
    r = client.post("/api/verify", json={"text": "地球是一个两极稍扁、赤道略鼓的球体"})
    d = r.json()
    check("POST /api/verify 真实", r.status_code == 200 and d["verdict"]["label"] == "属实",
          f"→ {d['verdict']['label']} {d['verdict']['confidence']}%")
    # 4. 边界（信息不足）
    r = client.post("/api/verify", json={"text": "网传某地近日出现不明飞行物并伴有异响"})
    d = r.json()
    check("POST /api/verify 边界", r.status_code == 200 and d["verdict"]["label"] == "存疑",
          f"→ {d['verdict']['label']} {d['verdict']['confidence']}%")
    # 5. 空输入校验
    r = client.post("/api/verify", json={"text": "   "})
    check("空输入返回 400", r.status_code == 400, r.json().get("detail", ""))
    # 6. 过短输入校验
    r = client.post("/api/verify", json={"text": "啊"})
    check("过短输入返回 400", r.status_code == 400, r.json().get("detail", ""))
    # 7. 批量查证
    r = client.post("/api/verify/batch", json={"texts": ["地球是球体", "手机整夜充电会严重损坏电池"]})
    d = r.json()
    check("POST /api/verify/batch", r.status_code == 200 and d["total"] == 2,
          f"→ {[x['card']['verdict']['label'] for x in d['results'] if x['ok']]}")
    # 8. 大模型接口回退
    r = client.post("/api/verify/llm", json={"text": "中国长城总长度超过2万公里"})
    d = r.json()
    check("POST /api/verify/llm 自动回退", r.status_code == 200 and "engine" in d,
          f"→ engine={d['engine']}")
    # 9. 历史记录
    r = client.get("/api/history")
    check("GET /api/history", r.status_code == 200 and len(r.json()["records"]) > 0,
          f"→ {len(r.json()['records'])} 条")
    # 10. 前端页面挂载
    r = client.get("/")
    check("GET / 前端页面", r.status_code == 200 and "查证台" in r.text)
    print("=" * 70)
    print(f"合计 {ok + fail} 项 ｜ 通过 {ok} ｜ 失败 {fail}")
    print("=" * 70)
    return 0 if fail == 0 else 1
if __name__ == "__main__":
    raise SystemExit(main())