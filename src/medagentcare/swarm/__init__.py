"""
Swarm 模块：Agent 群体智能协作系统
"""

from .shared_context import SharedContext, SubTask, Contribution, TaskStatus
from .events import Event, EventType

__all__ = [
    'SharedContext',
    'SubTask',
    'Contribution',
    'TaskStatus',
    'Event',
    'EventType',
    'LeadAgent',
    'SwarmCoordinator',
    'process_with_swarm',
]


def __getattr__(name):
    if name == "LeadAgent":
        from .lead_agent import LeadAgent

        return LeadAgent

    if name in {"SwarmCoordinator", "process_with_swarm"}:
        from .swarm_coordinator import SwarmCoordinator, process_with_swarm

        return {
            "SwarmCoordinator": SwarmCoordinator,
            "process_with_swarm": process_with_swarm,
        }[name]

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
