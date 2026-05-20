# TODO

当前文件只记录本轮没有改动的完善项。

## 高优先级

- 补齐 `.claude/skills/*/script/*.py`，让 `core.skill_loader.discover_skills()` 能真正加载 9 个 Skill，而不是只存在 `SKILL.md` 元数据。
- 修复 `validation/__init__.py` 与实际文件名不一致的问题：当前导入 `.auto_fixer`，实际文件是 `auto_fixer_20260428_231043.py`。
- 重写 `examples/test_all.py` 中已经漂移的测试字段，例如 `agent.tool_registry` 应与当前 `skill_registry` 架构对齐。
- 增加不依赖真实 LLM、Mem0、Milvus、外网搜索的离线单元测试，先覆盖配置加载、FastAPI health、Skill 发现、约束验证和路由降级。

## 中优先级

- 整理 `swarm/events.py` 与 `swarm/events(1).py` 的重复文件，只保留一个正式事件定义。
- 明确 Milvus Lite 数据库是否作为生成产物。如果是生成产物，保持忽略；如果要随项目分发，需要补数据导入和版本策略。
- 为 Docker 部署补充生产环境配置建议，例如反向代理、超时、日志、健康检查和模型/embedding 缓存挂载。
- 将 `setup.py` 迁移或补充为 `pyproject.toml`，添加正式包元数据和可执行入口。
- 为医疗安全约束增加回归测试，覆盖高危症状必须就医、禁止明确诊断、禁止具体处方剂量等规则。

## 低优先级

- 收敛 README 中历史阶段性表述，避免再次出现“已完成但代码不可验证”的状态漂移。
- 统一中文/英文命名，例如 MediX、MedAgentCare、medix-agent-swarm 当前混用。
- 增加 API 示例请求、错误响应示例和前端接入说明。
