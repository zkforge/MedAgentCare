# 🩺 MedAgentCare

面向多轮医疗咨询的多 Agent 协作与安全问答系统。

![Python](https://img.shields.io/badge/Python-3.11+-3776AB)
![FastAPI](https://img.shields.io/badge/FastAPI-API-009688)
![React](https://img.shields.io/badge/React-Frontend-61DAFB)
![TypeScript](https://img.shields.io/badge/TypeScript-Frontend-3178C6)
![Docker](https://img.shields.io/badge/Docker-Ready-2496ED)
![uv](https://img.shields.io/badge/uv-package%20manager-5C4EE5)

MedAgentCare 面向多症状、多轮次、信息不完整的医疗咨询场景，构建“问诊信息采集 + 业务 Skill + 专业 Agent + Swarm 协作”的安全问答链路，用于缓解背景信息缺失、复杂问题拆解不足、上下文遗忘和安全边界不稳定等问题。

> ⚠️ 说明：本项目仅用于学习、研究和工程展示，不能替代医生诊断或治疗。

## 🧭 项目概览

### 项目定位

在普通单 Agent 医疗问答中，模型容易把问诊采集、症状分析、知识检索、风险分级、生活建议和安全提示混在一次生成里处理，导致信息不足时追问不稳定、复杂问题拆解不足、多轮上下文丢失，以及高危症状提醒和免责声明遗漏。MedAgentCare 的核心目标是把医疗咨询拆成可复用、可约束、可验证的执行单元，并通过三路路由在问诊采集、快速咨询和 Swarm 协作之间切换执行路径。

### 核心方案

- **分层架构**：将检索、评估、建议和研究等能力拆分为 9 个可发现 Skill，其中 7 个业务 Skill 覆盖知识检索、风险评估、症状分析、生活建议、ICD-10 编码、临床指南和深度研究，2 个记忆类 Skill 覆盖会话历史与相似案例检索。
- **专业 Agent**：定义路由入口、问诊 Agent 和 3 个 Worker Agent。`InterviewAgent` 负责逐轮信息采集，`LeadAgent` 负责复杂问题拆解与结果汇总，`ConsultationAgent`、`DiagnosticAgent`、`ResearchAgent` 分别承担健康咨询、诊断推理和循证研究任务。
- **问诊路由**：构建“信息采集 → 快速咨询 → Swarm 协作”的三路路由机制。症状背景不足时先由 `InterviewAgent` 追问关键信息并生成问诊摘要；常见低风险咨询进入 `ConsultationAgent` 快速路径；复杂、高危、诊断或研究类问题由 `LeadAgent` 拆解后交给多个专业 Agent 并行处理。
- **记忆机制**：短期记忆维护会话内最近 5 轮关键上下文；长期记忆支持 Mem0 后端，并提供本地文件记忆后端，支持跨会话相似案例检索和会话摘要沉淀。
- **安全约束**：通过 Harness Engineering 约束 Agent 能力边界、工具调用、输出格式和医疗安全策略，覆盖免责声明、高危症状提醒、明确诊断和处方剂量风险，并在可修复场景下自动补全不合规输出。

### 架构图

```mermaid
flowchart TB
    User["用户输入<br/>健康咨询问题"] --> Entry["入口层<br/>CLI / FastAPI / 前端 SSE"]
    Entry --> Process["process_with_swarm"]
    Process --> Router{"SwarmCoordinator<br/>三路路由"}

    subgraph Memory["记忆系统"]
        ShortMemory["短期记忆<br/>最近 5 轮上下文"]
        InterviewState["问诊状态<br/>多轮采集进度"]
        LongMemory["长期记忆<br/>Mem0"]
        LocalMemory["本地文件记忆"]
    end

    Router -.-> Memory
    Router -->|症状背景不足| Interview["InterviewAgent<br/>问诊信息采集"]
    Interview --> InterviewResult{"问诊是否完成"}
    InterviewResult -->|继续追问| FollowUp["返回追问<br/>等待下一轮输入"]
    InterviewResult -->|生成摘要| Router

    Router -->|常见低风险咨询| FastPath["快速咨询路径"]
    FastPath --> Consultation["ConsultationAgent<br/>健康咨询"]

    Router -->|复杂 / 高危 / 研究类问题| Lead["LeadAgent<br/>路由拆解与汇总"]
    Lead --> Shared["SharedContext<br/>子任务与共享上下文"]

    subgraph Workers["Worker Agent 并行执行"]
        ConsultWorker["ConsultationAgent"]
        DiagnosticWorker["DiagnosticAgent"]
        ResearchWorker["ResearchAgent"]
    end

    Shared --> ConsultWorker
    Shared --> DiagnosticWorker
    Shared --> ResearchWorker

    subgraph Loop["Agent Loop<br/>ReAct / Think-Act-Observe"]
        SkillRegistry["Skill Registry<br/>自动发现与加载"]
        Validator["ConstraintValidator<br/>能力边界与输出校验"]
        AutoFixer["AutoFixer<br/>安全输出修复"]
    end

    Consultation --> Loop
    ConsultWorker --> Loop
    DiagnosticWorker --> Loop
    ResearchWorker --> Loop

    subgraph Skills["Skill 层<br/>7 个业务 Skill + 2 个记忆 Skill"]
        SearchKnowledge["search_knowledge"]
        AssessRisk["assess_risk"]
        AnalyzeSymptoms["analyze_symptoms"]
        RecommendLifestyle["recommend_lifestyle"]
        DiseaseCode["disease_code"]
        ClinicalGuideline["clinical_guideline"]
        DeepResearch["deep_research"]
        SearchHistory["search_history"]
        SearchSimilar["search_similar_cases"]
    end

    SkillRegistry --> Skills
    Validator -.-> Skills
    AutoFixer -.-> Loop

    SearchKnowledge --> Milvus[("Milvus 知识库<br/>语义检索")]
    AssessRisk --> Milvus
    AnalyzeSymptoms --> Milvus
    RecommendLifestyle --> Milvus
    DiseaseCode --> Milvus
    ClinicalGuideline --> Milvus
    DeepResearch --> WebSearch[("DuckDuckGo<br/>网络搜索")]
    SearchHistory --> ShortMemory
    SearchSimilar --> LongMemory
    SearchSimilar --> LocalMemory

    Lead --> Summary["结果汇总<br/>结构化正文 / 建议 / 免责声明"]
    Loop --> Summary
    Memory -.-> Summary
    Summary --> Output["最终输出<br/>SSE / JSON"]

    classDef entry fill:#d8e8ff,stroke:#4777b3,stroke-width:1px,color:#111;
    classDef router fill:#fff2cc,stroke:#d6a300,stroke-width:1px,color:#111;
    classDef agent fill:#f8cecc,stroke:#cc5c55,stroke-width:1px,color:#111;
    classDef loop fill:#eadcf2,stroke:#8e6aa3,stroke-width:1px,color:#111;
    classDef skill fill:#e6f4df,stroke:#6aa84f,stroke-width:1px,color:#111;
    classDef data fill:#dbeafe,stroke:#3c78d8,stroke-width:1px,color:#111;
    classDef output fill:#e6f4df,stroke:#6aa84f,stroke-width:1px,color:#111;

    class User,Entry,Process entry;
    class Router,Summary,InterviewResult router;
    class Interview,FollowUp,FastPath,Lead,Shared,ConsultWorker,DiagnosticWorker,ResearchWorker,Consultation agent;
    class Loop,SkillRegistry,Validator,AutoFixer loop;
    class SearchKnowledge,AssessRisk,AnalyzeSymptoms,RecommendLifestyle,DiseaseCode,ClinicalGuideline,DeepResearch,SearchHistory,SearchSimilar skill;
    class Milvus,WebSearch,ShortMemory,InterviewState,LongMemory,LocalMemory data;
    class Output output;
```

### 结果指标

项目评估关注路由、记忆、响应成本和医疗安全边界四类指标：

| 维度 | 优化前 | 优化后 |
| --- | ---: | ---: |
| 智能路由准确率 | - | 95% |
| 常见咨询延迟成本 | Swarm 基线 | 降低约 75% |
| 多轮上下文理解准确率 | 60% | 92% |
| 医学盲评综合得分 | 3.8 / 5 | 4.5 / 5 |

评测方式包括自建多轮医疗咨询样例集、LLM-as-a-Judge 和人工抽检，重点观察信息不足场景下回答完整性、风险识别稳定性、免责声明覆盖和高危症状就医提醒。

### 技术栈

| 层级 | 技术 |
| --- | --- |
| 后端服务 | Python, FastAPI |
| 前端演示 | React, TypeScript, Vite |
| Agent 编排 | ReAct, Agent Swarm, Skill Registry |
| 记忆与知识库 | Mem0, Milvus Lite, 本地文件记忆 |
| 安全约束 | YAML constraints, runtime validator, auto fixer |
| 工程化 | uv, Docker, unittest |

## 📁 目录结构

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

## ⚙️ 配置

配置统一从环境变量读取。

```bash
cp .env.example .env
```

<details>
<summary>关键环境变量</summary>

```bash
LLM_API_KEY=your-openai-compatible-api-key
LLM_MODEL_NAME="qwen3.6-plus"
LLM_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
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

</details>

## 🚀 本地运行

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

前端默认为 `http://127.0.0.1:5173`。

### Docker Compose 一键启动

本地有 Docker Desktop 或 Docker Engine + Compose Plugin 时，可以直接启动 FastAPI 后端和 Vite 前端：

```bash
docker compose up -d
```

默认访问地址：

- 前端：`http://localhost:5173`
- 后端健康检查：`http://localhost:8000/health`
- 后端流式咨询接口：`http://localhost:8000/chat/stream`

Compose 会把 Milvus Lite 数据库和模型缓存挂载到 Docker volume `/data` 下。容
健康检查：

```bash
curl http://127.0.0.1:8000/health
```

流式咨询接口：

```bash
curl -N -X POST http://127.0.0.1:8000/chat/stream \
  -H "Accept: text/event-stream" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "我最近头痛和发热，应该怎么办？"
  }'
```

## 🔌 API 接入

### 健康检查

> 浏览器打开以查看： 

> http://127.0.0.1:8000/docs 

> http://127.0.0.1:8000/redoc

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
  "mem0_configured": true
}
```

字段说明：

- `status`：服务进程是否可响应请求。
- `service`：服务名。
- `llm_configured`：是否检测到 `LLM_API_KEY`。
- `mem0_configured`：是否检测到 `MEM0_API_KEY`。

### 流式医疗咨询

请求：

```bash
curl -N -X POST "http://127.0.0.1:8000/chat/stream" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "question": "我最近胸闷气短，活动后更明显，怎么办？",
    "context": {
      "age": 55,
      "history": "高血压"
    },
    "enable_swarm": true,
    "session_id": "demo-session-001",
    "memory": {
      "enabled": true,
      "backend": "local"
    }
  }'
```

## 📚 知识库

医学文档位于 `src/medagentcare/knowledge/data/documents/`，这些 txt 文件是版本化源数据。导入 Milvus Lite：

```bash
uv run medagentcare-import-knowledge
```

`src/medagentcare/knowledge/data/*.db` 按当前策略视为本地生成产物，默认不纳入 Git，也不会进入 Docker build context。部署时需要在环境初始化阶段运行导入脚本，或通过 volume 挂载预生成的数据库。详见 `src/medagentcare/knowledge/data/README.md`。

## 🧪 验证状态

离线回归测试命令：

```bash
uv run python -m unittest discover -s tests
```

该命令覆盖运行配置读取、FastAPI `/health`、Skill 发现、医疗安全约束，以及 `/chat`、`/chat/stream` 在 mock Swarm 下的错误边界和 `enable_swarm=False` 参数传递。

基础编译检查命令：

```bash
uv run python -m compileall -q src tests .agents/skills
```
