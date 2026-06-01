"""
SwarmCoordinator：Swarm 入口和智能路由

注意：这不是编排器！
- 只负责路由决策：简单问题 → 单 Agent，复杂问题 → Swarm
- 不控制 Agent 执行
- 不编排任务顺序

类比：交通信号灯，决定车辆走哪条路，但不控制车辆如何行驶
"""
import asyncio
import uuid
from datetime import datetime
from typing import Awaitable, Callable, Dict, Any, Optional, List
from loguru import logger

from medagentcare.core import LLMClient
from .shared_context import SharedContext
from .lead_agent import LeadAgent
from .events import Event, EventType
from medagentcare.agents import ConsultationAgent, DiagnosticAgent, ResearchAgent, InterviewAgent
from medagentcare.core.tracing import reset_trace_callback, set_trace_callback
from medagentcare.memory import SessionSummaryManager, SessionSummary, ShortTermMemory, LongTermMemory
from medagentcare.response_sections import structure_medical_response
from .interview_state import InterviewState, REQUIRED_DIMENSIONS, RED_FLAG_RULES


ProgressCallback = Callable[[Dict[str, Any]], Awaitable[None]]


class SwarmCoordinator:
    """
    Swarm 协调器

    职责：
    1. 智能路由（简单 → 单 Agent，复杂 → Swarm）
    2. 初始化 SharedContext
    3. 启动和监控 Swarm
    4. 生成 SessionSummary

    不做：
    - 不编排 Worker 执行顺序
    - 不直接调用 Worker
    - 不控制任务分配
    """

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        enable_swarm: bool = True,
        progress_callback: Optional[ProgressCallback] = None
    ):
        self.llm_client = llm_client or LLMClient()
        self.enable_swarm = enable_swarm
        self.progress_callback = progress_callback

        # 初始化 Agent
        self.lead_agent = LeadAgent(llm_client=self.llm_client)
        self.consultation_agent = ConsultationAgent()
        self.diagnostic_agent = DiagnosticAgent()
        self.research_agent = ResearchAgent()
        self.interview_agent = InterviewAgent()

        # Worker 池
        self.worker_pool: List[Any] = [
            self.consultation_agent,
            self.diagnostic_agent,
            self.research_agent
        ]

        # 记忆管理器
        self.session_manager = SessionSummaryManager()
        self.short_term_memory = ShortTermMemory(storage_type="memory")  # 或 "redis"
        self.long_term_memory = LongTermMemory()

        # 将短期记忆注入到所有 Worker Agent 的 Loop
        # 注意：LeadAgent 不继承 BaseAgent，没有 loop 属性，不需要注入
        for worker in self.worker_pool + [self.interview_agent]:
            if hasattr(worker, 'loop'):
                worker.loop.short_term_memory = self.short_term_memory

        logger.info(f"SwarmCoordinator initialized with {len(self.worker_pool)} workers")
        logger.info(f"Memory system: short_term={self.short_term_memory.storage_type}, long_term={'enabled' if self.long_term_memory.enabled else 'disabled'}")

    @staticmethod
    def _should_use_fast_consultation(
        question: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        判断是否可跳过 LeadAgent，直接进入通用咨询路径。

        只覆盖短、常见、无明确急症信号的咨询；复杂鉴别诊断、指南检索
        和高危表现继续交给 LeadAgent 路由。
        """
        context_text = ""
        if context:
            context_text = " ".join(str(value) for value in context.values())
        text = f"{question} {context_text}".lower()

        if len(text) > 120:
            return False

        research_terms = (
            "指南", "共识", "论文", "文献", "研究", "循证", "最新",
            "诊疗规范", "治疗方案", "标准治疗",
        )
        if any(term in text for term in research_terms):
            return False

        diagnostic_terms = ("确诊", "诊断", "鉴别", "什么病", "是不是")
        if any(term in text for term in diagnostic_terms):
            return False

        high_risk_terms = (
            "胸痛", "胸闷", "呼吸困难", "气短", "喘不上气",
            "意识", "昏迷", "抽搐", "晕厥", "昏厥",
            "偏瘫", "口角歪斜", "说话不清", "言语不清",
            "视物模糊", "颈项强直", "脖子硬", "剧烈头痛",
            "爆炸样头痛", "最严重头痛", "持续加重",
            "血压180", "180/110", "180／110", "高热不退",
            "孕", "怀孕", "婴儿", "儿童", "老人", "免疫抑制",
        )
        if any(term in text for term in high_risk_terms):
            return False

        routine_symptoms = (
            "发热", "发烧", "低热", "头痛", "咳嗽", "咽痛",
            "流鼻涕", "鼻塞", "乏力", "肌肉酸痛", "腹泻", "恶心",
        )
        if not any(term in text for term in routine_symptoms):
            return False

        consultation_intents = ("怎么办", "注意什么", "需要注意", "建议", "怎么处理")
        return any(term in text for term in consultation_intents)

    # ===== 问诊模式路由 =====

    @staticmethod
    def _is_symptom_report(question: str) -> bool:
        """
        判断用户输入是否为需要问诊采集的症状报告。

        触发条件：信息贫乏的症状描述（有人称 + 有症状 + 缺少细节）
        不触发：已提供详情的咨询（有具体数值/病史/诊断术语）、纯知识问答

        症状报告示例：
        - "我最近头痛，怎么办" → 触发
        - "小孩发烧了要去医院吗" → 触发
        - "最近总是头晕乏力" → 触发

        不触发示例：
        - "高血压怎么治疗" → 知识问答
        - "35岁，头痛发热两天，体温38.2度，有高血压史" → 信息已详细
        - "二甲双胍的副作用是什么" → 知识问答
        """
        text = question.lower()

        # 排除纯知识问答
        knowledge_patterns = (
            "治疗方案", "治疗方法", "怎么治疗", "如何治疗",
            "副作用", "禁忌症", "适应症",
            "诊断标准", "鉴别诊断",
            "是什么", "什么是", "什么意思",
            "指南推荐", "临床指南",
        )
        has_knowledge_intent = any(p in text for p in knowledge_patterns)

        # 第一/第三人称报告模式
        person_indicators = (
            "我", "我的", "自己", "本人",
            "小孩", "孩子", "宝宝", "女儿", "儿子",
            "老人", "奶奶", "爷爷", "爸爸", "妈妈", "父亲", "母亲",
            "家人", "亲戚", "朋友",
            "最近", "这几天", "这两天", "今天", "昨天",
        )
        has_person = any(p in text for p in person_indicators)

        # 症状描述词
        symptom_indicators = (
            "痛", "疼", "晕", "闷", "胀", "麻",
            "不舒服", "难受", "不适",
            "发热", "发烧", "咳嗽", "恶心", "呕吐", "腹泻",
            "痒", "肿", "红", "出疹", "起疹",
            "乏力", "无力", "失眠", "心慌",
            "出血", "流血", "便血",
        )
        has_symptom = any(p in text for p in symptom_indicators)

        # 咨询意图
        consultation_intents = (
            "怎么办", "要不要", "需不需要", "用不用",
            "吃什么药", "能不能", "可以吗", "严重吗",
        )
        has_consultation = any(p in text for p in consultation_intents)

        # 纯知识问答不触发
        if has_knowledge_intent and not has_person:
            return False

        # 已提供详细信息的不触发（有具体数值、诊断术语、既往病史描述）
        detailed_info_indicators = (
            # 具体数值
            "度", "℃", "分", "级",
            # 详细时间描述
            "两天", "三天", "一周", "一个月", "几个月",
            "前天", "上周", "上个月",
            # 既往史（指定了具体疾病）
            "高血压史", "糖尿病史", "心脏病史", "有高血压", "有糖尿病",
            "在吃药", "在服药", "正在服用",
        )
        has_detailed_info = any(p in text for p in detailed_info_indicators)

        # 有人称 + 有症状 + 无详细信息 → 触发问诊
        # 有人称 + 有咨询意图 + 无详细信息 → 触发问诊
        if not (has_person and (has_symptom or has_consultation)):
            return False

        # 信息已详细 → 不需要问诊，直接走咨询/诊断
        if has_detailed_info:
            return False

        return True

    @staticmethod
    def _has_early_exit_intent(question: str) -> bool:
        """检测用户是否希望提前结束问诊"""
        exit_phrases = (
            "别问了", "不想说了", "直接告诉我", "直接说",
            "能不能直接", "别废话", "快告诉我",
        )
        return any(p in question.lower() for p in exit_phrases)

    async def _handle_interview_turn(
        self,
        question: str,
        session_id: str,
        interview_state: Optional[InterviewState],
        enhanced_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        处理单轮问诊

        返回:
            - status="need_more_info": 返回追问，等待用户下一轮输入
            - status="interview_complete": 问诊完成，转入诊断阶段
        """
        # 检测提前终止意图
        if self._has_early_exit_intent(question):
            if interview_state:
                interview_state.user_requested_early_exit = True
                interview_state.check_completion()
                self.short_term_memory.set_interview_state(session_id, interview_state)
                logger.info(f"User requested early exit from interview (session={session_id})")

                # 直接返回 interview_complete，外部处理转入诊断
                return {
                    "status": "interview_complete",
                    "answer": "好的，我理解。让我根据目前收集到的信息为您分析。",
                    "interview_state": interview_state.to_dict(),
                    "session_id": session_id,
                }

        # 判断是否需要启动新问诊
        if interview_state is None:
            return await self._start_new_interview(question, session_id, enhanced_context)

        # 继续已有问诊
        return await self._continue_interview(question, session_id, interview_state, enhanced_context)

    async def _start_new_interview(
        self,
        question: str,
        session_id: str,
        enhanced_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """启动新的问诊会话"""
        logger.info(f"Starting new interview session (session={session_id})")

        # 创建问诊状态
        interview_state = InterviewState(
            session_id=session_id,
            chief_complaint=question[:200],
        )

        # 检查红旗信号
        for flag_key in RED_FLAG_RULES:
            if flag_key in question:
                interview_state.add_red_flag(flag_key)
                logger.warning(f"Red flag detected at interview start: {flag_key}")

        # 记录用户的初始问题为第一轮回答
        interview_state.current_round = 1
        interview_state.add_answer(
            question="请描述您的不适情况",
            answer=question,
            dimension="主诉",
        )

        self.short_term_memory.set_interview_state(session_id, interview_state)

        # 调用 InterviewAgent 生成第一个追问
        result = await self.interview_agent.process({
            "question": question,
            "context": enhanced_context,
            "session_id": session_id,
            "interview_state": interview_state,
        })

        # 更新问诊状态
        status = result.get("status", "need_more_info")

        if status == "interview_complete":
            interview_state.interview_complete = True
            interview_state.check_completion()
            self.short_term_memory.set_interview_state(session_id, interview_state)
            return {
                "status": "interview_complete",
                "answer": result.get("interview_summary", result.get("answer", "")),
                "interview_state": interview_state.to_dict(),
                "session_id": session_id,
            }

        # need_more_info: 更新维度覆盖
        covered_dim = result.get("covered_dimension", "")
        if covered_dim and covered_dim in interview_state.remaining_dimensions:
            interview_state.mark_dimension_covered(covered_dim)

        # 记录追问到状态
        follow_up = result.get("question", "")
        interview_state.current_round = 1

        # 检查红旗信号
        red_flag = result.get("red_flag_detected")
        if red_flag and red_flag not in interview_state.red_flags:
            interview_state.add_red_flag(red_flag)

        self.short_term_memory.set_interview_state(session_id, interview_state)

        # 构建返回结果
        return {
            "status": "need_more_info",
            "answer": follow_up,
            "interview_round": interview_state.current_round,
            "max_rounds": interview_state.max_rounds,
            "covered_dimensions": interview_state.covered_dimensions,
            "remaining_dimensions": interview_state.remaining_dimensions,
            "session_id": session_id,
            "interview_state": interview_state.to_dict(),
        }

    async def _continue_interview(
        self,
        question: str,
        session_id: str,
        interview_state: InterviewState,
        enhanced_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """继续已有的问诊会话"""
        logger.info(
            f"Continuing interview (session={session_id}, round={interview_state.current_round}/{interview_state.max_rounds})"
        )

        # 增加轮次并记录用户回答
        interview_state.current_round += 1
        interview_state.add_answer(
            question="(追问中)",
            answer=question,
            dimension="",
        )

        # 调用 InterviewAgent
        result = await self.interview_agent.process({
            "question": question,
            "context": enhanced_context,
            "session_id": session_id,
            "interview_state": interview_state,
        })

        status = result.get("status", "need_more_info")

        if status == "interview_complete":
            interview_state.interview_complete = True
            interview_state.check_completion()
            self.short_term_memory.set_interview_state(session_id, interview_state)
            logger.info(f"Interview complete (session={session_id})")

            # 构建问诊总结
            summary = result.get("interview_summary", "") or interview_state.build_summary()
            return {
                "status": "interview_complete",
                "answer": summary,
                "interview_state": interview_state.to_dict(),
                "session_id": session_id,
            }

        # need_more_info: 更新维度覆盖
        covered_dim = result.get("covered_dimension", "")
        if covered_dim and covered_dim in interview_state.remaining_dimensions:
            interview_state.mark_dimension_covered(covered_dim)

        # 补充上一轮回答的维度信息
        if interview_state.collected_answers and covered_dim:
            interview_state.collected_answers[-1]["dimension"] = covered_dim

        # 检查红旗信号
        red_flag = result.get("red_flag_detected")
        if red_flag and red_flag not in interview_state.red_flags:
            interview_state.add_red_flag(red_flag)

        # 检查终止条件
        interview_state.check_completion()

        self.short_term_memory.set_interview_state(session_id, interview_state)

        follow_up = result.get("question", "")

        if interview_state.interview_complete:
            # 轮次用完，自动完成
            logger.info(f"Interview auto-complete: max_rounds reached (session={session_id})")
            return {
                "status": "interview_complete",
                "answer": interview_state.build_summary(),
                "interview_state": interview_state.to_dict(),
                "session_id": session_id,
            }

        return {
            "status": "need_more_info",
            "answer": follow_up,
            "interview_round": interview_state.current_round,
            "max_rounds": interview_state.max_rounds,
            "covered_dimensions": interview_state.covered_dimensions,
            "remaining_dimensions": interview_state.remaining_dimensions,
            "session_id": session_id,
            "interview_state": interview_state.to_dict(),
        }

    async def _emit_progress(
        self,
        stage: str,
        title: str,
        detail: str = "",
        status: str = "running",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Emit a user-facing runtime progress event if SSE is attached."""
        if self.progress_callback is None:
            return

        payload = {
            "timestamp": datetime.now().isoformat(),
            "stage": stage,
            "title": title,
            "detail": detail,
            "status": status,
            "metadata": metadata or {},
        }
        try:
            await self.progress_callback(payload)
        except Exception as exc:
            logger.warning(f"Failed to emit progress event: {exc}")

    def _get_agent_by_id(self, agent_id: str):
        """根据 agent_id 返回对应的 Agent 实例"""
        mapping = {
            "consultation_agent": self.consultation_agent,
            "diagnostic_agent": self.diagnostic_agent,
            "research_agent": self.research_agent
        }
        return mapping.get(agent_id)

    async def process(
        self,
        question: str,
        context: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        处理用户问题

        Args:
            question: 用户问题
            context: 额外上下文（年龄、既往史等）
            session_id: 会话ID（如果不提供，将自动生成）

        Returns:
            处理结果
        """
        start_time = datetime.now()
        if session_id is None:
            session_id = f"{start_time.strftime('%Y%m%d-%H%M%S')}-{str(uuid.uuid4())[:8]}"

        logger.info(f"Processing question (session={session_id}): {question[:50]}...")
        await self._emit_progress(
            stage="request_received",
            title="收到咨询请求",
            detail=f"会话 {session_id} 已开始处理。",
            metadata={"session_id": session_id},
        )
        may_fast_track = self._should_use_fast_consultation(question, context)

        # 保存问诊结果数据（由问诊完成时设置，供记忆检索后使用）
        _interview_result_for_diagnosis: Optional[Dict[str, Any]] = None

        # ===== 问诊模式：前置拦截 =====
        active_interview = self.short_term_memory.get_interview_state(session_id)

        if active_interview and not active_interview.interview_complete:
            # 有活跃的问诊会话 → 继续问诊
            logger.info(
                f"Route: Continue Interview (session={session_id}, "
                f"round={active_interview.current_round}/{active_interview.max_rounds})"
            )
            await self._emit_progress(
                stage="routing",
                title="继续问诊",
                detail=f"第 {active_interview.current_round}/{active_interview.max_rounds} 轮追问。",
                metadata={"mode": "interview_continue"},
            )

            interview_result = await self._handle_interview_turn(
                question=question,
                session_id=session_id,
                interview_state=active_interview,
                enhanced_context=context or {},
            )

            if interview_result.get("status") == "need_more_info":
                # 返回追问，等待用户下一轮输入
                interview_result["swarm_enabled"] = False
                interview_result["route_reason"] = "问诊追问（等待用户回复）"
                interview_result["disclaimer"] = ""
                interview_result["suggestions"] = []

                await self._emit_progress(
                    stage="completed",
                    title="等待用户回复",
                    detail="已发出追问，等待下一轮输入。",
                    status="completed",
                )
                return interview_result

            # interview_complete: 保存结果，后续统一处理
            _interview_result_for_diagnosis = interview_result
            may_fast_track = False

        elif not active_interview and self._is_symptom_report(question):
            # 新症状报告 → 启动问诊
            logger.info(f"Route: Start Interview (session={session_id})")
            await self._emit_progress(
                stage="routing",
                title="启动智能问诊",
                detail="检测到症状描述，开始系统性信息采集。",
                metadata={"mode": "interview_start"},
            )

            interview_result = await self._handle_interview_turn(
                question=question,
                session_id=session_id,
                interview_state=None,
                enhanced_context=context or {},
            )

            if interview_result.get("status") == "need_more_info":
                interview_result["swarm_enabled"] = False
                interview_result["route_reason"] = "启动问诊（首轮追问）"
                interview_result["disclaimer"] = ""
                interview_result["suggestions"] = []

                await self._emit_progress(
                    stage="completed",
                    title="等待用户回复",
                    detail="已发出首轮追问。",
                    status="completed",
                )
                return interview_result

            # 如果首轮就判断问诊完成（极少情况），保存结果
            _interview_result_for_diagnosis = interview_result
            may_fast_track = False

        # ===== 记忆检索 =====
        await self._emit_progress(
            stage="memory_lookup",
            title="检索会话记忆",
            detail="正在读取当前会话历史和相似历史案例。",
        )

        # 1. 检索短期记忆（当前会话历史）
        recent_history = self.short_term_memory.get_recent_messages(
            session_id=session_id,
            limit=10  # 最近5轮对话（10条消息）
        )

        # 2. 检索长期记忆（相似历史会话）
        if may_fast_track:
            similar_memories = []
            logger.info("Fast consultation path skips long-term similar case lookup")
        else:
            similar_memories = self.long_term_memory.search_similar_sessions(
                query=question,
                limit=3
            )

        # 3. 构建增强上下文
        enhanced_context = context or {}

        # 添加短期记忆
        if recent_history:
            enhanced_context["recent_history"] = [
                {"role": msg.get("role", ""), "content": msg.get("content", "")}
                for msg in recent_history
            ]
            logger.info(f"Loaded {len(recent_history)} recent messages from short-term memory")

        # 添加长期记忆
        if similar_memories:
            enhanced_context["historical_cases"] = [
                {
                    "summary": mem["content"],
                    "score": mem["score"]
                }
                for mem in similar_memories
            ]
            logger.info(f"Found {len(similar_memories)} similar historical cases from long-term memory")

        await self._emit_progress(
            stage="memory_lookup",
            title="记忆检索完成",
            detail=f"短期历史 {len(recent_history)} 条，相似历史案例 {len(similar_memories)} 条。",
            status="completed",
            metadata={
                "recent_history_count": len(recent_history),
                "similar_memory_count": len(similar_memories),
            },
        )

        # ===== 问诊完成 → 转入诊断 =====
        if _interview_result_for_diagnosis:
            interview_summary = _interview_result_for_diagnosis.get("answer", "")
            interview_state_dict = _interview_result_for_diagnosis.get("interview_state", {})

            logger.info(f"Interview complete → proceeding to diagnosis (session={session_id})")

            await self._emit_progress(
                stage="routing",
                title="问诊完成",
                detail="信息采集充分，转入诊断分析。",
                status="completed",
                metadata={"mode": "interview_to_diagnosis"},
            )

            # 用问诊总结替代原始 question
            question = (
                f"【问诊总结】\n{interview_summary}\n\n"
                f"请基于以上问诊信息进行全面分析，给出风险评估、鉴别诊断和建议。"
            )
            # 注入问诊状态到 enhanced_context 供 LeadAgent 参考
            enhanced_context["interview_state"] = interview_state_dict
            # 不清理 interview_state，保留用于后续可能的追问
            # 跳过快速路径，走完整的诊断流程
            may_fast_track = False

        if may_fast_track:
            logger.info("Route: Fast ConsultationAgent path")
            await self._emit_progress(
                stage="routing",
                title="进入快速通用咨询路径",
                detail="常见症状咨询且未发现明确急症信号，将跳过多 Agent 拆分。",
                metadata={"agent_id": self.consultation_agent.agent_id},
            )

            result = await self.consultation_agent.process({
                'question': question,
                'context': enhanced_context,
                'session_id': session_id
            })
            final_answer = result.get('answer', '')
            end_time = datetime.now()
            result.update({
                'swarm_enabled': False,
                'session_id': session_id,
                'route_reason': '简单常见咨询快速路由到 consultation_agent',
                'total_time': (end_time - start_time).total_seconds(),
            })
            if 'disclaimer' not in result:
                result['disclaimer'] = "⚠️ 以上信息仅供参考，不能替代专业医生的诊断和治疗。如有疑虑，请及时就医。"
            if 'suggestions' not in result:
                result['suggestions'] = []

            try:
                self.long_term_memory.add_session_summary(
                    session_id=session_id,
                    question=question,
                    answer=final_answer,
                    metadata={
                        "mode": "fast_consultation",
                        "subtasks_count": 0,
                        "total_time": (end_time - start_time).total_seconds(),
                    }
                )
                logger.info(f"Saved to long-term memory (session={session_id}, mode=fast_consultation)")
                await self._emit_progress(
                    stage="memory_save",
                    title="保存会话摘要",
                    detail="已尝试写入长期记忆。",
                    status="completed",
                    metadata={"mode": "fast_consultation"},
                )
            except Exception as e:
                logger.error(f"Failed to save to long-term memory: {e}")
                await self._emit_progress(
                    stage="memory_save",
                    title="长期记忆保存失败",
                    detail=str(e),
                    status="warning",
                    metadata={"mode": "fast_consultation"},
                )

            await self._emit_progress(
                stage="completed",
                title="咨询处理完成",
                detail="最终回答已生成。",
                status="completed",
            )
            return result

        # Step 1: LeadAgent 分解任务
        await self._emit_progress(
            stage="lead_assessment",
            title="分析问题复杂度",
            detail="LeadAgent 正在判断是否需要多 Agent 协作。",
        )
        assessment = await self.lead_agent.assess_and_decompose(question, enhanced_context)
        subtasks = assessment.get("subtasks", [])

        logger.info(f"LeadAgent 分解任务：{len(subtasks)} 个")
        await self._emit_progress(
            stage="lead_assessment",
            title="任务拆分完成",
            detail=f"LeadAgent 生成 {len(subtasks)} 个子任务。",
            status="completed",
            metadata={"subtasks": subtasks},
        )

        # Step 2: 根据任务数量路由
        final_answer = None
        mode = None

        if len(subtasks) == 1:
            # 单任务 → 直接调用对应 Agent
            task = subtasks[0]
            agent_id = task.get("assigned_agent")
            agent = self._get_agent_by_id(agent_id)

            if agent is None:
                # 如果找不到 Agent，降级到 ConsultationAgent
                logger.warning(f"Unknown agent_id: {agent_id}, fallback to ConsultationAgent")
                agent = self.consultation_agent

            logger.info(f"Route: Single Agent ({agent_id})")
            await self._emit_progress(
                stage="routing",
                title="进入单 Agent 路径",
                detail=f"问题已路由到 {agent.agent_id}。",
                metadata={"agent_id": agent.agent_id},
            )
            mode = "single_agent"
            result = await agent.process({
                'question': question,
                'context': enhanced_context,
                'session_id': session_id
            })
            final_answer = result.get('answer', '')

            result.update({
                'swarm_enabled': False,
                'session_id': session_id,
                'route_reason': f'单任务路由到 {agent_id}'
            })

            # 确保单Agent模式下也有 disclaimer 字段
            if 'disclaimer' not in result:
                result['disclaimer'] = "⚠️ 以上信息仅供参考，不能替代专业医生的诊断和治疗。如有疑虑，请及时就医。"

            # 确保单Agent模式下也有 suggestions 字段
            if 'suggestions' not in result:
                result['suggestions'] = []

        elif len(subtasks) >= 2 and self.enable_swarm:
            # 多任务 → 启动 Swarm
            logger.info(f"Route: Swarm (Multi-Agent Collaboration) - {len(subtasks)} tasks")
            await self._emit_progress(
                stage="routing",
                title="进入 Swarm 协作路径",
                detail=f"将并行执行 {len(subtasks)} 个子任务。",
                metadata={"subtasks_count": len(subtasks)},
            )
            mode = "swarm"
            result = await self._process_with_swarm(
                question=question,
                context=enhanced_context,
                assessment=assessment,
                session_id=session_id,
                start_time=start_time
            )
            final_answer = result.get('answer', '')

            # Swarm 模式已经在 _process_with_swarm 中保存了长期记忆，直接返回
            return result

        else:
            # 0个任务或Swarm关闭 → 降级到 ConsultationAgent
            if len(subtasks) == 0:
                logger.warning("No subtasks generated, fallback to ConsultationAgent")
                mode = "fallback"
            else:
                logger.info("Swarm disabled, fallback to ConsultationAgent")
                mode = "disabled_swarm"

            await self._emit_progress(
                stage="routing",
                title="进入通用咨询路径",
                detail="将由 ConsultationAgent 直接处理该问题。",
                metadata={"mode": mode},
            )
            result = await self.consultation_agent.process({
                'question': question,
                'context': enhanced_context,
                'session_id': session_id
            })
            final_answer = result.get('answer', '')
            result.update({
                'swarm_enabled': False,
                'session_id': session_id
            })

        # ===== 统一的记忆保存（非 Swarm 模式）=====
        end_time = datetime.now()

        # 注意：短期记忆已经在 Agent Loop 中保存了，这里不需要重复保存

        # 保存到长期记忆
        try:
            self.long_term_memory.add_session_summary(
                session_id=session_id,
                question=question,
                answer=final_answer,
                metadata={
                    "mode": mode,
                    "subtasks_count": len(subtasks),
                    "total_time": (end_time - start_time).total_seconds(),
                }
            )
            logger.info(f"Saved to long-term memory (session={session_id}, mode={mode})")
            await self._emit_progress(
                stage="memory_save",
                title="保存会话摘要",
                detail="已尝试写入长期记忆。",
                status="completed",
                metadata={"mode": mode},
            )
        except Exception as e:
            logger.error(f"Failed to save to long-term memory: {e}")
            await self._emit_progress(
                stage="memory_save",
                title="长期记忆保存失败",
                detail=str(e),
                status="warning",
                metadata={"mode": mode},
            )

        await self._emit_progress(
            stage="completed",
            title="咨询处理完成",
            detail="最终回答已生成。",
            status="completed",
        )
        return result

    async def _process_with_swarm(
        self,
        question: str,
        context: Optional[Dict[str, Any]],
        assessment: Dict[str, Any],
        session_id: str,
        start_time: datetime
    ) -> Dict[str, Any]:
        """
        使用 Swarm 处理复杂问题

        这是群体智能的核心流程

        注意：context 已经包含了长短期记忆（在 process() 中注入）
        """
        # context 已经包含 recent_history 和 historical_cases
        # 无需重复检索

        # 创建 SharedContext
        shared_context = SharedContext(session_id=session_id)

        # 附加 SharedContext 到所有 Worker
        for worker in self.worker_pool:
            worker.attach_shared_context(shared_context)

        # 发布 Swarm 启动事件
        shared_context.publish_event(Event(
            type=EventType.SWARM_STARTED,
            source_agent="swarm_coordinator",
            data={
                "question": question,
                "num_subtasks": len(assessment.get("subtasks", []))
            }
        ))

        # Step 1: LeadAgent 分解任务
        subtasks = self.lead_agent.create_subtasks(assessment, shared_context)
        logger.info(f"Created {len(subtasks)} subtasks")
        await self._emit_progress(
            stage="subtask_created",
            title="创建协作子任务",
            detail=f"已创建 {len(subtasks)} 个子任务。",
            status="completed",
            metadata={
                "subtasks": [
                    {
                        "id": subtask.id,
                        "type": subtask.type,
                        "assigned_agent": subtask.assigned_agent,
                    }
                    for subtask in subtasks
                ]
            },
        )

        # Step 2: Worker 执行分配的任务（并行）
        await self._emit_progress(
            stage="worker_execution",
            title="启动 Worker Agent",
            detail="正在并行执行已分配的子任务。",
            metadata={"workers": [worker.agent_id for worker in self.worker_pool]},
        )
        tasks = []
        for worker in self.worker_pool:
            task = asyncio.create_task(
                self._worker_execute_assigned_tasks(worker, shared_context)
            )
            tasks.append(task)

        # 等待所有 Worker 完成（或超时）
        timeout_occurred = False
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=90.0  # 增加超时时间到 90 秒，应对复杂案例
            )
        except asyncio.TimeoutError:
            timeout_occurred = True
            logger.warning("Swarm execution timeout (90s)")
            await self._emit_progress(
                stage="worker_execution",
                title="部分 Agent 执行超时",
                detail="已超过 Swarm Worker 等待时间，将基于已完成结果继续汇总。",
                status="warning",
            )
            # 记录哪些 Agent 已完成，哪些未完成
            completed_agents = list(shared_context.agent_contributions.keys())
            claimed_tasks = [
                (subtask.assigned_agent, subtask.type)
                for subtask in shared_context.task_decomposition.values()
                if subtask.status.value == "claimed"
            ]
            logger.info(f"Completed agents: {completed_agents}")
            logger.info(f"Timed out tasks: {claimed_tasks}")

        # Step 3: LeadAgent 汇总结果
        # 即使超时，也尝试汇总已完成的部分结果
        await self._emit_progress(
            stage="synthesis",
            title="汇总多 Agent 结果",
            detail="LeadAgent 正在整合各子任务输出。",
            metadata={"timeout_occurred": timeout_occurred},
        )
        final_answer = await self.lead_agent.synthesize_results(
            question=question,
            shared_context=shared_context,
            timeout_occurred=timeout_occurred
        )
        await self._emit_progress(
            stage="synthesis",
            title="结果汇总完成",
            detail="最终医学咨询回答已生成。",
            status="completed",
            metadata={"timeout_occurred": timeout_occurred},
        )

        end_time = datetime.now()

        # Step 4: 生成 SessionSummary
        try:
            summary = SessionSummary.from_shared_context(
                session_id=session_id,
                question=question,
                shared_context=shared_context,
                final_answer=final_answer,
                start_time=start_time,
                end_time=end_time
            )
            self.session_manager.save_summary(summary)
            await self._emit_progress(
                stage="summary",
                title="保存本地会话摘要",
                detail="已保存本地 SessionSummary。",
                status="completed",
            )
        except Exception as e:
            logger.error(f"Failed to generate session summary: {e}")
            await self._emit_progress(
                stage="summary",
                title="本地会话摘要保存失败",
                detail=str(e),
                status="warning",
            )

        # 注意：短期记忆已经在 Agent Loop 中保存了，这里不需要重复保存
        # Agent Loop 保存了完整的对话历史（user + assistant + tool messages）

        # 保存到 Mem0 长期记忆
        try:
            # 保存会话总结
            self.long_term_memory.add_session_summary(
                session_id=session_id,
                question=question,
                answer=final_answer,
                metadata={
                    "mode": "swarm",
                    "agents_count": len(shared_context.agent_contributions),
                    "total_time": (end_time - start_time).total_seconds(),
                    "timeout_occurred": timeout_occurred
                }
            )

            logger.info(f"Saved to Mem0 long-term memory (session={session_id})")
            await self._emit_progress(
                stage="memory_save",
                title="保存长期记忆",
                detail="已尝试写入 Mem0 长期记忆。",
                status="completed",
                metadata={"session_id": session_id},
            )

        except Exception as e:
            logger.error(f"Failed to save to Mem0: {e}")
            await self._emit_progress(
                stage="memory_save",
                title="长期记忆保存失败",
                detail=str(e),
                status="warning",
                metadata={"session_id": session_id},
            )

        # 发布 Swarm 完成事件
        shared_context.publish_event(Event(
            type=EventType.SWARM_COMPLETED,
            source_agent="swarm_coordinator",
            data={
                "duration": (end_time - start_time).total_seconds(),
                "agents_count": len(shared_context.agent_contributions)
            }
        ))

        await self._emit_progress(
            stage="completed",
            title="咨询处理完成",
            detail="Swarm 协作流程已完成。",
            status="completed",
            metadata={
                "agents_count": len(shared_context.agent_contributions),
                "duration": (end_time - start_time).total_seconds(),
            },
        )

        structured = structure_medical_response(
            final_answer,
            fallback_suggestions=["请遵循医嘱，注意休息和营养"],
            default_disclaimer="以上分析基于多个专业 Agent 的协作，仅供参考，不能替代医生诊断。",
        )

        # 返回结果
        completed_agents = list(shared_context.agent_contributions.keys())
        result = {
            'answer': structured.answer,
            'swarm_enabled': True,
            'session_id': session_id,
            'agents_involved': completed_agents,
            'subtasks_completed': len(shared_context.get_all_completed_subtasks()),
            'total_time': (end_time - start_time).total_seconds(),
            'swarm_metadata': shared_context.get_summary(),
            'timeout_occurred': timeout_occurred
        }

        result['suggestions'] = structured.suggestions

        # 根据是否超时调整免责声明
        if timeout_occurred and not completed_agents:
            result['disclaimer'] = "由于系统超时，未能提供完整分析。建议简化问题重试，或在紧急情况下立即就医。"
        elif timeout_occurred:
            result['disclaimer'] = f"以上分析基于 {len(completed_agents)} 个 Agent 的部分协作结果（部分分析模块超时未完成），仅供参考，不能替代医生诊断。"
        else:
            result['disclaimer'] = structured.disclaimer

        return result

    async def _worker_execute_assigned_tasks(
        self,
        worker: Any,
        shared_context: SharedContext
    ):
        """
        Worker 执行分配给它的任务

        简化后的流程：
        - 查找分配给自己的任务
        - 执行任务
        - 记录结果
        """
        try:
            # 获取分配给该 Agent 的任务
            assigned_tasks = shared_context.get_subtasks_for_agent(worker.agent_id)

            if not assigned_tasks:
                logger.debug(f"{worker.agent_id}: No assigned tasks")
                return

            # 并行执行所有分配的任务
            tasks = []
            for subtask in assigned_tasks:
                logger.info(f"{worker.agent_id}: Starting {subtask.type}")
                await self._emit_progress(
                    stage="subtask_started",
                    title=f"{worker.agent_id} 开始处理子任务",
                    detail=subtask.description,
                    metadata={
                        "agent_id": worker.agent_id,
                        "subtask_id": subtask.id,
                        "subtask_type": subtask.type,
                    },
                )
                shared_context.start_subtask(subtask.id)

                task = asyncio.create_task(
                    self._execute_single_subtask(worker, subtask, shared_context)
                )
                tasks.append(task)

            # 等待所有任务完成
            await asyncio.gather(*tasks, return_exceptions=True)

        except Exception as e:
            logger.error(f"{worker.agent_id}: Error processing subtask: {e}")

    async def _execute_single_subtask(self, worker, subtask, shared_context):
        """执行单个子任务"""
        try:
            result = await worker.process_subtask(subtask)
            shared_context.complete_subtask(subtask.id, worker.agent_id, result)
            logger.info(f"{worker.agent_id}: Completed {subtask.type}")
            await self._emit_progress(
                stage="subtask_completed",
                title=f"{worker.agent_id} 完成子任务",
                detail=subtask.description,
                status="completed",
                metadata={
                    "agent_id": worker.agent_id,
                    "subtask_id": subtask.id,
                    "subtask_type": subtask.type,
                },
            )
        except Exception as e:
            logger.error(f"{worker.agent_id}: Error in {subtask.type}: {e}")
            await self._emit_progress(
                stage="subtask_failed",
                title=f"{worker.agent_id} 子任务失败",
                detail=str(e),
                status="error",
                metadata={
                    "agent_id": worker.agent_id,
                    "subtask_id": subtask.id,
                    "subtask_type": subtask.type,
                },
            )

async def process_with_swarm(
    question: str,
    context: Optional[Dict[str, Any]] = None,
    enable_swarm: bool = True,
    session_id: Optional[str] = None,
    progress_callback: Optional[ProgressCallback] = None
) -> Dict[str, Any]:
    """
    便捷函数：使用 Swarm 处理问题

    Args:
        question: 用户问题
        context: 额外上下文
        enable_swarm: 是否启用 Swarm（False 则总是用单 Agent）
        session_id: 会话ID（如果提供，将使用该ID而不是生成新的）
        progress_callback: 可选进度事件回调，用于 SSE 输出关键运行状态

    Returns:
        处理结果
    """
    trace_token = set_trace_callback(progress_callback)
    try:
        coordinator = SwarmCoordinator(
            enable_swarm=enable_swarm,
            progress_callback=progress_callback,
        )
        return await coordinator.process(question, context, session_id=session_id)
    finally:
        reset_trace_callback(trace_token)
