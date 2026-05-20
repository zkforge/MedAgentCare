# MedAgentCare

MedAgentCare 是一个多 Agent 医疗咨询原型项目，代码包含交互式 CLI、FastAPI HTTP 入口、Swarm 路由框架、短期/长期记忆模块、Milvus Lite 医学知识库封装和 Docker 部署文件。

> 说明：本项目仅用于学习、研究和工程展示，不能替代医生诊断或治疗。

## 当前可验证状态

代码中可检查的模块：

- `src/medagentcare/main.py`：交互式命令行入口。
- `src/medagentcare/api.py`：FastAPI 入口，提供 `/health` 和 `/chat`。
- `src/medagentcare/swarm/`：LeadAgent、SwarmCoordinator、SharedContext 等多 Agent 协作骨架。
- `src/medagentcare/agents/`：ConsultationAgent、DiagnosticAgent、ResearchAgent 三类 Worker Agent。
- `src/medagentcare/core/`：LLM 客户端、Agent Loop、SkillRegistry、SkillLoader。
- `src/medagentcare/memory/`：短期记忆、Mem0 长期记忆、会话总结和熵管理模块。
- `src/medagentcare/knowledge/`：Milvus Lite 知识库封装和 txt 文档导入脚本。
- `.claude/skills/`：9 个 Skill 的 `SKILL.md` 元数据和可加载 `script/*.py` 实现。
- `Dockerfile` / `.dockerignore` / `.env.example`：容器部署基础文件。

当前限制：

- `examples/test_all.py` 含有历史字段和真实外部服务依赖，不能作为当前最终验收标准。
- 医疗知识库、LLM、Mem0、网络搜索依赖本地环境或外部服务，部署前必须显式配置。
- README 只记录可以从代码、配置或命令验证的状态；尚未验证的能力统一放入 TODO，不写成已验证结论。

更完整的待办项见 [TODO.md](TODO.md)。

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
├── examples/test_all.py           # 历史集成测试脚本，修复后再作为验收
└── TODO.md                        # 待完善项
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
```

## 本地运行

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

启动 CLI：

```bash
medagentcare
```

启动 FastAPI：

```bash
uvicorn medagentcare.api:app --host 0.0.0.0 --port 8000
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
uvicorn medagentcare.api:app --host 0.0.0.0 --port 8000
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
medagentcare-import-knowledge
```

`src/medagentcare/knowledge/data/*.db` 按当前策略视为本地生成产物，默认不纳入 Git，也不会进入 Docker build context。部署时需要在环境初始化阶段运行导入脚本，或通过 volume 挂载预生成的数据库。详见 `src/medagentcare/knowledge/data/README.md`。

## 验证状态

离线回归测试命令：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

该命令覆盖运行配置读取、FastAPI `/health`、Skill 发现、医疗安全约束，以及 `/chat` 在 mock Swarm 下的错误边界和 `enable_swarm=False` 参数传递。

基础编译检查命令：

```bash
python3 -m compileall -q src tests
```

上述检查不覆盖真实 LLM 调用、Mem0 连接、Milvus Lite 数据导入、网络搜索或 Docker 镜像运行。

尚未形成可重复的端到端验收测试，原因是当前环境缺少完整外部服务配置，且 `examples/test_all.py` 仍有历史漂移问题。端到端能力在补齐集成测试前，不在 README 中声明为已验证。
