"""
问诊状态追踪：维度覆盖、轮次计数、红旗信号检测、终止条件判断

设计原则：
- 维度追踪由代码维护，不依赖 LLM 的"记忆力"
- 终止条件：必问维度全部覆盖 OR 达到最大轮次 OR 用户提前终止
- 红旗信号匹配后，优先追问且压缩最大轮次
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any

# ===== 第一层：通用必问维度 =====
REQUIRED_DIMENSIONS = [
    "部位",
    "时间/病程",
    "性质",
    "严重程度",
    "诱因/缓解因素",
    "伴随症状",
    "既往史",
    "用药史",
]

# ===== 第二层：紧急红旗信号 → 处理策略 =====
RED_FLAG_RULES = {
    "胸痛": "立即追问性质、放射痛、持续时间，必要时建议急诊",
    "呼吸困难": "追问发作情况、体位影响、是否发绀",
    "剧烈头痛": "追问是否突然发作、有无意识改变、视觉变化",
    "意识改变": "快速追问关键信息后建议立即就医",
    "严重过敏": "追问呼吸情况、皮疹范围，必要时建议急诊",
    "出血不止": "追问出血量和持续时间，建议立即就医",
    "高热不退": "追问体温数值、持续时间、伴随症状",
    "咯血": "追问血量、是否胸痛、有无呼吸困难",
    "黑便/呕血": "建议立即就医，减少追问轮次",
    "突发言语不清": "快速评估卒中可能性，建议立即就医",
    "一侧肢体无力": "快速评估卒中可能性，建议立即就医",
    "抽搐": "追问频率、持续时间、意识状态",
    "严重外伤": "减少追问，尽快建议就医",
}


@dataclass
class InterviewState:
    """问诊状态数据类 — 在 ShortTermMemory 中持久化，跨请求追踪"""

    session_id: str
    chief_complaint: str
    current_round: int = 0
    max_rounds: int = 5
    covered_dimensions: List[str] = field(default_factory=list)
    skipped_dimensions: List[str] = field(default_factory=list)
    remaining_dimensions: List[str] = field(
        default_factory=lambda: list(REQUIRED_DIMENSIONS)
    )
    red_flags: List[str] = field(default_factory=list)
    # 维度 → 已重新措辞追问次数（松一次紧一次，>=2 则 skip）
    dimension_retry_count: Dict[str, int] = field(default_factory=dict)
    interview_complete: bool = False
    user_requested_early_exit: bool = False
    # 问诊过程中用户的所有回答摘要（供诊断阶段使用）
    collected_answers: List[Dict[str, str]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    last_updated: datetime = field(default_factory=datetime.now)

    # ===== 维度操作 =====

    def mark_dimension_covered(self, dimension: str):
        """标记某个维度已覆盖（用户给出了有效回答）"""
        if dimension in self.remaining_dimensions:
            self.remaining_dimensions.remove(dimension)
            self.covered_dimensions.append(dimension)
        # 同时清理重试计数
        self.dimension_retry_count.pop(dimension, None)
        self.last_updated = datetime.now()

    def mark_dimension_skipped(self, dimension: str):
        """标记某个维度被跳过（用户无法回答或拒绝回答）"""
        if dimension in self.remaining_dimensions:
            self.remaining_dimensions.remove(dimension)
            self.skipped_dimensions.append(dimension)
        self.dimension_retry_count.pop(dimension, None)
        self.last_updated = datetime.now()

    def retry_dimension(self, dimension: str) -> bool:
        """
        重新措辞追问（松一次 → 紧一次 → 跳过）
        返回 True 表示应该继续追问，False 表示应该跳过
        """
        count = self.dimension_retry_count.get(dimension, 0)
        if count >= 2:
            self.mark_dimension_skipped(dimension)
            return False
        self.dimension_retry_count[dimension] = count + 1
        return True

    # ===== 红旗信号 =====

    def add_red_flag(self, flag: str):
        """记录触发的红旗信号，并自动压缩最大轮次"""
        if flag not in self.red_flags:
            self.red_flags.append(flag)
            # 有红旗信号时压缩轮次到 2-3 轮，尽快给出建议
            self.max_rounds = min(self.max_rounds, 3)
        self.last_updated = datetime.now()

    def has_red_flags(self) -> bool:
        return len(self.red_flags) > 0

    def is_emergency(self) -> bool:
        """是否需要立即建议就医（如卒中、心梗等）"""
        emergency_signals = {
            "突发言语不清", "一侧肢体无力", "黑便/呕血",
            "严重外伤", "意识改变",
        }
        return bool(set(self.red_flags) & emergency_signals)

    # ===== 终止条件判断 =====

    def check_completion(self) -> bool:
        """检查问诊是否应该终止（任一条件满足）"""
        if self.interview_complete:
            return True
        if not self.remaining_dimensions:
            self.interview_complete = True
            return True
        if self.current_round >= self.max_rounds:
            self.interview_complete = True
            return True
        if self.user_requested_early_exit:
            self.interview_complete = True
            return True
        return False

    # ===== 记录收集 =====

    def add_answer(self, question: str, answer: str, dimension: str = ""):
        """记录一次问答"""
        self.collected_answers.append({
            "round": str(self.current_round),
            "dimension": dimension,
            "question": question,
            "answer": answer,
        })
        self.last_updated = datetime.now()

    def build_summary(self) -> str:
        """构建问诊摘要文本（供诊断阶段使用）"""
        parts = [f"主诉：{self.chief_complaint}"]
        parts.append(f"问诊轮次：{self.current_round}/{self.max_rounds}")
        parts.append(f"已覆盖维度：{', '.join(self.covered_dimensions) if self.covered_dimensions else '无'}")

        if self.skipped_dimensions:
            parts.append(f"跳过的维度：{', '.join(self.skipped_dimensions)}")
        if self.red_flags:
            parts.append(f"⚠️ 触发的红旗信号：{', '.join(self.red_flags)}")
        if self.user_requested_early_exit:
            parts.append("⚠️ 用户提前终止问诊，以下信息不完整")

        parts.append("\n问诊记录：")
        for entry in self.collected_answers:
            dim_label = f"[{entry['dimension']}] " if entry["dimension"] else ""
            parts.append(f"  {dim_label}问：{entry['question']}")
            parts.append(f"  答：{entry['answer']}")

        return "\n".join(parts)

    # ===== 序列化（跨请求持久化） =====

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "chief_complaint": self.chief_complaint,
            "current_round": self.current_round,
            "max_rounds": self.max_rounds,
            "covered_dimensions": self.covered_dimensions,
            "skipped_dimensions": self.skipped_dimensions,
            "remaining_dimensions": self.remaining_dimensions,
            "red_flags": self.red_flags,
            "dimension_retry_count": self.dimension_retry_count,
            "interview_complete": self.interview_complete,
            "user_requested_early_exit": self.user_requested_early_exit,
            "collected_answers": self.collected_answers,
            "created_at": self.created_at.isoformat(),
            "last_updated": self.last_updated.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InterviewState":
        return cls(
            session_id=data["session_id"],
            chief_complaint=data["chief_complaint"],
            current_round=data.get("current_round", 0),
            max_rounds=data.get("max_rounds", 5),
            covered_dimensions=data.get("covered_dimensions", []),
            skipped_dimensions=data.get("skipped_dimensions", []),
            remaining_dimensions=data.get(
                "remaining_dimensions", list(REQUIRED_DIMENSIONS)
            ),
            red_flags=data.get("red_flags", []),
            dimension_retry_count=data.get("dimension_retry_count", {}),
            interview_complete=data.get("interview_complete", False),
            user_requested_early_exit=data.get("user_requested_early_exit", False),
            collected_answers=data.get("collected_answers", []),
        )
