"""交付收尾：README 归位到项目根目录，清理临时脚本。"""
import os
import shutil
BACKEND = r"D:\jqw33\Documents\68\backend"
ROOT = r"D:\jqw33\Documents\68"
# README 归位
src = os.path.join(BACKEND, "README.md")
dst = os.path.join(ROOT, "README.md")
if os.path.exists(src):
    shutil.move(src, dst)
    print("README ->", dst)
# 清理临时脚本
for name in ("fix_and_test.py", "render_check.py", "launch_service.py", "todo.md"):
    path = os.path.join(BACKEND, name)
    if os.path.exists(path):
        try:
            os.remove(path)
            print("removed:", name)
        except OSError as exc:
            print("remove failed:", name, exc)
print("--- 项目根目录 ---")
print(sorted(os.listdir(ROOT)))
print("--- backend ---")
print(sorted(os.listdir(BACKEND)))