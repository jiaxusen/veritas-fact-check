"""访问台门禁接口测试。"""
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
    print("访问台门禁接口测试")
    print("=" * 70)
    # 1. 生成本次访问密令
    r = client.post("/api/access/generate")
    d = r.json()
    check("生成密令", r.status_code == 200 and d["code"].startswith("VC-") and len(d["code"]) == 9,
          f"→ {d['code']}（{d['ttl_minutes']} 分钟有效）")
    code = d["code"]
    # 2. 错误密令拒绝
    r = client.post("/api/access/verify", json={"code": "VC-WRONG1"})
    check("错误密令返回 403", r.status_code == 403, r.json().get("detail", ""))
    # 3. 正确密令通过并签发令牌
    r = client.post("/api/access/verify", json={"code": code})
    d = r.json()
    check("正确密令通过", r.status_code == 200 and "token" in d, f"→ token 长度 {len(d.get('token', ''))}")
    token = d.get("token", "")
    # 4. 令牌校验
    r = client.post("/api/access/check", json={"code": token})
    check("令牌校验有效", r.status_code == 200 and r.json()["valid"] is True)
    # 5. 无效令牌拒绝
    r = client.post("/api/access/check", json={"code": "fake-token"})
    check("无效令牌拒绝", r.status_code == 200 and r.json()["valid"] is False)
    # 6. 本人免密直通
    r = client.post("/api/access/owner")
    d = r.json()
    check("本人免密直通", r.status_code == 200 and "token" in d)
    owner_token = d.get("token", "")
    r = client.post("/api/access/check", json={"code": owner_token})
    check("本人令牌有效", r.status_code == 200 and r.json()["valid"] is True)
    # 7. 访问台页面可访问
    r = client.get("/access.html")
    check("访问台页面挂载", r.status_code == 200 and "J2026" in r.text and "访问台" in r.text)
    # 8. 原有查证接口不受影响
    r = client.post("/api/verify", json={"text": "手机整夜充电会严重损坏电池"})
    check("查证接口正常", r.status_code == 200 and r.json()["verdict"]["label"] == "不实")
    print("=" * 70)
    print(f"合计 {ok + fail} 项 ｜ 通过 {ok} ｜ 失败 {fail}")
    print("=" * 70)
    return 0 if fail == 0 else 1
if __name__ == "__main__":
    raise SystemExit(main())