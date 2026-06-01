import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import {
  Activity,
  AlertTriangle,
  ArrowUp,
  Brain,
  CheckCircle2,
  CircleAlert,
  CircleDotDashed,
  Database,
  GitBranch,
  ListChecks,
  Loader2,
  MessageSquare,
  Network,
  Plus,
  Stethoscope,
  Timer,
  Trash2,
} from "lucide-react";

type HealthStatus = {
  status?: string;
  service?: string;
  llm_configured?: boolean;
  mem0_configured?: boolean;
};

type ChatResponse = {
  answer?: string;
  disclaimer?: string;
  suggestions?: string[];
  swarm_enabled?: boolean;
  session_id?: string;
  agents_involved?: string[];
  subtasks_completed?: number;
  total_time?: number;
  timeout_occurred?: boolean;
  progress_events?: RuntimeProgressEvent[];
  status?: string;
  interview_round?: number;
  max_rounds?: number;
  covered_dimensions?: string[];
  remaining_dimensions?: string[];
  [key: string]: unknown;
};

type RuntimeProgressEvent = {
  timestamp?: string;
  stage?: string;
  title?: string;
  detail?: string;
  status?: "running" | "completed" | "warning" | "error" | string;
  metadata?: Record<string, unknown>;
};

type StreamEvent = {
  event: string;
  data: unknown;
};

type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "error";
  content: string;
  createdAt: string;
  isStreaming?: boolean;
  progressEvents?: RuntimeProgressEvent[];
  progressStatus?: string;
  response?: ChatResponse;
};

type ChatSession = {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messages: ChatMessage[];
};

const STORAGE_KEY = "medagentcare.sessions.v2";
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";
const EXAMPLE_QUESTIONS = [
  "35岁，头痛发热两天，体温38.2度，有高血压史，需要注意什么？",
  "最近一周胸闷气短，活动后更明显，偶尔出冷汗，是否需要尽快就医？",
  "糖尿病患者最近空腹血糖偏高，饮食和运动上应该如何调整？",
  "孩子咳嗽三天伴低热，没有明显呼吸困难，居家观察需要看哪些信号？",
];
const INLINE_MARKDOWN_COMPONENTS = {
  p: ({ children }: { children?: ReactNode }) => <>{children}</>,
};

function createId(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
}

function createSession(): ChatSession {
  const now = new Date().toISOString();
  return {
    id: createId("session"),
    title: "新的咨询",
    createdAt: now,
    updatedAt: now,
    messages: [],
  };
}

function isChatSession(value: unknown): value is ChatSession {
  const candidate = value as ChatSession;
  return Boolean(
    candidate &&
      typeof candidate.id === "string" &&
      typeof candidate.title === "string" &&
      Array.isArray(candidate.messages),
  );
}

function loadSessions(): ChatSession[] {
  try {
    const raw = window.localStorage?.getItem(STORAGE_KEY);
    if (!raw) return [createSession()];

    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [createSession()];
    const sessions = parsed.filter(isChatSession);
    return sessions.length > 0 ? sessions : [createSession()];
  } catch {
    return [createSession()];
  }
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatBooleanStatus(value?: boolean) {
  if (value === true) return "已配置";
  if (value === false) return "未配置";
  return "未知";
}

function firstLineTitle(text: string) {
  const normalized = text.replace(/\s+/g, " ").trim();
  if (!normalized) return "新的咨询";
  return normalized.length > 30 ? `${normalized.slice(0, 30)}...` : normalized;
}

function answerContentOnly(content: string) {
  const lines = content.split(/\r?\n/);
  const output: string[] = [];
  let skippingStructuredSection = false;

  for (const rawLine of lines) {
    const trimmed = rawLine.trim();
    const bracketHeading = trimmed.match(/^#{0,6}\s*(?:\*\*)?【(.+?)】(?:\*\*)?\s*$/);
    const plainHeading = trimmed.match(/^#{1,6}\s*(?:\*\*)?(回答|核心建议|免责声明)(?:[：:])?(?:\*\*)?\s*$/);
    const headingName = (bracketHeading?.[1] ?? plainHeading?.[1])?.replace(/[：:]/g, "").trim();

    if (headingName === "核心建议" || headingName === "免责声明") {
      skippingStructuredSection = true;
      continue;
    }

    if (headingName) {
      skippingStructuredSection = false;
      if (headingName === "回答") continue;
    }

    if (!skippingStructuredSection) {
      output.push(rawLine);
    }
  }

  return output.join("\n").trim();
}

function parseSseFrame(frame: string): StreamEvent | null {
  const lines = frame.split(/\r?\n/);
  let event = "message";
  const dataLines: string[] = [];

  for (const line of lines) {
    if (line.startsWith("event:")) {
      event = line.slice("event:".length).trim();
      continue;
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).trimStart());
    }
  }

  if (dataLines.length === 0) return null;

  try {
    return { event, data: JSON.parse(dataLines.join("\n")) };
  } catch {
    return { event, data: dataLines.join("\n") };
  }
}

function extractSseEvents(buffer: string) {
  const events: StreamEvent[] = [];
  let cursor = buffer;
  let boundaryIndex = cursor.indexOf("\n\n");

  while (boundaryIndex >= 0) {
    const frame = cursor.slice(0, boundaryIndex).trim();
    cursor = cursor.slice(boundaryIndex + 2);
    const event = parseSseFrame(frame);
    if (event) events.push(event);
    boundaryIndex = cursor.indexOf("\n\n");
  }

  return { events, remaining: cursor };
}

function formatProgressTime(value?: string) {
  if (!value) return "--:--:--";
  return new Date(value).toLocaleTimeString("zh-CN", { hour12: false });
}

function formatDuration(seconds?: number) {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds < 0) return null;
  if (seconds < 60) {
    return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)} 秒`;
  }

  const totalSeconds = Math.round(seconds);
  const minutes = Math.floor(totalSeconds / 60);
  const remainingSeconds = totalSeconds % 60;
  return remainingSeconds > 0 ? `${minutes} 分 ${remainingSeconds} 秒` : `${minutes} 分`;
}

function progressElapsedSeconds(events: RuntimeProgressEvent[], totalTimeSeconds?: number) {
  if (typeof totalTimeSeconds === "number" && Number.isFinite(totalTimeSeconds)) {
    return totalTimeSeconds;
  }

  const timestamps = events
    .map((event) => Date.parse(event.timestamp ?? ""))
    .filter((timestamp) => Number.isFinite(timestamp));
  if (timestamps.length < 2) return undefined;

  return (timestamps[timestamps.length - 1] - timestamps[0]) / 1000;
}

function progressStatusLabel(status?: string) {
  if (status === "completed") return "完成";
  if (status === "warning") return "注意";
  if (status === "error") return "失败";
  return "进行中";
}

function progressStageLabel(stage?: string) {
  const labels: Record<string, string> = {
    request_received: "请求",
    memory_lookup: "记忆",
    memory_operation: "记忆调用",
    lead_assessment: "分析",
    routing: "路由",
    subtask_created: "任务",
    worker_execution: "执行",
    subtask_started: "Agent",
    subtask_completed: "Agent",
    subtask_failed: "Agent",
    llm_call: "LLM",
    skill_call: "Skill",
    knowledge_search: "Milvus",
    web_search: "Web",
    synthesis: "汇总",
    summary: "摘要",
    memory_save: "保存",
    completed: "完成",
  };
  return stage ? labels[stage] ?? "事件" : "事件";
}

function progressIcon(stage?: string, status?: string) {
  if (status === "completed") return <CheckCircle2 size={15} />;
  if (status === "warning" || status === "error") return <CircleAlert size={15} />;
  if (status === "running") return <Loader2 size={15} className="spin" />;
  if (stage === "memory_lookup" || stage === "memory_save") return <Database size={15} />;
  if (stage === "memory_operation" || stage === "knowledge_search") return <Database size={15} />;
  if (stage === "llm_call") return <Brain size={15} />;
  if (stage === "skill_call") return <ListChecks size={15} />;
  if (stage === "web_search") return <Network size={15} />;
  if (stage === "lead_assessment") return <Brain size={15} />;
  if (stage === "routing") return <GitBranch size={15} />;
  if (stage === "subtask_created") return <ListChecks size={15} />;
  if (stage === "worker_execution" || stage?.startsWith("subtask_")) return <Network size={15} />;
  return <CircleDotDashed size={15} />;
}

function deriveProgressStatus(
  event: RuntimeProgressEvent,
  index: number,
  total: number,
  isStreaming?: boolean,
) {
  if (event.status === "completed" || event.status === "warning" || event.status === "error") {
    return event.status;
  }
  if (!isStreaming || index < total - 1) {
    return "completed";
  }
  return "running";
}

function metadataText(metadata: Record<string, unknown> | undefined, key: string) {
  const value = metadata?.[key];
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    return value.map((item) => String(item)).join(", ");
  }
  return "";
}

function traceDurationMs(event: RuntimeProgressEvent) {
  const value = event.metadata?.duration_ms;
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function progressStepClass(event: RuntimeProgressEvent & { displayStatus: string }) {
  const classes = ["progress-step", event.displayStatus];
  if (event.metadata?.trace) classes.push("trace-step");

  const durationMs = traceDurationMs(event);
  if (durationMs !== null && durationMs >= 30000) classes.push("very-slow");
  else if (durationMs !== null && durationMs >= 10000) classes.push("slow");

  return classes.join(" ");
}

function traceChips(event: RuntimeProgressEvent) {
  const metadata = event.metadata;
  if (!metadata?.trace) return [];

  const chips = [
    metadataText(metadata, "operation"),
    metadataText(metadata, "model"),
    metadataText(metadata, "skill"),
    metadataText(metadata, "provider"),
    metadataText(metadata, "tool_calls"),
  ].filter(Boolean);

  const durationMs = traceDurationMs(event);
  if (durationMs !== null) chips.unshift(`${(durationMs / 1000).toFixed(1)}s`);

  return chips.slice(0, 5);
}

function ProgressTimeline({
  events,
  status,
  isStreaming,
  totalTimeSeconds,
}: {
  events: RuntimeProgressEvent[];
  status?: string;
  isStreaming?: boolean;
  totalTimeSeconds?: number;
}) {
  const latestEvent = events.length ? events[events.length - 1] : undefined;
  const displayEvents = events.map((event, index) => ({
    ...event,
    displayStatus: deriveProgressStatus(event, index, events.length, isStreaming),
  }));
  const completedCount = displayEvents.filter((event) => event.displayStatus === "completed").length;
  const traceCount = displayEvents.filter((event) => event.metadata?.trace).length;
  const elapsedText = formatDuration(progressElapsedSeconds(events, totalTimeSeconds));
  const summaryText = latestEvent?.title ?? status ?? "等待后端返回运行进度";
  const summaryDetail = latestEvent?.detail ?? "SSE 连接建立后会显示后端关键执行事件。";
  const completedSummary = [
    `${events.length} 个事件`,
    traceCount ? `${traceCount} 个调用` : null,
    `${completedCount} 个完成`,
    elapsedText ? `耗时 ${elapsedText}` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <details className="progress-panel" open={isStreaming}>
      <summary className="progress-summary">
        <span className={`progress-summary-icon ${isStreaming ? "active" : "done"}`}>
          {isStreaming ? <Loader2 size={16} className="spin" /> : <CheckCircle2 size={16} />}
        </span>
        <span>
          <strong>{isStreaming ? summaryText : "执行轨迹"}</strong>
          <small>{isStreaming ? summaryDetail : completedSummary}</small>
        </span>
      </summary>
      <div className="progress-timeline">
        {events.length === 0 ? (
          <div className="progress-empty">
            <Timer size={16} />
            <span>{status ?? "等待后端返回运行进度"}</span>
          </div>
        ) : (
          displayEvents.map((event, index) => (
            <div className={progressStepClass(event)} key={`${event.stage}-${index}`}>
              <div className="progress-step-marker">{progressIcon(event.stage, event.displayStatus)}</div>
              <div className="progress-step-body">
                <div className="progress-step-heading">
                  <span>{progressStageLabel(event.stage)}</span>
                  <time>{formatProgressTime(event.timestamp)}</time>
                  <em>{progressStatusLabel(event.displayStatus)}</em>
                </div>
                <strong>{event.title ?? event.stage ?? "运行事件"}</strong>
                {event.detail ? <p>{event.detail}</p> : null}
                {traceChips(event).length ? (
                  <div className="trace-chip-row">
                    {traceChips(event).map((chip) => (
                      <span key={chip}>{chip}</span>
                    ))}
                  </div>
                ) : null}
              </div>
            </div>
          ))
        )}
      </div>
    </details>
  );
}

function InlineMarkdown({ children }: { children: string }) {
  return <ReactMarkdown components={INLINE_MARKDOWN_COMPONENTS}>{children}</ReactMarkdown>;
}

export default function App() {
  const [sessions, setSessions] = useState<ChatSession[]>(() => loadSessions());
  const [activeSessionId, setActiveSessionId] = useState(() => sessions[0]?.id ?? createSession().id);
  const [question, setQuestion] = useState("");
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [healthError, setHealthError] = useState("");
  const [isSending, setIsSending] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  const activeSession = useMemo(
    () => sessions.find((session) => session.id === activeSessionId) ?? sessions[0],
    [activeSessionId, sessions],
  );

  const latestResponse = [...(activeSession?.messages ?? [])]
    .reverse()
    .find((message) => message.response)?.response;

  const metrics = {
    swarm: latestResponse?.swarm_enabled ? "已启用" : latestResponse ? "单 Agent" : "待运行",
    agents: latestResponse?.agents_involved?.length ?? (latestResponse ? 1 : 0),
    subtasks: latestResponse?.subtasks_completed ?? 0,
    time: typeof latestResponse?.total_time === "number" ? `${latestResponse.total_time.toFixed(1)}s` : "--",
  };

  useEffect(() => {
    try {
      window.localStorage?.setItem(STORAGE_KEY, JSON.stringify(sessions));
    } catch {
      // 本地存储不可用时保留当前内存会话。
    }
  }, [sessions]);

  useEffect(() => {
    const controller = new AbortController();

    fetch(`${API_BASE_URL}/health`, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(`health check failed: ${response.status}`);
        return response.json();
      })
      .then((data: HealthStatus) => {
        setHealth(data);
        setHealthError("");
      })
      .catch((error: Error) => {
        if (error.name !== "AbortError") {
          setHealth(null);
          setHealthError(error.message);
        }
      });

    return () => controller.abort();
  }, []);

  function updateSession(nextSession: ChatSession) {
    setSessions((current) =>
      current.map((session) => (session.id === nextSession.id ? nextSession : session)),
    );
  }

  function patchMessage(sessionId: string, messageId: string, patch: Partial<ChatMessage>) {
    const updatedAt = new Date().toISOString();
    setSessions((current) =>
      current.map((session) =>
        session.id === sessionId
          ? {
              ...session,
              updatedAt,
              messages: session.messages.map((message) =>
                message.id === messageId ? { ...message, ...patch } : message,
              ),
            }
          : session,
      ),
    );
  }

  function startSession() {
    const session = createSession();
    setSessions((current) => [session, ...current]);
    setActiveSessionId(session.id);
    setQuestion("");
  }

  function deleteSession(sessionId: string) {
    setSessions((current) => {
      const next = current.filter((session) => session.id !== sessionId);
      if (next.length === 0) {
        const fallback = createSession();
        setActiveSessionId(fallback.id);
        return [fallback];
      }
      if (sessionId === activeSessionId) {
        setActiveSessionId(next[0].id);
      }
      return next;
    });
  }

  function selectExampleQuestion(exampleQuestion: string) {
    setQuestion(exampleQuestion);
    textareaRef.current?.focus();
  }

  async function sendQuestion() {
    if (!activeSession || !question.trim() || isSending) return;

    const submittedQuestion = question.trim();
    const now = new Date().toISOString();
    const userMessage: ChatMessage = {
      id: createId("message"),
      role: "user",
      content: submittedQuestion,
      createdAt: now,
    };

    const assistantMessageId = createId("message");
    const assistantMessage: ChatMessage = {
      id: assistantMessageId,
      role: "assistant",
      content: "",
      createdAt: now,
      isStreaming: true,
      progressEvents: [],
      progressStatus: "正在建立 SSE 连接...",
    };

    const optimisticSession: ChatSession = {
      ...activeSession,
      title: activeSession.messages.length === 0 ? firstLineTitle(submittedQuestion) : activeSession.title,
      updatedAt: now,
      messages: [...activeSession.messages, userMessage, assistantMessage],
    };

    updateSession(optimisticSession);
    setQuestion("");
    setIsSending(true);

    const controller = new AbortController();
    const progressEvents: RuntimeProgressEvent[] = [];

    try {
      const response = await fetch(`${API_BASE_URL}/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: submittedQuestion,
          context: {},
          enable_swarm: true,
          session_id: activeSession.id,
        }),
        signal: controller.signal,
      });

      if (!response.ok) {
        throw new Error(`request failed: ${response.status}`);
      }
      if (!response.body) {
        throw new Error("stream response body is empty");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const parsed = extractSseEvents(buffer);
        buffer = parsed.remaining;

        for (const streamEvent of parsed.events) {
          if (streamEvent.event === "start") {
            patchMessage(activeSession.id, assistantMessageId, {
              progressStatus: "SSE 连接已建立，等待后端事件...",
            });
            continue;
          }

          if (streamEvent.event === "progress" && typeof streamEvent.data === "object" && streamEvent.data) {
            progressEvents.push(streamEvent.data as RuntimeProgressEvent);
            const visibleEvents = progressEvents.slice(-80);
            patchMessage(activeSession.id, assistantMessageId, {
              progressEvents: visibleEvents,
              progressStatus: "正在生成最终回答...",
              response: { progress_events: visibleEvents },
            });
            continue;
          }

          if (streamEvent.event === "heartbeat") {
            const visibleEvents = progressEvents.slice(-80);
            patchMessage(activeSession.id, assistantMessageId, {
              progressEvents: visibleEvents,
              progressStatus: "后端仍在执行，请等待...",
              response: { progress_events: visibleEvents },
            });
            continue;
          }

          if (streamEvent.event === "interview_question" && typeof streamEvent.data === "object" && streamEvent.data) {
            const data = streamEvent.data as Record<string, unknown>;
            const questionText = (data.question as string) || "";
            const round = data.interview_round as number;
            const maxRounds = data.max_rounds as number;
            const covered = (data.covered_dimensions as string[]) || [];
            const remaining = (data.remaining_dimensions as string[]) || [];

            const visibleEvents = progressEvents.slice(-80);
            patchMessage(activeSession.id, assistantMessageId, {
              content: questionText,
              createdAt: new Date().toISOString(),
              isStreaming: false,
              progressEvents: visibleEvents,
              progressStatus: `第 ${round}/${maxRounds} 轮问诊 · 已覆盖: ${covered.join("、") || "无"} · 待追问: ${remaining.join("、") || "无"}`,
              response: {
                status: "need_more_info",
                progress_events: visibleEvents,
                interview_round: round,
                max_rounds: maxRounds,
                covered_dimensions: covered,
                remaining_dimensions: remaining,
              },
            });
            continue;
          }

          if (streamEvent.event === "interview_complete" && typeof streamEvent.data === "object" && streamEvent.data) {
            const data = streamEvent.data as Record<string, unknown>;
            const visibleEvents = progressEvents.slice(-80);
            patchMessage(activeSession.id, assistantMessageId, {
              progressEvents: visibleEvents,
              progressStatus: "问诊信息已完成，正在进入诊断分析...",
              response: {
                status: "interview_complete",
                progress_events: visibleEvents,
                session_id: data.session_id as string | undefined,
              },
            });
            continue;
          }

          if (streamEvent.event === "result" && typeof streamEvent.data === "object" && streamEvent.data) {
            const data = streamEvent.data as ChatResponse;
            const visibleEvents = progressEvents.slice(-80);
            patchMessage(activeSession.id, assistantMessageId, {
              content: data.answer || JSON.stringify(data, null, 2),
              createdAt: new Date().toISOString(),
              isStreaming: false,
              progressEvents: visibleEvents,
              progressStatus: "已完成",
              response: { ...data, progress_events: visibleEvents },
            });
            continue;
          }

          if (streamEvent.event === "done") {
            patchMessage(activeSession.id, assistantMessageId, {
              isStreaming: false,
              progressStatus: "已完成",
            });
            continue;
          }

          if (streamEvent.event === "error" && typeof streamEvent.data === "object" && streamEvent.data) {
            const detail = (streamEvent.data as { detail?: unknown }).detail;
            throw new Error(typeof detail === "string" ? detail : "请求失败");
          }
        }
      }
    } catch (error) {
      const content =
        error instanceof Error && error.name === "AbortError"
          ? "请求已取消。"
          : error instanceof Error
            ? error.message
            : "请求失败";
      patchMessage(activeSession.id, assistantMessageId, {
        role: "error",
        content,
        isStreaming: false,
        createdAt: new Date().toISOString(),
      });
    } finally {
      controller.abort();
      setIsSending(false);
    }
  }

  return (
    <main className="workbench-shell">
      <aside className="sidebar" aria-label="会话列表和服务状态">
        <div className="brand-block">
          <span>MedAgentCare</span>
          <h1>临床咨询工作台</h1>
        </div>

        <button className="new-button" type="button" onClick={startSession}>
          <Plus size={18} />
          新建咨询
        </button>

        <section className="recent-section">
          <h2>最近会话</h2>
          <div className="session-list">
            {sessions.map((session) => (
              <button
                className={`session-item ${session.id === activeSessionId ? "active" : ""}`}
                key={session.id}
                type="button"
                onClick={() => setActiveSessionId(session.id)}
              >
                <MessageSquare size={17} />
                <span>{session.title}</span>
                <small>{formatDate(session.updatedAt)}</small>
                <Trash2
                  aria-label="删除会话"
                  className="delete-session"
                  size={16}
                  onClick={(event) => {
                    event.stopPropagation();
                    deleteSession(session.id);
                  }}
                />
              </button>
            ))}
          </div>
        </section>

        <section className="status-section">
          <h2>服务状态</h2>
          <div className="status-card">
            <div className={`health-dot ${health?.status === "ok" ? "ok" : "error"}`} />
            <div>
              <strong>{health?.status === "ok" ? "API 已连接" : "API 未连接"}</strong>
              <span>{health?.service ?? healthError ?? API_BASE_URL}</span>
            </div>
          </div>
          <div className="status-grid">
            <div>
              <span>LLM</span>
              <strong>{formatBooleanStatus(health?.llm_configured)}</strong>
            </div>
            <div>
              <span>Mem0</span>
              <strong>{formatBooleanStatus(health?.mem0_configured)}</strong>
            </div>
          </div>
        </section>
      </aside>

      <section className="main-panel">
        <header className="app-bar">
          <div>
            <span className="section-kicker">SSE / Clinical Stream</span>
            <h2>{activeSession?.title ?? "新的咨询"}</h2>
          </div>
          <div className="runtime-strip" aria-label="最近一次运行概览">
            <div>
              <span>模式</span>
              <strong>{metrics.swarm}</strong>
            </div>
            <div>
              <span>Agent</span>
              <strong>{metrics.agents}</strong>
            </div>
            <div>
              <span>子任务</span>
              <strong>{metrics.subtasks}</strong>
            </div>
            <div>
              <span>耗时</span>
              <strong>{metrics.time}</strong>
            </div>
          </div>
        </header>

        <div className="chat-container">
          {activeSession?.messages.length === 0 ? (
            <div className="empty-state">
              <div className="empty-icon">
                <Stethoscope size={30} />
              </div>
              <h3>输入真实症状与背景，查看流式分析过程</h3>
              <p>建议包含年龄、持续时间、严重程度、既往病史和已用药情况。高危症状应优先线下就医。</p>
              <div className="example-grid" aria-label="示例医学问题">
                {EXAMPLE_QUESTIONS.map((exampleQuestion) => (
                  <button
                    className="example-card"
                    key={exampleQuestion}
                    type="button"
                    onClick={() => selectExampleQuestion(exampleQuestion)}
                  >
                    {exampleQuestion}
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          <div className="message-flow">
            {activeSession?.messages.map((message) => (
              <article className={`message-row ${message.role}`} key={message.id}>
                {message.role !== "user" ? (
                  <div className="assistant-avatar">
                    {message.role === "error" ? <AlertTriangle size={17} /> : <Activity size={17} />}
                  </div>
                ) : null}
                <div className="message-card">
                  <div className="message-meta">
                    <span>{message.role === "user" ? "用户" : message.role === "assistant" ? "MedAgentCare" : "错误"}</span>
                    <time>{formatDate(message.createdAt)}</time>
                  </div>
                  {message.role === "assistant" ? (
                    <ProgressTimeline
                      events={message.progressEvents ?? message.response?.progress_events ?? []}
                      isStreaming={message.isStreaming}
                      status={message.progressStatus}
                      totalTimeSeconds={message.response?.total_time}
                    />
                  ) : null}
                  <div className={`message-content ${message.role === "assistant" && message.content ? "message-answer" : ""}`}>
                    {message.role === "assistant" ? (
                      message.content ? (
                        <ReactMarkdown>{answerContentOnly(message.content)}</ReactMarkdown>
                      ) : null
                    ) : (
                      <p>{message.content}</p>
                    )}
                  </div>
                  {message.response?.suggestions?.length ? (
                    <div className="suggestion-list">
                      <strong>核心建议</strong>
                      {message.response.suggestions.map((item, index) => (
                        <span key={`${item}-${index}`}>
                          <InlineMarkdown>{item}</InlineMarkdown>
                        </span>
                      ))}
                    </div>
                  ) : null}
                  {message.response?.disclaimer ? (
                    <div className="message-disclaimer">
                      <AlertTriangle size={15} />
                      <span>
                        <InlineMarkdown>{message.response.disclaimer}</InlineMarkdown>
                      </span>
                    </div>
                  ) : null}
                </div>
              </article>
            ))}

            {isSending ? (
              <div className="loading-row">
                <Loader2 size={18} className="spin" />
                正在等待后端流式事件
              </div>
            ) : null}
          </div>
        </div>

        <footer className="prompt-dock">
          <div className="prompt-container">
            <textarea
              ref={textareaRef}
              placeholder="请输入症状、年龄、持续时间、体温、既往史或医学问题..."
              rows={1}
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                  sendQuestion();
                }
              }}
            />
            <button className="send-button" type="button" disabled={!question.trim() || isSending} onClick={sendQuestion}>
              {isSending ? <Loader2 size={18} className="spin" /> : <ArrowUp size={18} strokeWidth={2.5} />}
              <span>发送</span>
            </button>
          </div>
        </footer>
      </section>
    </main>
  );
}
