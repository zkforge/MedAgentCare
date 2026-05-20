# MedAgentCare

MedAgentCare 是一个多 Agent 医疗咨询原型项目，当前代码包含交互式 CLI、Swarm 路由框架、短期/长期记忆模块、Milvus Lite 医学知识库封装，以及本轮新增的 FastAPI HTTP 入口和 Docker 部署文件。

> 说明：本项目仅用于学习、研究和工程展示，不能替代医生诊断或治疗。

## 当前真实状态

已具备：

- `src/medagentcare/main.py`：交互式命令行入口。
- `src/medagentcare/api.py`：FastAPI 入口，提供 `/health` 和 `/chat`。
- `src/medagentcare/swarm/`：LeadAgent、SwarmCoordinator、SharedContext 等多 Agent 协作骨架。
- `src/medagentcare/agents/`：ConsultationAgent、DiagnosticAgent、ResearchAgent 三类 Worker Agent。
- `src/medagentcare/core/`：LLM 客户端、Agent Loop、SkillRegistry、SkillLoader。
- `src/medagentcare/memory/`：短期记忆、Mem0 长期记忆、会话总结和熵管理模块。
- `src/medagentcare/knowledge/`：Milvus Lite 知识库封装和 txt 文档导入脚本。
- `.claude/skills/`：9 个 Skill 的 `SKILL.md` 元数据和可加载 `script/*.py` 实现。
- `Dockerfile` / `.dockerignore` / `.env.example`：容器部署基础文件。

尚未完成或需要修复：

- `examples/test_all.py` 含有历史字段和真实外部服务依赖，暂时不能作为最终验收标准。
- 医疗知识库、LLM、Mem0、网络搜索都依赖本地环境或外部服务，部署前必须显式配置。

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
├── examples/test_all.py           # 历史集成测试脚本，当前需修复后再作为验收
└── TODO.md                        # 未改动完善项
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

## 知识库

医学文档位于 `src/medagentcare/knowledge/data/documents/`，这些 txt 文件是版本化源数据。导入 Milvus Lite：

```bash
medagentcare-import-knowledge
```

`src/medagentcare/knowledge/data/*.db` 按当前策略视为本地生成产物，默认不纳入 Git，也不会进入 Docker build context。部署时需要在环境初始化阶段运行导入脚本，或通过 volume 挂载预生成的数据库。详见 `src/medagentcare/knowledge/data/README.md`。

## 验证记录

本轮已做的轻量验证：

```bash
python3 -m compileall -q .
```

该检查通过。完整端到端测试暂未运行，因为当前环境缺少完整项目依赖和真实 LLM/API 配置，且 `examples/test_all.py` 仍有历史漂移问题。
