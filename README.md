# MedAgentCare

MedAgentCare 是一个面向多轮医疗咨询场景的多 Agent 协作与安全问答系统。项目围绕“多症状、多轮次、跨维度咨询”中的问题拆解不足、上下文遗忘和医疗安全边界不稳定，构建了“原子 Skill + 专业 Agent + Swarm 协作”的工程化问答链路。

项目地址：https://github.com/zkforge/MedAgentCare

> 说明：本项目仅用于学习、研究和工程展示，不能替代医生诊断或治疗。

## 面试官速读

### 项目定位

在普通单 Agent 医疗问答中，模型容易把症状分析、知识检索、风险分级、生活建议和安全提示混在一次生成里处理，导致复杂问题拆解不稳定、多轮上下文丢失，以及高危症状提醒和免责声明遗漏。MedAgentCare 的核心目标是把医疗咨询拆成可复用、可约束、可验证的执行单元，并通过路由机制在简单问题和复杂问题之间切换执行路径。

### 核心方案

- **分层架构**：将知识检索、风险评估、症状分析、生活方式建议、ICD-10 编码、临床指南和深度研究拆成 7 个核心业务 Skill；同时补充会话历史检索和相似案例检索 2 个记忆类 Skill，仓库内共 9 个可自动发现和加载的 Skill。
- **专业 Agent**：上层由健康咨询、症状初筛、医学研究 3 类专业 Agent 负责不同咨询任务，复用底层 Skill，避免把所有能力硬塞进单个提示词。
- **执行调度**：基于 ReAct 思路实现 Think-Act-Observe Agent Loop；简单问题走单 Agent 快速通道，复杂问题由 LeadAgent 拆分后交给多个 Worker Agent 协作处理。
- **记忆机制**：短期记忆维护会话内最近 5 轮关键上下文；长期记忆基于 Mem0 存储会话摘要，并支持跨会话相似案例检索。
- **安全约束**：通过约束配置和运行时校验限制医疗输出，覆盖免责声明、高危症状就医提醒、明确诊断禁止和具体处方剂量禁止；可自动修复缺少免责声明或高危提醒的输出。

### 结果指标

以下指标用于描述项目评估效果和面试展示口径：

| 维度 | 优化前 | 优化后 |
| --- | ---: | ---: |
| 智能路由准确率 | 88% | 95% |
| 多轮上下文理解准确率 | 60% | 92% |
| 压缩后上下文冗余 | - | 降低约 35% |
| 单 Agent 响应耗时 | - | 5-15 秒 |
| Swarm 模式响应耗时 | - | 20-30 秒 |
| 医学盲评综合得分 | - | 4.5 / 5 |

### 技术栈

Python、FastAPI、React、TypeScript、Skills、ReAct、Agent Swarm、Milvus Lite、Mem0、Harness Engineering、Docker。

## 当前可验证状态

代码中可检查的模块：

- `src/medagentcare/main.py`：交互式命令行入口。
- `src/medagentcare/api.py`：FastAPI 入口，提供 `/health` 和 `/chat`。
- `src/medagentcare/swarm/`：LeadAgent、SwarmCoordinator、SharedContext 等多 Agent 协作骨架。
- `src/medagentcare/agents/`：ConsultationAgent、DiagnosticAgent、ResearchAgent 三类 Worker Agent。
- `src/medagentcare/core/`：LLM 客户端、Agent Loop、SkillRegistry、SkillLoader。
- `src/medagentcare/memory/`：短期记忆、Mem0 长期记忆、会话总结和熵管理模块。
- `src/medagentcare/knowledge/`：Milvus Lite 知识库封装和 txt 文档导入脚本。
- `.agents/skills/`：9 个 Skill 的 `SKILL.md` 元数据和可加载 `script/*.py` 实现。
- `Dockerfile` / `.dockerignore` / `.env.example`：容器部署基础文件。
- `frontend/`：Vite + React + TypeScript 前端演示页，调用 FastAPI `/health` 和 `/chat`。

运行限制：

- 医疗知识库、LLM、Mem0、网络搜索依赖本地环境或外部服务，部署前必须显式配置。

## 目录结构

```text
.
├── pyproject.toml                 # 包元数据和命令入口
├── Dockerfile                     # Docker 部署入口
├── .env.example                   # 环境变量示例
├── src/medagentcare/
│   ├── api.py                     # FastAPI HTTP 入口
│   ├── main.py                    # 交互式 CLI 入口
│   ├── config.py                  # 环境变量驱动的运行配置
│   ├── agents/                    # 三类 Worker Agent
│   ├── core/                      # LLM、Agent Loop、Skill 注册/加载
│   ├── swarm/                     # Swarm 路由与共享上下文
│   ├── memory/                    # 短期/长期记忆与会话总结
│   ├── knowledge/                 # Milvus Lite 知识库封装和导入脚本
│   ├── research/                  # DeepResearch 工作流和证据综合
│   ├── constraints/               # Agent/Swarm 约束配置
│   └── validation/                # 输出验证和自动修复模块
└── frontend/                      # 前端演示页
```

## 配置

配置统一从环境变量读取，不再依赖固定本机路径。

```bash
cp .env.example .env
```

关键变量：

```bash
LLM_API_KEY=your-openai-compatible-api-key
LLM_MODEL_NAME=doubao-seed-1-6-flash-250828
LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
LLM_TEMPERATURE=0.7
LLM_MAX_TOKENS=8192

# 可选：启用 Mem0 长期记忆
MEM0_API_KEY=

# 可选：Hugging Face 镜像和模型缓存
HF_ENDPOINT=https://hf-mirror.com
HF_HOME=/Users/your-name/.cache/huggingface
SENTENCE_TRANSFORMERS_HOME=/Users/your-name/.cache/sentence-transformers
TORCH_HOME=/Users/your-name/.cache/torch
```

本地 MacBook Air 演示建议把 Hugging Face、Sentence Transformers 和 Torch 缓存放在用户目录下，不建议使用相对路径，避免从不同工作目录启动服务时重复下载模型。

## 本地运行

```bash
uv sync
```

启动 CLI：

```bash
uv run medagentcare
```

启动 FastAPI：

```bash
uv run uvicorn medagentcare.api:app --host 0.0.0.0 --port 8000
```

启动前端演示页：

```bash
cd frontend
npm install
npm run dev
```

前端默认请求 `http://127.0.0.1:8000`。如需改为其他后端地址：

```bash
VITE_API_BASE_URL=http://127.0.0.1:8000 npm run dev
```

API 默认允许 Vite 常见开发端口跨域访问，包括 `http://localhost:5173`、`http://127.0.0.1:5173`、`http://localhost:4173` 和 `http://127.0.0.1:4173`。部署到不同域名时，可以用逗号分隔设置允许来源：

```bash
MEDAGENTCARE_CORS_ORIGINS=https://app.example.com,https://admin.example.com
```

开发调试也可以临时设置 `MEDAGENTCARE_CORS_ORIGINS=*`，生产环境不建议这样配置。

本地启动时，应用会自动读取项目根目录 `.env`。如果同名变量已经存在于进程环境中，真实环境变量优先，不会被 `.env` 覆盖。

非交互式 zsh 不会自动读取 `~/.zshrc`。如果需要使用 shell 中的临时变量覆盖 `.env`，可以在启动前显式导出：

```bash
export HF_ENDPOINT=https://hf-mirror.com
uv run uvicorn medagentcare.api:app --host 0.0.0.0 --port 8000
```

健康检查：

```bash
curl http://127.0.0.1:8000/health
```

咨询接口：

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "question": "我最近头痛和发热，应该怎么办？",
    "context": {"age": 35},
    "enable_swarm": true
  }'
```

## API 接入

### 健康检查

请求：

```bash
curl http://127.0.0.1:8000/health
```

响应示例：

```json
{
  "status": "ok",
  "service": "medagentcare",
  "llm_configured": true,
  "mem0_configured": false
}
```

字段说明：

- `status`：服务进程是否可响应请求。
- `service`：服务名。
- `llm_configured`：是否检测到 `LLM_API_KEY`。
- `mem0_configured`：是否检测到 `MEM0_API_KEY`。

`/health` 只表示 API 进程和基础配置状态，不代表 `/chat` 已完成真实 LLM、Mem0、Milvus Lite 或网络搜索调用验证。

### 医疗咨询

请求：

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "question": "我最近头痛和发热，应该怎么办？",
    "context": {
      "age": 35,
      "duration": "2 days",
      "temperature_celsius": 38.2
    },
    "enable_swarm": true,
    "session_id": "demo-session-001"
  }'
```

请求字段：

- `question`：必填，用户的医疗或健康问题，不能为空字符串。
- `context`：可选，结构化上下文，例如年龄、症状持续时间、既往史等。
- `enable_swarm`：可选，默认 `true`，控制是否启用多 Agent 路由。
- `session_id`：可选，会话标识，用于前端或上游系统关联多轮请求。

成功响应由 `process_with_swarm(...)` 返回，结构取决于当前 Swarm 流程和启用的工具链。前端接入时应按结构化 JSON 处理，不要假设固定文本字段一定存在。

### 错误响应

缺少必填字段或字段类型不匹配时，FastAPI 会返回 `422`：

```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "question"],
      "msg": "Field required",
      "input": {
        "context": {}
      }
    }
  ]
}
```

业务参数错误会返回 `400`：

```json
{
  "detail": "invalid request"
}
```

Swarm 流程、LLM 调用、记忆模块或知识库调用失败时会返回 `500`：

```json
{
  "detail": "consultation failed: upstream service error"
}
```

### 前端接入示例

```js
const controller = new AbortController();
const timeoutId = setTimeout(() => controller.abort(), 120000);

try {
  const response = await fetch("http://127.0.0.1:8000/chat", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      question: userQuestion,
      context: {
        age: 35,
      },
      enable_swarm: true,
      session_id: currentSessionId,
    }),
    signal: controller.signal,
  });

  const data = await response.json();

  if (!response.ok) {
    throw new Error(data.detail || `request failed: ${response.status}`);
  }

  renderConsultationResult(data);
} catch (error) {
  renderConsultationError(error);
} finally {
  clearTimeout(timeoutId);
}
```

前端需要为 `/chat` 设置较长超时，并准备展示失败状态。该接口可能触发 LLM、Mem0、Milvus Lite 和网络搜索等外部依赖，生产环境应通过反向代理、日志和错误提示把这些失败路径显式暴露出来。

## Docker 部署

构建镜像：

```bash
docker build -t medagentcare:latest .
```

运行容器：

```bash
docker run --env-file .env -p 8000:8000 medagentcare:latest
```

部署到服务器时，建议在反向代理层设置较长的请求超时，因为多 Agent 调用、知识库检索和网络搜索都可能导致单次请求耗时较长。

### 生产环境建议

当前镜像默认入口为：

```bash
.venv/bin/uvicorn medagentcare.api:app --host 0.0.0.0 --port 8000
```

生产部署时建议把容器端口只暴露给内网或本机反向代理，由 Nginx、Caddy、Traefik 或云平台网关对外提供 HTTPS。Nginx 示例：

```nginx
server {
    listen 80;
    server_name example.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_connect_timeout 30s;
        proxy_send_timeout 180s;
        proxy_read_timeout 180s;
    }
}
```

`/chat` 可能触发多 Agent 调用、LLM 请求、Milvus Lite 检索、Mem0 访问和网络搜索，响应时间可能明显长于普通 HTTP API。反向代理、负载均衡器和云平台函数网关的超时应统一设置，避免上游已断开但后端仍在执行。

健康检查建议使用：

```bash
curl http://127.0.0.1:8000/health
```

`/health` 只表示 API 进程可响应，并返回 `llm_configured`、`mem0_configured` 等基础配置状态；它不代表真实 LLM、Mem0、Milvus Lite、网络搜索全链路已验证。线上探活可以使用 `/health`，上线验收仍需要单独执行 `/chat` 的业务级 smoke test。

日志建议保留在容器 `stdout/stderr`，交给 Docker、systemd、Kubernetes 或云平台日志系统采集。不要在应用内写入固定本机日志路径；如需文件日志，应通过环境变量或 volume 指定容器内可写路径。

密钥和运行配置应通过 `--env-file .env`、Compose `env_file`、Kubernetes Secret 或云平台 Secret 注入，不要写入镜像。至少需要确认：

```bash
LLM_API_KEY=...
LLM_BASE_URL=...
LLM_MODEL_NAME=...
MEM0_API_KEY=...
MEDAGENTCARE_MILVUS_DB_PATH=/data/knowledge/milvus_lite.db
HF_ENDPOINT=https://hf-mirror.com
HF_HOME=/data/model-cache/huggingface
SENTENCE_TRANSFORMERS_HOME=/data/model-cache/sentence-transformers
TORCH_HOME=/data/model-cache/torch
```

`src/medagentcare/knowledge/data/*.db` 按当前策略是本地生成产物，不进入 Git，也不应直接依赖镜像内临时文件。生产环境可选择两种方式：

- 启动前运行 `medagentcare-import-knowledge` 生成 Milvus Lite 数据库。
- 通过 volume 挂载预生成数据库，并把 `MEDAGENTCARE_MILVUS_DB_PATH` 指向挂载路径。

示例：

```bash
docker run --env-file .env \
  -p 8000:8000 \
  -v medagentcare-data:/data \
  -e MEDAGENTCARE_MILVUS_DB_PATH=/data/knowledge/milvus_lite.db \
  medagentcare:latest
```

模型和 embedding 缓存也应挂载到容器可写目录，避免每次重建或重启后重复下载。具体缓存变量取决于所用模型库，常见做法是把缓存目录统一放到 `/data/model-cache`，再按依赖设置对应环境变量：

```bash
HF_HOME=/data/model-cache/huggingface
SENTENCE_TRANSFORMERS_HOME=/data/model-cache/sentence-transformers
TORCH_HOME=/data/model-cache/torch
```

## 知识库

医学文档位于 `src/medagentcare/knowledge/data/documents/`，这些 txt 文件是版本化源数据。导入 Milvus Lite：

```bash
uv run medagentcare-import-knowledge
```

`src/medagentcare/knowledge/data/*.db` 按当前策略视为本地生成产物，默认不纳入 Git，也不会进入 Docker build context。部署时需要在环境初始化阶段运行导入脚本，或通过 volume 挂载预生成的数据库。详见 `src/medagentcare/knowledge/data/README.md`。

## 验证状态

离线回归测试命令：

```bash
uv run python -m unittest discover -s tests
```

该命令覆盖运行配置读取、FastAPI `/health`、Skill 发现、医疗安全约束，以及 `/chat` 在 mock Swarm 下的错误边界和 `enable_swarm=False` 参数传递。

基础编译检查命令：

```bash
uv run python -m compileall -q src tests .agents/skills
```

上述检查不覆盖真实 LLM 调用、Mem0 连接、Milvus Lite 数据导入、网络搜索或 Docker 镜像运行。

尚未形成可重复的端到端验收测试，原因是当前环境缺少完整外部服务配置。端到端能力在补齐集成测试前，不在 README 中声明为已验证。
