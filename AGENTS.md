# MedAgentCare Agent Onboarding

本文档给后续 Codex 或代码 Agent 使用。修改仓库前先读这里，再进入具体文件；内容只记录容易误判的项目事实和验证命令。

## 工作原则

- 默认用中文沟通和解释代码变更。
- 开发前先运行 `git status --short`，确认已有改动；不要回滚用户未提交内容。
- 只改当前任务直接相关的文件。发现无关历史问题时在回复中说明，不顺手重构。
- 不把 `README.md` 写成阶段汇报；README 只能声明代码、配置或命令可验证的事实。
- 医疗输出相关改动必须保留安全边界：不能明确诊断，不能给具体处方剂量，高危症状必须建议就医。
- 当前测试主要是离线单元/集成替身测试；`/chat` 和 `/chat/stream` 的真实 LLM、Mem0、Milvus Lite、外网搜索链路需要单独 smoke test，不能用 `/health` 代替。

## 常用命令

```bash
# 安装后端依赖
uv sync

# 离线回归测试，不依赖真实 LLM、Mem0、Milvus 或外网搜索
uv run python -m unittest discover -s tests

# 单个测试文件
uv run python -m unittest tests.test_api_offline

# 基础编译检查
uv run python -m compileall -q src tests .agents/skills

# 本地 CLI
uv run medagentcare

# FastAPI 后端
uv run uvicorn medagentcare.api:app --host 0.0.0.0 --port 8000

# 医学知识库导入
uv run medagentcare-import-knowledge
```

前端在 `frontend/` 下：

```bash
npm ci
npm run build
npm run dev
```

Docker Compose：

```bash
docker compose config --quiet
docker compose up -d
docker compose logs -f api
docker compose logs -f frontend
docker compose down
```

GitHub Actions 的后端 CI 使用 Python 3.12、`uv sync --locked --no-dev`，跳过 CUDA/Triton/NVIDIA 包后安装 CPU-only `torch==2.12.0+cpu`，再运行 `unittest` 和 `compileall`；前端 CI 使用 Node 22、`npm ci`、`npm run build`。

## 运行入口和 API 边界

- `src/medagentcare/main.py` 是交互式 CLI，调用 `process_with_swarm()`。
- `src/medagentcare/api.py` 是 FastAPI 入口，当前提供 `/health`、`/chat`、`/chat/stream`、`/sessions*`、`/memory*` 等接口。
- 前端演示页在 `frontend/`，默认调用 `VITE_API_BASE_URL` 指向的后端，并使用 `/chat/stream`。不要把 SSE 接口当普通 JSON 响应处理。
- `/health` 只返回 API 进程和基础配置状态，例如 LLM/Mem0 是否配置；不代表真实咨询链路可用。
- `/chat/stream` 会持续发送 `start`、`progress`、`stream_delta`、`heartbeat`、`result`、`done`、`error` 等 SSE 事件。代理或网关部署时要避免响应体缓冲，并给 LLM/检索链路留足超时。

## 核心架构

- `src/medagentcare/swarm/swarm_coordinator.py` 是总入口和路由器，不是通用任务编排器。它负责问诊前置拦截、快速咨询路径、LeadAgent 路由、Swarm 协作、记忆检索和进度事件。
- `InterviewAgent` 不在 `worker_pool` 中；它用于症状报告的多轮信息采集。症状问诊状态由 `src/medagentcare/swarm/interview_state.py` 建模，并可随会话恢复。
- Swarm 的 Worker 池当前是 `ConsultationAgent`、`DiagnosticAgent`、`ResearchAgent` 三类专业 Agent。复杂问题由 `LeadAgent` 拆分后写入 `SharedContext` 并并行执行。
- 简短、常见、无高危信号的症状咨询可能走快速 `ConsultationAgent` 路径；研究、诊断、高危、长文本问题不会走该路径。
- `src/medagentcare/core/agent_loop.py` 负责 Think-Act-Observe 循环、工具调用、短期记忆写入、约束验证和自动修复；默认工具调用次数有上限。
- `src/medagentcare/core/tracing.py` 提供请求级 trace/progress 回调；API 会把选定进度转成用户可见 SSE 文本，不能泄露原始异常或内部标识。
- `src/medagentcare/response_sections.py` 负责从模型回答中抽取正文、建议和免责声明。修改输出格式时同步更新相关测试。

## Skills 和知识库

- Skill 自动发现优先读取 `.agents/skills`，保留 `.claude/skills` fallback。新增、删除或改名 Skill 时同步检查 `tests/test_skill_discovery.py`。
- 当前仓库内有 9 个可发现 Skill：`analyze-symptoms`、`assess-risk`、`clinical-guideline`、`deep-research`、`disease-code`、`recommend-lifestyle`、`search-history`、`search-knowledge`、`search-similar-cases`。
- Skill 目录通常包含 `SKILL.md` 和 `script/*.py`；两者的名称、入口函数、参数语义要保持一致。
- `.agents/skills/skill_helpers.py` 负责项目路径注入、统一 success/failure 返回、本地知识库 fallback 和文本格式化；不要在各 Skill 中重复实现这些通用逻辑。
- `src/medagentcare/knowledge/data/documents/*.txt` 是版本化知识源；Milvus Lite 的 `*.db` 是生成产物，默认不进 Git，也不进 Docker build context。

## 记忆和持久化

- `ShortTermMemory` 保存会话内历史和问诊状态，默认内存存储，也保留 Redis fallback。
- `ConversationStore` 支撑前端最近会话列表和 API 重启后的可见对话恢复；默认路径来自 `MEDAGENTCARE_SESSIONS_DIR`，未配置时在 `.medagentcare/sessions`。
- `LocalHealthMemory` 是本地长期健康记忆后端；默认路径来自 `MEDAGENTCARE_MEMORY_DIR`，未配置时在 `.medagentcare/memory`。
- `LongTermMemory` 基于 Mem0；未配置 `MEM0_API_KEY` 时应降级为 disabled。
- 环境变量只启用记忆后端能力；每个 `/chat` 或 `/chat/stream` 请求仍需通过 `memory.enabled` 显式选择是否读写长期记忆。
- 本地持久化目录 `.medagentcare/` 属于运行产物，不应提交。

## 配置和部署

- 运行配置集中在 `src/medagentcare/config.py`，从 `.env` 和环境变量读取。默认 LLM 是 OpenAI-compatible 接口：`LLM_MODEL_NAME=qwen3.6-plus`，`LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1`。
- `.env.example` 是示例，不放真实密钥。新增运行时配置时同步更新 `config.py`、`.env.example`、`compose.yaml` 和 README 中可验证命令。
- `compose.yaml` 同时启动后端 API 和 Vite 前端，API 挂载 `/data` 与本地 `.medagentcare/memory`、`.medagentcare/sessions`，前端默认访问 `http://localhost:8000`。
- 前端跨域由 `MEDAGENTCARE_CORS_ORIGINS` 控制；生产环境不要使用 `*`。

## 安全和测试重点

- 医疗安全约束在 `src/medagentcare/constraints/*.yaml`、`src/medagentcare/constraints/validator.py` 和 `src/medagentcare/validation/auto_fixer.py` 中共同生效。
- 改动诊断、处方、急症提醒、免责声明、问诊路由或 SSE 输出时，至少运行相关离线测试和 `compileall`。
- 改动前端时运行 `npm run build`；改动 Compose/Docker 时运行 `docker compose config --quiet`。
- 旧的大型端到端集成脚本已移除；新增可重复验收请放入 `tests/` 或专门 `scripts/`，并明确外部依赖。
