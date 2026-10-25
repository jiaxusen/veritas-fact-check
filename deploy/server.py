# -*- coding: utf-8 -*-
"""云托管启动入口：监听 $PORT，绑定 0.0.0.0"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE / "backend"

sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="info")
