# -*- coding: utf-8 -*-
"""构建干净的发布目录 deploy/（不含 .venv / 缓存 / 日志）"""
import os
import shutil

SRC = os.path.dirname(os.path.abspath(__file__))
DST = os.path.join(SRC, "deploy")

EXCLUDE_DIRS = {".venv", "__pycache__", ".git", "backend"}
EXCLUDE_FILES = {"history.json", "app.db", "usage_log.jsonl", "usage_state.json", ".usage_cleaned"}
EXCLUDE_SUFFIX = {".log", ".pyc", ".pyo"}


def ignore(path, names):
    out = set()
    for n in names:
        full = os.path.join(path, n)
        if os.path.isdir(full):
            if n in EXCLUDE_DIRS:
                out.add(n)
        else:
            if n in EXCLUDE_FILES or os.path.splitext(n)[1] in EXCLUDE_SUFFIX:
                out.add(n)
    return out


def copy(src, dst):
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=ignore)
    return sum(len(f) for _, _, f in os.walk(dst)), \
        sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(dst) for f in fs)


if __name__ == "__main__":
    os.makedirs(DST, exist_ok=True)
    for part in ("backend", "frontend"):
        n, size = copy(os.path.join(SRC, part), os.path.join(DST, part))
        print(f"{part:9s} {n:4d} files  {size/1024/1024:.2f} MB")
    shutil.copy(os.path.join(SRC, "backend", "requirements.txt"),
                os.path.join(DST, "requirements.txt"))
    total = sum(os.path.getsize(os.path.join(r, f))
                for r, _, fs in os.walk(DST) for f in fs)
    print(f"{'TOTAL':9s}      {total/1024/1024:.2f} MB")
