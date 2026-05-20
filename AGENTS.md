# MedAgentCare Project Map

本文档是给后续开发者和代码 Agent 使用的仓库地图。修改代码前先读这里，再进入具体文件。

## 工作原则

- 默认使用中文沟通、中文解释代码变更。
- 先看 `git status --short`，确认当前工作树是否已有未提交改动。
- 只改当前任务直接相关的文件；发现无关历史问题时记录或说明，不顺手重构。
- 不把 README 写成阶段汇报；README 只能声明代码、配置或命令可验证的事实。
- 医疗输出相关修改必须注意安全约束：不能明确诊断，不能给具体处方剂量，高危症状必须建议就医。
- 当前没有可重复端到端集成测试；优先使用 `tests/` 下的离线测试。

## 常用命令

```bash
# 离线回归测试，不依赖真实 LLM、Mem0、Milvus 或外网搜索
PYTHONPATH=src python3 -m unittest discover -s tests

# 基础编译检查
python3 -m compileall -q src tests .agents/skills

# 本地 CLI
medagentcare

# FastAPI
uvicorn medagentcare.api:app --host 0.0.0.0 --port 8000

# 医学知识库导入
medagentcare-import-knowledge
```

## 根目录文件职责

- `README.md`：面向用户和部署者的项目说明。记录当前可验证状态、本地运行、API 示例、Docker 部署和验证边界。
- `TODO.md`：只记录尚未完成的完善项；已完成事项要从这里移除。
- `AGENTS.md`：面向代码 Agent 的开发地图和文件职责说明。
- `pyproject.toml`：正式包元数据、依赖、`src/` 包发现规则、console scripts 和包数据配置。
- `requirements.txt`：Dockerfile 当前使用的依赖安装清单。
- `Dockerfile`：生产镜像基础定义，默认运行 `uvicorn medagentcare.api:app --host 0.0.0.0 --port 8000`。
- `.env.example`：运行时环境变量示例，不放真实密钥。
- `.gitignore`：忽略本地环境、缓存、生成数据库和本地 Agent 设置。
- `.dockerignore`：控制 Docker build context，避免带入本地缓存、密钥和生成数据库。

## 包入口

- `src/medagentcare/__init__.py`：包版本声明。
- `src/medagentcare/config.py`：统一读取运行配置。`LLM_CONFIG` 从 `LLM_API_KEY` 或 `OPENAI_API_KEY` 读取；`MEM0_CONFIG` 从 `MEM0_API_KEY` 读取。
- `src/medagentcare/main.py`：交互式 CLI 入口。负责读取用户输入、调用 `process_with_swarm()`、打印回答、建议和免责声明。
- `src/medagentcare/api.py`：FastAPI HTTP 入口。提供 `/health` 和 `/chat`，只做请求校验、配置可用性暴露和错误映射，实际咨询流程委托给 Swarm。

## Core 模块

- `src/medagentcare/core/__init__.py`：核心类型的懒加载导出，避免导入包时过早触发 LLM/OpenAI 依赖。
- `src/medagentcare/core/llm_client.py`：OpenAI-compatible LLM 客户端封装，定义 `ToolCall`、`LLMResponse` 和工具调用消息格式。
- `src/medagentcare/core/agent_loop.py`：Agent 主循环。负责 LLM 调用、Skill 调用、短期记忆写入、输出约束验证和自动修复。
- `src/medagentcare/core/state_manager.py`：Agent Loop 的任务状态管理，定义 `TaskStatus`、`AgentState` 和 `StateManager`。
- `src/medagentcare/core/skill_registry.py`：运行时 Skill 注册表，负责把本地 Skill 转成 OpenAI function-calling 格式并执行。
- `src/medagentcare/core/skill_loader.py`：从 `.agents/skills` 自动发现并按文件路径加载 Skill。当前优先 `.agents/skills`，保留 `.claude/skills` fallback 兼容旧路径。

## Agents 模块

- `src/medagentcare/agents/__init__.py`：Agent 类型和便捷函数导出。
- `src/medagentcare/agents/base_agent.py`：所有 Worker Agent 的抽象基类。封装 LLMClient、AgentLoop、SkillRegistry、共享上下文挂载和子任务处理。
- `src/medagentcare/agents/skill_registry_mixin.py`：统一自动注册 `.agents/skills` 下发现的所有 Skill，并从函数签名推断参数。
- `src/medagentcare/agents/consultation_agent.py`：通用健康咨询 Agent。负责常见咨询、生活建议、症状分诊和免责声明提取。
- `src/medagentcare/agents/diagnostic_agent.py`：诊断推理 Agent。负责症状分析、鉴别诊断思路和风险评估，但不能下确诊结论。
- `src/medagentcare/agents/research_agent.py`：医学研究 Agent。负责指南、证据检索和研究综合，偏向资料支持而不是直接医疗决策。

## Swarm 模块

- `src/medagentcare/swarm/__init__.py`：Swarm 公开类型导出。对重依赖对象使用懒加载。
- `src/medagentcare/swarm/events.py`：Swarm 事件类型和事件数据结构。
- `src/medagentcare/swarm/shared_context.py`：多 Agent 共享上下文。管理子任务、贡献结果、事件流和任务状态。
- `src/medagentcare/swarm/lead_agent.py`：LeadAgent。负责判断问题复杂度、拆分子任务、选择 Agent，并综合多个 Agent 的结果。
- `src/medagentcare/swarm/swarm_coordinator.py`：Swarm 总入口和路由器。负责单 Agent、禁用 Swarm、fallback 和多 Agent 协作路径，导出 `process_with_swarm()`。

## Constraints 与 Validation

- `src/medagentcare/constraints/__init__.py`：约束验证器导出。
- `src/medagentcare/constraints/agent_constraints.yaml`：Agent 能力边界、允许工具、禁止行为和输出约束。
- `src/medagentcare/constraints/swarm_constraints.yaml`：Swarm 层任务拆分、Agent 选择和协作约束。
- `src/medagentcare/constraints/validator.py`：运行时约束验证。检查工具调用、输出免责声明、高危就医提醒、明确诊断和具体处方剂量。
- `src/medagentcare/validation/__init__.py`：自动修复器导出。
- `src/medagentcare/validation/auto_fixer.py`：对可自动修复的输出问题追加免责声明或高危就医提醒。

## Memory 模块

- `src/medagentcare/memory/__init__.py`：记忆系统公开类导出。
- `src/medagentcare/memory/short_term.py`：短期记忆。支持内存存储和 Redis fallback，用于当前会话历史。
- `src/medagentcare/memory/long_term.py`：长期记忆。基于 Mem0 的跨会话记忆和相似会话搜索；未配置时应降级为 disabled。
- `src/medagentcare/memory/session_summary.py`：会话总结结构和本地持久化管理。
- `src/medagentcare/memory/agent_identity.py`：Agent 身份、协作记录、工具使用统计和本地 Markdown 持久化。
- `src/medagentcare/memory/entropy_manager.py`：记忆去重、压缩和熵管理，减少长期记忆噪声。

## Knowledge 模块

- `src/medagentcare/knowledge/__init__.py`：医学知识库导出。
- `src/medagentcare/knowledge/milvus_kb.py`：Milvus Lite 医学知识库封装。默认数据库路径可由 `MEDAGENTCARE_MILVUS_DB_PATH` 覆盖。
- `src/medagentcare/knowledge/scripts/__init__.py`：知识库脚本包标记。
- `src/medagentcare/knowledge/scripts/import_hardcoded_data.py`：从版本化 txt 文档导入 Milvus Lite 数据库的脚本入口。
- `src/medagentcare/knowledge/data/README.md`：知识库数据版本策略。txt 文档是源数据，`*.db` 是本地生成产物。
- `src/medagentcare/knowledge/data/documents/*.txt`：版本化医学知识源文档，覆盖生活方式、急症症状、ICD-10 和指南片段。

## Research 模块

- `src/medagentcare/research/deep_research_workflow.py`：DeepResearch 工作流。整合查询规划、知识库检索、网页搜索和证据综合。
- `src/medagentcare/research/evidence_synthesizer.py`：研究报告结构和证据综合逻辑。
- `src/medagentcare/research/web_search.py`：医学网页搜索工具，封装搜索、抓取和简单结果结构。

## Skills 目录

- `.agents/skills/skill_helpers.py`：本地 Skill 共用工具。负责项目路径注入、统一 success/failure 返回、医学知识库搜索 fallback 和文本格式化。
- `.agents/skills/analyze-symptoms/`：症状系统归类和持续时间风险提示。
- `.agents/skills/assess-risk/`：显式规则风险分级，覆盖胸痛、呼吸困难、昏厥等高危关键词。
- `.agents/skills/clinical-guideline/`：从本地知识库检索指南和诊疗规范片段。
- `.agents/skills/deep-research/`：调用 DeepResearch 工作流并返回结构化研究报告。
- `.agents/skills/disease-code/`：检索 ICD-10 编码和疾病分类资料。
- `.agents/skills/recommend-lifestyle/`：检索疾病或症状对应的生活方式建议。
- `.agents/skills/search-history/`：检索当前会话短期历史。
- `.agents/skills/search-knowledge/`：检索本地医学知识库。
- `.agents/skills/search-similar-cases/`：检索 Mem0 长期记忆中的相似历史案例；未启用 Mem0 时返回结构化降级结果。

## Tests 与历史脚本

- `tests/test_runtime_config.py`：离线测试环境变量配置读取。
- `tests/test_api_offline.py`：离线测试 `/health`、`/chat` 错误映射和 `enable_swarm=False` 参数传递。
- `tests/test_skill_discovery.py`：离线测试 `.agents/skills` 优先目录和 9 个 Skill 自动发现。
- `tests/test_medical_safety_constraints.py`：离线测试医疗安全约束，包括高危就医、禁止确诊、禁止具体处方剂量。
- 旧的大型集成脚本已移除；新增端到端验收请放入 `tests/` 或专门的 `scripts/`，并明确外部依赖。

## 运行边界

- `/health` 只说明 API 进程可响应，并暴露 LLM/Mem0 基础配置状态；不代表真实外部服务全链路可用。
- `/chat` 可能触发 LLM、Mem0、Milvus Lite、外网搜索和多 Agent 协作；生产环境需要更长 HTTP 超时和明确错误展示。
- `src/medagentcare/knowledge/data/*.db` 是生成产物，默认不进 Git，也不进 Docker build context。
- 本地设置文件如 `.agents/settings.local.json` 和 `.claude/settings.local.json` 不应提交。
