# ============================================================
# LangChain Agent 智能助手 - Dockerfile
# 多阶段构建：最小化最终镜像体积
# ============================================================

# ---- 阶段 1: 基础依赖 ----
FROM python:3.12-slim AS base

# 防止 .pyc 文件生成 + 强制 stdout/stderr 无缓冲
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 安装系统依赖（健康检查用 + 编译工具）
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ---- 阶段 2: 依赖安装 ----
FROM base AS builder

# 安装构建工具
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ make \
    && rm -rf /var/lib/apt/lists/*

# 先复制依赖文件（利用 Docker 层缓存）
COPY requirements.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# ---- 阶段 3: 生产运行 ----
FROM base AS production

# 创建非 root 用户
RUN groupadd -r appuser && useradd -r -g appuser -s /bin/bash appuser

# 从 builder 阶段复制已安装的包
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# 复制应用代码
COPY --chown=appuser:appuser . .

# 切换到非 root 用户
USER appuser

# 健康检查（使用 liveness 端点）
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -sf http://localhost:8000/api/health/live || exit 1

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["python", "main.py", "--web"]


# ---- 阶段 4: 开发模式 ----
FROM builder AS development

# 安装开发工具
RUN pip install --no-cache-dir \
    pytest pytest-asyncio pytest-cov \
    black ruff mypy

COPY . .

# 暴露端口 + 热重载
EXPOSE 8000
CMD ["uvicorn", "web_app:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
