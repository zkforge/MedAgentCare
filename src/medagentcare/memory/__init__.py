"""
记忆系统：Agent 的持久化学习和记忆管理

包含：
- ShortTermMemory：会话级对话历史（内存/Redis）
- LongTermMemory：跨会话记忆（Mem0）
- MemoryEntropyManager：熵管理器（去重和压缩）
"""

# 短期和长期记忆
from .short_term import (
    ShortTermMemory,
    ConversationHistory
)
from .long_term import (
    LongTermMemory
)
from .local_health_memory import (
    LocalHealthMemory
)
from .conversation_store import (
    ConversationStore
)
from .request_context import (
    get_request_memory,
    reset_request_memory,
    set_request_memory,
)

# Harness Engineering: 熵管理
from .entropy_manager import (
    MemoryEntropyManager
)

# 本地 Markdown 持久化
from .agent_identity import (
    AgentIdentity,
    AgentIdentityManager,
    CollaborationRecord,
    ToolUsageStats
)
from .session_summary import (
    SessionSummary,
    SessionSummaryManager,
    AgentParticipation,
    KeyFinding,
    Lesson,
    PerformanceMetrics
)

__all__ = [
    # 短期和长期记忆
    'ShortTermMemory',
    'ConversationHistory',
    'LongTermMemory',
    'LocalHealthMemory',
    'ConversationStore',
    'get_request_memory',
    'reset_request_memory',
    'set_request_memory',
    # Harness Engineering: 熵管理
    'MemoryEntropyManager',
    # 本地持久化类
    'AgentIdentity',
    'AgentIdentityManager',
    'LearningRecord',
    'CollaborationRecord',
    'ToolUsageStats',
    'SessionSummary',
    'SessionSummaryManager',
    'AgentParticipation',
    'KeyFinding',
    'Lesson',
    'PerformanceMetrics',
]
