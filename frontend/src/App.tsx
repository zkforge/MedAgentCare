import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import {
  AlertTriangle,
  Brain,
  Clipboard,
  Github,
  HeartPulse,
  Loader2,
  MessageSquare,
  MessageSquarePlus,
  Plus,
  Send,
  Stethoscope,
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
  swarm_metadata?: Record<string, unknown>;
  progress_events?: RuntimeProgressEvent[];
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
  response?: ChatResponse;
};

type ChatSession = {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messages: ChatMessage[];
};

const STORAGE_KEY = "medagentcare.sessions.v1";
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";
const EXAMPLE_QUESTIONS = [
  "35岁，头痛发热两天，体温38.2度，有高血压史，需要注意什么？",
  "最近一周胸闷气短，活动后更明显，偶尔出冷汗，是否需要尽快就医？",
  "糖尿病患者最近空腹血糖偏高，饮食和运动上应该如何调整？",
  "孩子咳嗽三天伴低热，没有明显呼吸困难，居家观察需要看哪些信号？",
  "长期失眠、白天乏力，最近压力较大，有哪些可能原因和改善建议？",
  "体检发现血压偏高，平时没有症状，下一步应该怎么管理？",
];

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

function loadSessions(): ChatSession[] {
  try {
    const raw = window.localStorage?.getItem(STORAGE_KEY);
    if (!raw) return [createSession()];

    const parsed = JSON.parse(raw) as ChatSession[];
    return parsed.length > 0 ? parsed : [createSession()];
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

function summarizeResponse(response?: ChatResponse) {
  if (!response) return {};
  return {
    agents_involved: response.agents_involved ?? [],
    subtasks_completed: response.subtasks_completed ?? 0,
    total_time: response.total_time ?? null,
    timeout_occurred: response.timeout_occurred ?? false,
    swarm_enabled: response.swarm_enabled ?? false,
  };
}

function firstLineTitle(text: string) {
  const normalized = text.replace(/\s+/g, " ").trim();
  if (!normalized) return "新的咨询";
  return normalized.length > 30 ? `${normalized.slice(0, 30)}...` : normalized;
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

function formatProgressEvent(event: RuntimeProgressEvent) {
  const timestamp = event.timestamp
    ? new Date(event.timestamp).toLocaleTimeString("zh-CN", { hour12: false })
    : "--:--:--";
  const statusText =
    event.status === "completed"
      ? "完成"
      : event.status === "warning"
        ? "注意"
        : event.status === "error"
          ? "失败"
          : "进行中";
  const title = event.title ?? event.stage ?? "运行事件";
  const detail = event.detail ? `：${event.detail}` : "";
  return `- ${timestamp} [${statusText}] ${title}${detail}`;
}

function buildStreamingContent(
  progressEvents: RuntimeProgressEvent[],
  status: string,
  answer?: string,
) {
  const progressLines = progressEvents.map(formatProgressEvent);
  const progressBlock = progressLines.length
    ? progressLines.join("\n")
    : "- 等待后端返回运行进度...";
  if (answer) {
    return `### 运行进度\n\n${progressBlock}\n\n### 最终回答\n\n${answer}`;
  }
  return `### 运行进度\n\n${progressBlock}\n\n${status}`;
}

export default function App() {
  const [sessions, setSessions] = useState<ChatSession[]>(() => loadSessions());
  const [activeSessionId, setActiveSessionId] = useState(() => sessions[0]?.id ?? createSession().id);
  const [question, setQuestion] = useState("");
  const [enableSwarm, setEnableSwarm] = useState(false);
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
    swarm: latestResponse?.swarm_enabled ?? false,
    agents: latestResponse?.agents_involved?.length ?? (latestResponse ? 1 : 0),
    subtasks: latestResponse?.subtasks_completed ?? 0,
    time: typeof latestResponse?.total_time === "number" ? `${latestResponse.total_time.toFixed(1)}s` : "0.0s",
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
      content: buildStreamingContent([], "正在建立 SSE 连接..."),
      createdAt: now,
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
          enable_swarm: enableSwarm,
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
          if (streamEvent.event === "progress" && typeof streamEvent.data === "object" && streamEvent.data) {
            progressEvents.push(streamEvent.data as RuntimeProgressEvent);
            const visibleEvents = progressEvents.slice(-80);
            patchMessage(
              activeSession.id,
              assistantMessageId,
              {
                content: buildStreamingContent(visibleEvents, "正在生成最终回答..."),
                response: { progress_events: visibleEvents },
              },
            );
            continue;
          }

          if (streamEvent.event === "heartbeat") {
            const visibleEvents = progressEvents.slice(-80);
            patchMessage(activeSession.id, assistantMessageId, {
              content: buildStreamingContent(visibleEvents, "后端仍在执行，请等待..."),
              response: { progress_events: visibleEvents },
            });
            continue;
          }

          if (streamEvent.event === "result" && typeof streamEvent.data === "object" && streamEvent.data) {
            const data = streamEvent.data as ChatResponse;
            const visibleEvents = progressEvents.slice(-80);
            patchMessage(activeSession.id, assistantMessageId, {
              content: buildStreamingContent(
                visibleEvents,
                "已完成",
                data.answer || JSON.stringify(data, null, 2),
              ),
              createdAt: new Date().toISOString(),
              response: { ...data, progress_events: visibleEvents },
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
        createdAt: new Date().toISOString(),
      });
    } finally {
      controller.abort();
      setIsSending(false);
    }
  }

  return (
    <main className="workbench-shell">
      <aside className="sidebar">
        <div className="brand-block">
          <h1>MedAgentCare</h1>
          <p>临床咨询工作台</p>
        </div>

        <button className="new-button" type="button" onClick={startSession}>
          <Plus size={19} />
          新建咨询
        </button>

        <section className="recent-section">
          <h2>最近会话</h2>
          <div className="session-list">
            {sessions.length === 0 ? (
              <p className="empty-recent">暂无最近会话</p>
            ) : (
              sessions.map((session) => (
                <button
                  className={`session-item ${session.id === activeSessionId ? "active" : ""}`}
                  key={session.id}
                  type="button"
                  onClick={() => setActiveSessionId(session.id)}
                >
                  <MessageSquare size={18} />
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
              ))
            )}
          </div>
        </section>
      </aside>

      <section className="main-panel">
        <header className="app-bar">
          <div>
            <h2>医疗咨询工作台</h2>
          </div>
          <a className="github-link" href="https://github.com" target="_blank" rel="noreferrer" aria-label="打开 GitHub">
            <Github size={20} />
          </a>
        </header>

        <div className="chat-container">
          {activeSession?.messages.length === 0 ? (
            <div className="empty-state">
              <div className="empty-icon">
                <Stethoscope size={32} />
              </div>
              <h3>今天想咨询什么健康问题？</h3>
              <p>输入症状、持续时间、既往史或医学问题，开始一次 AI 辅助咨询。</p>
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
                    <Stethoscope size={18} />
                  </div>
                ) : null}
                <div className="message-card">
                  <div className="message-meta">
                    <span>{message.role === "user" ? "用户" : message.role === "assistant" ? "MedAgentCare" : "错误"}</span>
                    <time>{formatDate(message.createdAt)}</time>
                  </div>
                  <div className="message-content">
                    {message.role === "assistant" ? <ReactMarkdown>{message.content}</ReactMarkdown> : <p>{message.content}</p>}
                  </div>
                  {message.response?.suggestions?.length ? (
                    <div className="suggestion-list">
                      {message.response.suggestions.map((item, index) => (
                        <span key={`${item}-${index}`}>{item}</span>
                      ))}
                    </div>
                  ) : null}
                  {message.response?.disclaimer ? (
                    <div className="message-disclaimer">
                      <AlertTriangle size={15} />
                      {message.response.disclaimer}
                    </div>
                  ) : null}
                </div>
              </article>
            ))}

            {isSending ? (
              <div className="loading-row">
                <Loader2 size={18} className="spin" />
                正在等待 Agent 响应
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
            <div className="prompt-footer">
              <label className="swarm-control">
                <span>启用 Swarm 协作</span>
                <input
                  checked={enableSwarm}
                  type="checkbox"
                  onChange={(event) => setEnableSwarm(event.target.checked)}
                />
              </label>
              <button className="send-button" type="button" disabled={!question.trim() || isSending} onClick={sendQuestion}>
                {isSending ? <Loader2 size={18} className="spin" /> : <Send size={18} />}
                发送
              </button>
            </div>
          </div>
        </footer>
      </section>

      <aside className="details-panel">
        <div className="details-heading">
          <h2>详情</h2>
          <p>运行配置</p>
        </div>

        <section className="details-section">
          <div className="section-title">
            <HeartPulse size={15} />
            服务健康状态
            <span className={`status-dot ${health?.status === "ok" ? "ok" : "error"}`} />
          </div>
          <div className="health-card">
            <span>API 状态</span>
            <strong className={health?.status === "ok" ? "ok-text" : "error-text"}>
              {health?.status === "ok" ? "可用" : healthError ? "未连接" : "检查中..."}
            </strong>
          </div>
          <div className="health-card">
            <span>LLM 连接</span>
            <strong className={health?.llm_configured ? "ok-text" : "muted-text"}>
              {health?.llm_configured ? "已配置" : "未配置"}
            </strong>
          </div>
          <div className="health-card">
            <span>Mem0 记忆</span>
            <strong className={health?.mem0_configured ? "ok-text" : "muted-text"}>
              {health?.mem0_configured ? "已启用" : "未启用"}
            </strong>
          </div>
        </section>

        <section className="details-section">
          <div className="section-title">
            <Brain size={15} />
            指标
          </div>
          <div className="metric-grid">
            <div>
              <p>Swarm</p>
              <strong>{metrics.swarm ? "已启用" : "关闭"}</strong>
            </div>
            <div>
              <p>Agent</p>
              <strong>{metrics.agents}</strong>
            </div>
            <div>
              <p>子任务</p>
              <strong>{metrics.subtasks}</strong>
            </div>
            <div>
              <p>耗时</p>
              <strong>{metrics.time}</strong>
            </div>
          </div>
        </section>

        <section className="inspect-section">
          <div className="section-title">
            <Clipboard size={15} />
            检查
          </div>
          <div className="json-card">
            <div className="json-card-header">
              <span>ID: {activeSession?.id ?? "无"}</span>
            </div>
            <pre>{JSON.stringify(latestResponse ? summarizeResponse(latestResponse) : {}, null, 2)}</pre>
          </div>
        </section>
      </aside>
    </main>
  );
}
