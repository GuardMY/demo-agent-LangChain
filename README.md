# 🤖 LangChain Agent 智能助手

基于 **LangChain** 的多工具 AI 智能助手，支持 Web 交互和 CLI 命令行两种模式。内置 7 种 LLM 提供商、5 个实用工具、流式输出、会话隔离、安全防护，具备生产级特性。

**技术栈**: Python 3.12 / LangChain 1.3 / FastAPI / Docker / Redis

---

## ✨ 核心特性

- 🧠 **多 Agent 类型** — Conversational / ReAct / OpenAI Functions，自动路由
- 🔧 **5 个内置工具** — 计算器、搜索、天气、日期时间、文件操作（8 层安全防护）
- 🌊 **流式输出 (SSE)** — 逐 token 实时推送，前端闪烁光标 + 工具调用状态条
- 🔒 **五层安全** — 输入验证 / API 认证 / 速率限制 / CORS 管控 / 安全响应头
- 🏥 **健康检查** — 4 个端点（基础/详细/Liveness/Readiness），支持 K8s
- 📊 **结构化日志** — JSON/Console 双模式，请求追踪（X-Request-ID）
- 💬 **会话隔离** — 每个标签页独立会话，TTL 自动过期
- 📝 **Prompt 模板化** — 4 种角色 YAML 模板 + 变量插值 + 热加载
- 🛡️ **容错重试** — 指数退避 + 熔断器 + Fallback 链 + 超时控制
- 📚 **RAG 知识库** — TF-IDF 检索引擎，支持 txt/md/py/pdf
- 🖼️ **多模态输入** — 图片魔数验证 + GPT-4o / Claude Vision API
- 🐳 **Docker 一键部署** — 多阶段构建 + docker-compose (app + redis)
- 🔄 **CI/CD** — GitHub Actions 五阶段流水线 (lint → type → test → security → build)

---

## 🚀 快速开始

### 环境要求

- Python >= 3.11
- [可选] Docker & Docker Compose

### 本地运行

```bash
# 1. 克隆项目
git clone git@github.com:GuardMY/demo-agent-LangChain.git
cd demo-agent-LangChain

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，至少填入一个 LLM 提供商的 API Key

# 3. 安装依赖
make install

# 4. 启动服务
make run          # Web 模式: http://localhost:8000
# 或
python main.py --cli   # CLI 交互模式
```

### Docker 部署

```bash
# 生产模式
docker-compose -f deploy/docker-compose.yml up -d

# 开发模式（源码挂载 + 热重载）
docker-compose -f deploy/docker-compose.yml --profile dev up app-dev

# 验证
curl http://localhost:8000/api/health
```

---

## 🛠️ 可用命令

| 命令 | 说明 |
|------|------|
| `make install` | 安装全部依赖 |
| `make lint` | ruff 代码检查 |
| `make format` | ruff 自动格式化 |
| `make type-check` | mypy 类型检查 |
| `make test` | 运行测试 (78 个用例) |
| `make test-cov` | 测试 + HTML 覆盖率报告 |
| `make security` | bandit 安全扫描 |
| `make build` | Docker 生产构建 |
| `make run` | 启动开发服务器 |
| `make clean` | 清理所有缓存 |

---

## 📡 API 端点总览（29 个）

### 聊天
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/chat` | 非流式聊天 |
| POST | `/api/chat/stream` | 流式聊天 (SSE) |

### 会话管理
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/session/new` | 创建新会话 |
| GET | `/api/session/info` | 会话详情 |
| GET | `/api/sessions` | 活跃会话列表 |
| POST | `/api/reset` | 重置会话记忆 |
| GET/POST | `/api/config` | 获取/更新配置 |

### 健康检查
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 基础健康检查 |
| GET | `/api/health/detailed` | 详细检查 (含 LLM 连通性) |
| GET | `/api/health/live` | K8s Liveness Probe |
| GET | `/api/health/ready` | K8s Readiness Probe |

### 其他
- **工具管理**: `GET/POST /api/tools`, `/api/tools/{name}/enable|disable`, `/api/tools/cache/clear`
- **RAG 知识库**: `GET /api/rag/stats`, `POST /api/rag/search`, `POST /api/rag/ingest`
- **多 Agent**: `GET /api/agents`, `POST /api/agents/route`
- **结构化输出**: `GET /api/schemas`, `GET /api/schemas/{name}`
- **Prompt**: `GET /api/prompts`, `GET /api/prompts/{name}`, `POST /api/prompts/reload`
- **配置**: `GET /api/settings`, `GET /api/providers`

---

## 🧰 内置工具

| 工具 | 权限 | 超时 | 缓存 | 说明 |
|------|------|------|------|------|
| `calculator` | READ | 5s | 60s | 安全 eval，支持 19 种数学函数 |
| `web_search` | NETWORK | 15s | 120s | DuckDuckGo 搜索 |
| `get_weather` | NETWORK | 10s | 600s | 模拟 + OpenWeatherMap 真实 API |
| `get_datetime` | READ | 3s | 30s | 日期时间查询 |
| `file_operations` | SYSTEM | 15s | — | 文件读写，8 层安全防护 |

---

## 🔐 安全特性

```
Layer 1: 输入验证   — Pydantic 字段校验（非空/长度/白名单）
Layer 2: API 认证   — HTTPBearer + Query ?api_key=
Layer 3: 速率限制   — slowapi / 简易计数器回退
Layer 4: CORS 管控  — 可配置域名白名单
Layer 5: 安全响应头 — X-Content-Type-Options, X-Frame-Options, XSS, Referrer
```

---

## 📂 项目结构

```
├── agent/              # Agent 核心 (基类 + 流式 + 容错)
├── deploy/             # Dockerfile + docker-compose.yml
├── docs/               # 改进文档
├── prompts/            # YAML Prompt 模板 (4 种角色)
├── static/             # 前端聊天界面
├── tests/              # 78 个测试用例
├── tools/              # 5 个工具（基类 + 注册表 + 缓存）
├── main.py             # 应用入口 (Web / CLI)
├── web_app.py          # FastAPI 应用 (29 个端点)
├── session_manager.py  # 会话隔离管理
├── resilience.py       # 重试 / 熔断 / Fallback
├── logger.py           # 结构化日志
├── health_check.py     # 健康检查引擎
├── rag.py              # RAG 检索引擎
├── multi_agent.py      # 多 Agent 协作调度
├── multimodal.py       # 多模态图片处理
├── structured_output.py # 结构化输出 Schema
├── config_loader.py    # pydantic-settings 配置
├── prompt_manager.py   # Prompt 模板引擎
├── Makefile            # 11 个开发命令
└── pyproject.toml      # ruff + mypy + pytest 配置
```

---

## 🧪 测试

```bash
make test        # 运行全部 78 个测试
make test-cov    # 带 HTML 覆盖率报告
```

测试覆盖：安全（11 用例）、日志（6）、计算器（24）、工具（9）、会话（13）、API 集成（15） — 全部通过。

---

## 🌍 支持的 LLM 提供商

| 提供商 | 默认模型 |
|--------|----------|
| OpenAI | gpt-4, gpt-4-turbo, gpt-3.5-turbo |
| Azure OpenAI | 自定义部署名 |
| DeepSeek | deepseek-chat, deepseek-coder |
| 智谱 AI | glm-4, glm-3-turbo |
| Moonshot | moonshot-v1-8k, moonshot-v1-32k |
| Ollama | llama2, llama3, mistral, qwen |
| 自定义 API | 兼容 OpenAI 格式的任意 API |

---

## 📄 License

MIT

---

> 🤖 Generated with [Claude Code](https://claude.com/claude-code)
