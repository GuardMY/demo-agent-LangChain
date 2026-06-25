# ============================================================
# Makefile — 本地开发命令（与 CI 保持一致）
# ============================================================

.PHONY: help lint format type-check test test-cov security build build-dev up down run clean

# 默认目标
help:
	@echo "LangChain Agent — 可用命令:"
	@echo "  make install    安装依赖"
	@echo "  make lint       ruff 代码检查"
	@echo "  make format     ruff 代码格式化"
	@echo "  make type-check mypy 类型检查"
	@echo "  make test       运行测试"
	@echo "  make test-cov   测试 + 覆盖率报告"
	@echo "  make security   bandit 安全扫描"
	@echo "  make build      Docker 构建 (生产)"
	@echo "  make build-dev  Docker 构建 (开发)"
	@echo "  make up         启动服务 (docker-compose)"
	@echo "  make down       停止服务"
	@echo "  make run        启动服务 (uvicorn)"
	@echo "  make clean      清理缓存文件"

# ---- 安装 ----
install:
	pip install -r requirements.txt
	pip install ruff mypy pytest pytest-asyncio pytest-cov bandit

# ---- 代码质量 ----
lint:
	ruff check .

format:
	ruff format .

format-check:
	ruff format --check .

type-check:
	mypy . --ignore-missing-imports --exclude '.venv/'

# ---- 测试 ----
test:
	pytest tests/ -v

test-cov:
	pytest tests/ --cov=. --cov-report=html --cov-report=term -v

# ---- 安全 ----
security:
	bandit -r . -x .venv/,tests/

# ---- Docker ----
build:
	docker build -f deploy/Dockerfile --target production -t langchain-agent:latest .

build-dev:
	docker build -f deploy/Dockerfile --target development -t langchain-agent:dev .

# ---- Docker Compose ----
up:
	docker-compose -f deploy/docker-compose.yml up -d

down:
	docker-compose -f deploy/docker-compose.yml down

# ---- 运行 ----
run:
	uvicorn web_app:app --host 0.0.0.0 --port 8000 --reload

# ---- 清理 ----
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "htmlcov" -exec rm -rf {} + 2>/dev/null || true
	rm -f .coverage coverage.xml bandit-report.json
