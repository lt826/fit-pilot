"""启动 API 服务（PyCharm 里直接右键运行这个文件即可）。

用法: .venv/Scripts/python.exe scripts/run_server.py
访问: http://127.0.0.1:8000/docs （FastAPI 自带接口文档）
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn  # noqa: E402

if __name__ == "__main__":
    uvicorn.run("app.api.server:app", host="127.0.0.1", port=8000, reload=False)
