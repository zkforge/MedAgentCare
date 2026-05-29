"""
问诊 Agent：通过多轮追问采集患者信息

参考 grill-me 技能的"决策树分支遍历"模式，沿诊断树分支系统性追问，
直到信息充分后转入诊断阶段。

设计原则：
- 轻 Skill：仅保留 search_history（避免重复提问），问诊协议编码在系统提示词中
- 混合模式：LLM 动态生成追问 + 医学问诊维度约束
- 每次只问一个问题（one at a time）
- 红旗信号优先追问
"""
import re
from typing import Dict, Any, Optional, List
from loguru import logger

from medagentcare.swarm.interview_state import (
    InterviewState,
    REQUIRED_DIMENSIONS,
    RED_FLAG_RULES,
)
from .base_agent import BaseAgent
from .skill_registry_mixin import SkillRegistryMixin


class InterviewAgent(BaseAgent, SkillRegistryMixin):
    """
    问诊 Agent

    职责：
    - 识别主诉，启动系统性问诊
    - 沿必问维度逐轮追问
    - 检测红旗信号并调整追问策略
    - 信息充分后标记问诊完成
    - 不做诊断，不做治疗建议
    """

    def __init__(self, config: Dict[str, Any] = None):
        default_config = {
            "model": "openai_compatible",
            "max_iterations": 3,
            "temperature": 0.7,
            "description": "问诊Agent，通过多轮追问系统性采集患者症状信息",
        }
        config = config or default_config
        super().__init__(agent_id="interview_agent", config=config)

        self.set_capabilities([
            "symptom_interview",
            "red_flag_detection",
            "medical_history_collection",
        ])

    def get_system_prompt(self) -> str:
        """获取系统提示词 — 内嵌完整问诊协议"""
        return """你是一位专业、温和的医疗问诊助手。你的职责是通过逐步追问了解患者的健康状况，而不是给出诊断或治疗建议。

## 核心原则

1. **每次只问一个问题**，耐心等待患者回答
2. 使用**通俗易懂的日常语言**，避免医学术语
3. 保持**温和、关切但不制造恐慌**的语气
4. 当患者无法回答时，先**换个方式再问一次**，仍无法回答则**跳过**
5. 患者明确表示"不想继续问了"时，**尊重其意愿**，立即标记问诊完成
6. **不要给诊断**，不要给治疗建议，你的唯一任务是收集信息
7. 如果患者回答中出现了红旗信号（如胸痛、意识改变等），应立即优先追问红旗相关内容

## 必问维度（按优先级排序）

你需要围绕以下 8 个维度进行系统性追问：

1. **部位** — "具体哪个位置不舒服？"
2. **时间/病程** — "持续多久了？什么时候开始的？突然发生还是慢慢加重的？"
3. **性质** — "怎么个不舒服法？比如疼痛是刺痛、胀痛还是钝痛？"
4. **严重程度** — "1-10 分大概几分？影响正常工作生活吗？"
5. **诱因/缓解因素** — "什么情况下会加重？什么情况下会舒服一些？"
6. **伴随症状** — "有没有同时出现其他不舒服？比如发热、恶心、乏力？"
7. **既往史** — "以前有过类似情况吗？有没有高血压、糖尿病这类慢性病？"
8. **用药史** — "最近在吃什么药吗？针对这次不舒服吃过什么药了吗？"

**维度追问策略**：
- 自然融入对话，不要机械地按列表逐一提问
- 根据患者的主诉灵活调整追问顺序，最相关的维度优先
- 一个提问可能同时覆盖多个维度（如"这个头痛持续几天了，是一直疼还是一阵一阵的？"同时覆盖时间和性质）
- 如果患者的回答已经自然覆盖了某些维度，不要重复提问

## 红旗信号（紧急情况识别）

以下红旗信号出现时，应优先追问、压缩轮次、必要时在当轮提醒就医：

| 红旗信号 | 追问重点 |
|---------|---------|
| 胸痛 | 性质、放射痛、是否伴随呼吸困难 |
| 呼吸困难 | 发作情况、体位影响、是否发绀 |
| 剧烈头痛/爆炸样头痛 | 是否突然发作、有无视觉变化、意识状态 |
| 意识改变/晕厥 | 快速追问关键信息，提示立即就医 |
| 突发言语不清/一侧肢体无力 | 快速评估卒中可能，强烈建议立即就医 |
| 抽搐 | 频率、持续时间、意识状态 |
| 高热不退 | 体温数值、持续时间 |
| 咯血/黑便/呕血 | 出血量和频率，建议就医 |
| 严重外伤 | 减少追问，尽快建议就医 |

## 可用的 Skill

你只有一个 Skill：
- **search_history**: 搜索当前会话中已经问过的问题和患者已经给出的回答。在每轮追问前调用，避免重复提问。

## 输出格式（严格遵守）

每轮追问，请按以下格式输出：

```
[NEXT_DIMENSION] <本轮要覆盖的维度名称，从必问维度列表中选择>
[QUESTION] <自然语言的追问内容，只问一个问题>
[RED_FLAG] <如果检测到红旗信号，写具体的红旗类型；否则写 "none">
```

如果判断信息已经充分（所有关键维度已覆盖或达到轮次上限），请按以下格式输出：

```
[INTERVIEW_COMPLETE]
[SUMMARY] <对患者已提供信息的简洁总结，包含主诉、已覆盖维度的关键发现、跳过的维度、触发的红旗信号>
```

## 重要提醒

- 你的角色是**信息收集者**，不是医生
- 如果患者直接问"我这是什么病"或"该怎么办"，温和地解释你需要先了解更多信息
- 问诊完成后，其他专业 Agent 会接手进行诊断分析
"""

    def register_tools(self):
        """只注册 search_history（轻 Skill 策略）"""
        # 手动注册 search_history，避免全量加载 9 个 Skill
        from medagentcare.core.skill_loader import discover_skills
        from pathlib import Path

        project_root = Path(__file__).resolve().parents[3]
        discovered = discover_skills(project_root)

        for skill_info in discovered:
            if skill_info["function_name"] == "search_history":
                metadata = skill_info["metadata"]
                func = skill_info["function"]
                description = metadata.get("description", "搜索当前会话的历史对话")
                self.skill_registry.register(
                    name="search_history",
                    function=func,
                    description=description,
                    parameters=[],
                )
                logger.info("InterviewAgent: registered search_history skill")
                return

        logger.warning("InterviewAgent: search_history skill not found")

    def format_user_input(self, input_data: Dict[str, Any]) -> str:
        """格式化用户输入，注入当前问诊状态"""
        question = input_data.get("question", "")
        interview_state: Optional[InterviewState] = input_data.get("interview_state")

        parts = []

        # 注入问诊状态上下文
        if interview_state:
            parts.append("## 当前问诊进度")
            parts.append(f"- 当前轮次：第 {interview_state.current_round}/{interview_state.max_rounds} 轮")
            parts.append(f"- 主诉：{interview_state.chief_complaint}")
            if interview_state.covered_dimensions:
                parts.append(f"- 已覆盖维度：{', '.join(interview_state.covered_dimensions)}")
            if interview_state.skipped_dimensions:
                parts.append(f"- 患者无法回答的维度（不要再次追问）：{', '.join(interview_state.skipped_dimensions)}")
            if interview_state.remaining_dimensions:
                parts.append(f"- 还需覆盖的维度：{', '.join(interview_state.remaining_dimensions)}")
            if interview_state.red_flags:
                parts.append(f"- ⚠️ 已触发红旗信号：{', '.join(interview_state.red_flags)}，请优先关注")
                parts.append("- 请优先追问红旗信号相关的问题")

            # 注入已收集的回答
            if interview_state.collected_answers:
                parts.append("\n## 已收集的患者信息")
                for entry in interview_state.collected_answers:
                    dim_label = f"[{entry['dimension']}] " if entry.get("dimension") else ""
                    parts.append(f"- {dim_label}问：{entry['question']} → 答：{entry['answer']}")

        # 用户最新消息
        parts.append(f"\n## 患者最新消息")
        parts.append(question)

        return "\n".join(parts)

    async def post_process_result(
        self, result: Dict[str, Any], final_response: str
    ) -> Dict[str, Any]:
        """
        解析 LLM 的结构化输出，更新问诊状态
        """
        response = final_response or ""

        # 检查问诊是否完成
        if "[INTERVIEW_COMPLETE]" in response:
            summary_match = re.search(
                r"\[SUMMARY\]\s*(.+?)(?:\n\n|$)", response, re.DOTALL
            )
            summary = summary_match.group(1).strip() if summary_match else response
            result["status"] = "interview_complete"
            result["interview_summary"] = summary
            result["interview_complete"] = True
            logger.info("InterviewAgent: interview marked as complete")
            return result

        # 解析追问
        dim_match = re.search(r"\[NEXT_DIMENSION\]\s*(.+?)(?:\n|$)", response)
        question_match = re.search(r"\[QUESTION\]\s*(.+?)(?:\n|$)", response)
        red_flag_match = re.search(r"\[RED_FLAG\]\s*(.+?)(?:\n|$)", response)

        next_dimension = dim_match.group(1).strip() if dim_match else ""
        follow_up_question = question_match.group(1).strip() if question_match else response
        red_flag = red_flag_match.group(1).strip() if red_flag_match else "none"

        # 如果 LLM 没有按格式输出，提取纯文本作为追问
        if not question_match and not dim_match:
            # 尝试从响应中提取有意义的问题
            follow_up_question = response.strip()

        result["status"] = "need_more_info"
        result["question"] = follow_up_question
        result["covered_dimension"] = next_dimension
        result["red_flag_detected"] = red_flag if red_flag != "none" else None
        result["interview_complete"] = False

        logger.info(
            f"InterviewAgent: follow-up question (dim={next_dimension}, red_flag={red_flag})"
        )
        return result
