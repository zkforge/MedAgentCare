"""
Skill 注册系统
直接将 Skill 函数转换为 OpenAI function calling 格式
"""
from typing import Dict, Any, List, Callable, Optional
from dataclasses import dataclass
import inspect
import asyncio
import time
from loguru import logger

from medagentcare.core.langsmith_tracing import traceable
from medagentcare.core.tracing import emit_trace_event, text_preview


@dataclass
class SkillParameter:
    """Skill 参数定义"""
    name: str
    type: str  # "string", "number", "integer", "boolean", "object", "array"
    description: str
    required: bool = False
    enum: Optional[List[str]] = None


class SkillRegistry:
    """
    Skill 注册表

    存储 Skill 函数并提供执行和格式转换能力
    """

    def __init__(self):
        self.skills: Dict[str, Dict[str, Any]] = {}

    def register(
        self,
        name: str,
        function: Callable,
        description: str,
        parameters: List[SkillParameter]
    ):
        """
        注册 Skill

        Args:
            name: Skill 名称
            function: Skill 函数（async 或 sync）
            description: Skill 描述
            parameters: 参数列表
        """
        self.skills[name] = {
            'function': function,
            'description': description,
            'parameters': parameters,
            'is_async': inspect.iscoroutinefunction(function)
        }
        logger.debug(f"Registered skill: {name}")

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        """获取 Skill"""
        return self.skills.get(name)

    def get_all(self) -> Dict[str, Dict[str, Any]]:
        """获取所有 Skills"""
        return self.skills

    @traceable(name="SkillRegistry.execute", run_type="tool")
    async def execute(self, name: str, **kwargs) -> Dict[str, Any]:
        """
        执行 Skill

        Args:
            name: Skill 名称
            **kwargs: Skill 参数

        Returns:
            Skill 执行结果
        """
        skill = self.skills.get(name)
        if not skill:
            error_msg = f"Skill not found: {name}"
            logger.error(error_msg)
            return {
                "success": False,
                "error": error_msg
            }

        try:
            logger.debug(f"Executing skill: {name} with args: {kwargs}")
            start_time = time.perf_counter()
            await emit_trace_event(
                stage="skill_call",
                title=f"Skill 调用开始：{name}",
                detail=text_preview(kwargs, limit=120),
                metadata={
                    "skill": name,
                    "operation": "execute",
                    "args_preview": text_preview(kwargs, limit=160),
                },
            )

            if skill['is_async']:
                # Async skill
                result = await skill['function'](**kwargs)
            else:
                # Sync skill - run in executor
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None,
                    lambda: skill['function'](**kwargs)
                )

            logger.debug(f"Skill {name} completed successfully")
            duration_ms = round((time.perf_counter() - start_time) * 1000)
            result_count = len(result) if isinstance(result, list) else None
            await emit_trace_event(
                stage="skill_call",
                title=f"Skill 调用完成：{name}",
                detail=f"用时 {duration_ms / 1000:.1f}s。",
                status="completed" if not isinstance(result, dict) or result.get("success", True) else "warning",
                metadata={
                    "skill": name,
                    "operation": "execute",
                    "duration_ms": duration_ms,
                    "success": result.get("success") if isinstance(result, dict) else None,
                    "result_count": result_count,
                },
            )
            return result

        except Exception as e:
            error_msg = f"Skill execution failed: {name} - {str(e)}"
            logger.error(error_msg)
            duration_ms = round((time.perf_counter() - start_time) * 1000) if "start_time" in locals() else None
            await emit_trace_event(
                stage="skill_call",
                title=f"Skill 调用失败：{name}",
                detail=str(e)[:200],
                status="error",
                metadata={
                    "skill": name,
                    "operation": "execute",
                    "duration_ms": duration_ms,
                },
            )
            return {
                "success": False,
                "error": error_msg,
                "skill": name
            }

    def to_openai_format(self) -> List[Dict[str, Any]]:
        """
        直接转换为 OpenAI function calling 格式

        Returns:
            OpenAI tools 格式的列表
        """
        tools = []

        for name, skill in self.skills.items():
            properties = {}
            required = []

            for param in skill['parameters']:
                prop = {
                    'type': param.type,
                    'description': param.description
                }
                if param.enum:
                    prop['enum'] = param.enum

                properties[param.name] = prop

                if param.required:
                    required.append(param.name)

            tools.append({
                'type': 'function',
                'function': {
                    'name': name,
                    'description': skill['description'],
                    'parameters': {
                        'type': 'object',
                        'properties': properties,
                        'required': required
                    }
                }
            })

        return tools
