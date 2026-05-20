"""
核心模块
"""
__all__ = [
    'LLMClient',
    'ToolCall',
    'LLMResponse',
    'AgentLoop',
    'AgentState',
    'TaskStatus',
    'SkillRegistry',
    'SkillParameter'
]


def __getattr__(name):
    if name in {"LLMClient", "ToolCall", "LLMResponse"}:
        from .llm_client import LLMClient, ToolCall, LLMResponse

        return {
            "LLMClient": LLMClient,
            "ToolCall": ToolCall,
            "LLMResponse": LLMResponse,
        }[name]

    if name == "AgentLoop":
        from .agent_loop import AgentLoop

        return AgentLoop

    if name in {"AgentState", "TaskStatus"}:
        from .state_manager import AgentState, TaskStatus

        return {
            "AgentState": AgentState,
            "TaskStatus": TaskStatus,
        }[name]

    if name in {"SkillRegistry", "SkillParameter"}:
        from .skill_registry import SkillRegistry, SkillParameter

        return {
            "SkillRegistry": SkillRegistry,
            "SkillParameter": SkillParameter,
        }[name]

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
