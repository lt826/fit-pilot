# 后端镜像：Python 3.12 + uv 锁定依赖
FROM python:3.12-slim

# 国内网络构建加速（基础镜像层走 Docker 配置的镜像加速，pip 走清华源）
ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai

RUN pip install --no-cache-dir uv

WORKDIR /app

# 先装依赖再拷代码：依赖层缓存不被代码改动打断
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY scripts ./scripts
COPY data ./data

# 不安装项目本身，用 PYTHONPATH 直接跑（pyproject 无打包配置，最简可靠）
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app

EXPOSE 8000
CMD ["uvicorn", "app.api.server:app", "--host", "0.0.0.0", "--port", "8000"]
