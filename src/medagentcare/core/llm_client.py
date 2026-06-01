"""
LLM客户端
支持调用 OpenAI 兼容的 API（如字节跳动豆包、OpenAI、Deepseek 等）
支持 function calling
"""
import asyncio
import json
import time
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from openai import AsyncOpenAI
from loguru import logger

from medagentcare.config import LLM_CONFIG
from medagentcare.core.tracing import emit_trace_event


@dataclass
class ToolCall:
    """Function call 数据结构"""
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class LLMResponse:
    """LLM 响应数据结构（支持 function calling）"""
    content: Optional[str]
    tool_calls: List[ToolCall]
    finish_reason: str  # "stop", "tool_calls", "length", "content_filter"

    def has_tool_calls(self) -> bool:
        """是否包含 function calls"""
        return len(self.tool_calls) > 0


class LLMClient:
    """统一的LLM客户端，支持多种模型"""

    def __init__(self, model_type: str = "openai_compatible"):
        """
        初始化LLM客户端

        Args:
            model_type: 模型类型，默认 "openai_compatible"（支持 OpenAI 兼容的 API）
        """
        self.model_type = model_type

        if model_type == "openai_compatible":
            # 使用 OpenAI 兼容的 API（通过 config.py 配置）
            self.config = LLM_CONFIG
            api_key = self.config.get("api_key")
            if not api_key:
                raise ValueError(
                    "LLM API key is not configured. Set LLM_API_KEY or OPENAI_API_KEY."
                )
            self.client = AsyncOpenAI(
                api_key=api_key,
                base_url=self.config["base_url"]
            )
            self.model_name = self.config["model_name"]
            self.temperature = self.config.get("temperature", 0.7)
            self.max_tokens = self.config.get("max_tokens", 8192)
        else:
            raise ValueError(f"Unknown model type: {model_type}")

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> str:
        """
        异步聊天接口

        Args:
            messages: 消息列表，格式为 [{"role": "user", "content": "..."}]
            temperature: 温度参数（可选）
            max_tokens: 最大token数（可选）

        Returns:
            模型返回的文本
        """
        try:
            temperature = temperature or self.temperature
            max_tokens = max_tokens or self.max_tokens

            logger.debug(f"Calling LLM ({self.model_type}) with {len(messages)} messages")
            start_time = time.perf_counter()
            await emit_trace_event(
                stage="llm_call",
                title="LLM 调用开始",
                detail="正在请求模型生成文本。",
                metadata={
                    "operation": "chat",
                    "model": self.model_name,
                    "messages_count": len(messages),
                    "max_tokens": max_tokens,
                },
            )

            response = await self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs
            )

            content = response.choices[0].message.content
            logger.debug(f"LLM response length: {len(content)} chars")
            duration_ms = round((time.perf_counter() - start_time) * 1000)
            await emit_trace_event(
                stage="llm_call",
                title="LLM 调用完成",
                detail=f"模型返回 {len(content or '')} 个字符，用时 {duration_ms / 1000:.1f}s。",
                status="completed",
                metadata={
                    "operation": "chat",
                    "model": self.model_name,
                    "duration_ms": duration_ms,
                    "messages_count": len(messages),
                    "content_chars": len(content or ""),
                },
            )
            return content

        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            duration_ms = round((time.perf_counter() - start_time) * 1000) if "start_time" in locals() else None
            await emit_trace_event(
                stage="llm_call",
                title="LLM 调用失败",
                detail=str(e)[:200],
                status="error",
                metadata={
                    "operation": "chat",
                    "model": getattr(self, "model_name", None),
                    "duration_ms": duration_ms,
                },
            )
            raise

    async def chat_with_retry(
        self,
        messages: List[Dict[str, str]],
        max_retries: int = 3,
        **kwargs
    ) -> str:
        """
        带重试的聊天接口

        Args:
            messages: 消息列表
            max_retries: 最大重试次数

        Returns:
            模型返回的文本
        """
        for attempt in range(max_retries):
            try:
                return await self.chat(messages, **kwargs)
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                logger.warning(f"Retry {attempt + 1}/{max_retries} after error: {e}")
                await asyncio.sleep(2 ** attempt)  # 指数退避

    def create_message(self, role: str, content: str) -> Dict[str, str]:
        """
        创建消息对象

        Args:
            role: 角色，"user" 或 "assistant" 或 "system"
            content: 消息内容

        Returns:
            消息字典
        """
        return {"role": role, "content": content}

    async def chat_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: str = "auto",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> LLMResponse:
        """
        带工具支持的聊天接口

        Args:
            messages: 消息列表
            tools: 工具定义列表（OpenAI format）
            tool_choice: 工具选择策略 ("auto"/"required"/"none")
            temperature: 温度参数
            max_tokens: 最大token数

        Returns:
            LLMResponse 对象
        """
        try:
            temperature = temperature or self.temperature
            max_tokens = max_tokens or self.max_tokens

            logger.debug(f"Calling LLM with {len(tools) if tools else 0} tools")
            start_time = time.perf_counter()
            await emit_trace_event(
                stage="llm_call",
                title="LLM 工具决策开始",
                detail="正在请求模型判断是否调用 Skill。",
                metadata={
                    "operation": "chat_with_tools",
                    "model": self.model_name,
                    "messages_count": len(messages),
                    "tools_count": len(tools) if tools else 0,
                    "max_tokens": max_tokens,
                },
            )

            # 准备请求参数
            request_params = {
                "model": self.model_name,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                **kwargs
            }

            # 添加工具参数（如果提供）
            if tools:
                request_params["tools"] = tools
                if tool_choice != "auto":
                    request_params["tool_choice"] = tool_choice

            response = await self.client.chat.completions.create(**request_params)

            # 解析响应
            message = response.choices[0].message
            finish_reason = response.choices[0].finish_reason

            # 提取工具调用
            tool_calls = []
            if hasattr(message, 'tool_calls') and message.tool_calls:
                for tc in message.tool_calls:
                    tool_calls.append(ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=json.loads(tc.function.arguments)
                    ))
                logger.debug(f"LLM requested {len(tool_calls)} tool calls")

            result = LLMResponse(
                content=message.content,
                tool_calls=tool_calls,
                finish_reason=finish_reason
            )
            duration_ms = round((time.perf_counter() - start_time) * 1000)
            await emit_trace_event(
                stage="llm_call",
                title="LLM 工具决策完成",
                detail=f"finish_reason={finish_reason}，用时 {duration_ms / 1000:.1f}s。",
                status="completed",
                metadata={
                    "operation": "chat_with_tools",
                    "model": self.model_name,
                    "duration_ms": duration_ms,
                    "messages_count": len(messages),
                    "tools_count": len(tools) if tools else 0,
                    "tool_calls": [tool_call.name for tool_call in tool_calls],
                    "finish_reason": finish_reason,
                    "content_chars": len(message.content or ""),
                },
            )
            return result

        except Exception as e:
            logger.error(f"LLM call with tools failed: {e}")
            duration_ms = round((time.perf_counter() - start_time) * 1000) if "start_time" in locals() else None
            await emit_trace_event(
                stage="llm_call",
                title="LLM 工具决策失败",
                detail=str(e)[:200],
                status="error",
                metadata={
                    "operation": "chat_with_tools",
                    "model": getattr(self, "model_name", None),
                    "duration_ms": duration_ms,
                    "tools_count": len(tools) if tools else 0,
                },
            )
            raise

    def create_tool_message(
        self,
        tool_call_id: str,
        tool_name: str,
        result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        创建工具执行结果消息

        Args:
            tool_call_id: 工具调用ID
            tool_name: 工具名称
            result: 工具执行结果

        Returns:
            工具消息字典
        """
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": json.dumps(result, ensure_ascii=False)
        }
