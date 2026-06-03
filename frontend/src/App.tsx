import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import {
  Activity,
  AlertTriangle,
  ArrowUp,
  ChevronDown,
  ChevronRight,
  CheckCircle2,
  Database,
  Brain,
  GitBranch,
  ListChecks,
  Loader2,
  MessageSquare,
  Plus,
  Stethoscope,
  Trash2,
} from "lucide-react";

type HealthStatus = {
  status?: string;
  service?: string;
  llm_configured?: boolean;
  mem0_configured?: boolean;
  memory_enabled?: boolean;
  memory_default_backend?: string;
};

type MemoryBackend = "local" | "mem0";

type MemoryPreferences = {
  enabled: boolean;
  backend: MemoryBackend;
};

type MemoryStatus = {
  enabled?: boolean;
  default_backend?: string;
  user_id?: string;
  mem0_configured?: boolean;
  local?: {
    memory_dir?: string;
    raw_count?: number;
    summary_count?: number;
    max_sessions?: number;
  };
};

type MemorySummaryPreview = {
  title: string;
  summary: string;
  tags: string[];
  urgency: string;
  timeline: string;
  care_recommendation: string;
  profile_candidates: Array<{
    type?: string;
    value?: string;
    evidence?: string;
    confidence?: string;
  }>;
};

type MemoryIndexSnapshot = {
  summaries?: Array<{
    session_id?: string;
    title?: string;
    confirmed_at?: string;
    tags?: string[];
  }>;
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
  memory?: {
    effective_enabled?: boolean;
    backend?: string;
    raw_session_saved?: boolean;
    raw_session_error?: string | null;
  };
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

type StreamChannel = "reasoning" | "answer";

type StreamTranscript = {
  reasoning: string;
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
  streamTranscript?: StreamTranscript;
  reasoningExpanded?: boolean;
  response?: ChatResponse;
};

type ChatSession = {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messages: ChatMessage[];
};

const ACTIVE_SESSION_KEY = "medagentcare.activeSession.v1";
const MEMORY_PREF_KEY = "medagentcare.memory.preferences.v1";
const REASONING_CACHE_KEY = "medagentcare.reasoning.cache.v1";
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

type ReasoningCacheEntry = {
  question: string;
  answer: string;
  reasoning: string;
  updatedAt: string;
};

type ReasoningCache = Record<string, ReasoningCacheEntry[]>;

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

function loadMemoryPreferences(): MemoryPreferences {
  try {
    const raw = window.localStorage?.getItem(MEMORY_PREF_KEY);
    if (!raw) return { enabled: false, backend: "local" };
    const parsed = JSON.parse(raw) as Partial<MemoryPreferences>;
    return {
      enabled: parsed.enabled === true,
      backend: parsed.backend === "mem0" ? "mem0" : "local",
    };
  } catch {
    return { enabled: false, backend: "local" };
  }
}

function loadActiveSessionId() {
  try {
    return window.localStorage?.getItem(ACTIVE_SESSION_KEY) || "";
  } catch {
    return "";
  }
}

function loadReasoningCache(): ReasoningCache {
  try {
    const raw = window.localStorage?.getItem(REASONING_CACHE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as ReasoningCache;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function saveReasoningCacheEntry(sessionId: string, entry: ReasoningCacheEntry) {
  try {
    const cache = loadReasoningCache();
    const entries = (cache[sessionId] ?? []).filter(
      (item) => !(item.question === entry.question && item.answer === entry.answer),
    );
    cache[sessionId] = [...entries, entry].slice(-40);
    window.localStorage?.setItem(REASONING_CACHE_KEY, JSON.stringify(cache));
  } catch {
    // 推理过程缓存只用于前端展示，失败不影响咨询流程。
  }
}

function deleteReasoningCacheSession(sessionId: string) {
  try {
    const cache = loadReasoningCache();
    delete cache[sessionId];
    window.localStorage?.setItem(REASONING_CACHE_KEY, JSON.stringify(cache));
  } catch {
    // 缓存清理失败不影响后端会话删除。
  }
}

function enrichSessionWithReasoning(session: ChatSession): ChatSession {
  const entries = loadReasoningCache()[session.id] ?? [];
  if (entries.length === 0) return session;

  return {
    ...session,
    messages: session.messages.map((message, index) => {
      if (message.role !== "assistant" || message.streamTranscript?.reasoning) return message;
      const previousUser = [...session.messages.slice(0, index)].reverse().find((item) => item.role === "user");
      const answer = message.content || message.response?.answer || "";
      const cached = [...entries]
        .reverse()
        .find((entry) => entry.question === previousUser?.content && entry.answer === answer);
      if (!cached?.reasoning) return message;
      return {
        ...message,
        streamTranscript: { reasoning: cached.reasoning },
        reasoningExpanded: message.reasoningExpanded ?? false,
      };
    }),
  };
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
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

function formatProcessingDuration(seconds?: number) {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds < 0) return "";
  const totalSeconds = Math.max(1, Math.round(seconds));
  if (totalSeconds < 60) return `${totalSeconds}s`;

  const minutes = Math.floor(totalSeconds / 60);
  const remainingSeconds = totalSeconds % 60;
  return remainingSeconds > 0 ? `${minutes}m ${remainingSeconds}s` : `${minutes}m`;
}

function progressElapsedSeconds(events?: RuntimeProgressEvent[], totalTimeSeconds?: number) {
  if (typeof totalTimeSeconds === "number" && Number.isFinite(totalTimeSeconds)) {
    return totalTimeSeconds;
  }
  if (!events?.length) return undefined;

  const timestamps = events
    .map((event) => Date.parse(event.timestamp ?? ""))
    .filter((timestamp) => Number.isFinite(timestamp));
  if (timestamps.length < 2) return undefined;

  return (timestamps[timestamps.length - 1] - timestamps[0]) / 1000;
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

function InlineMarkdown({ children }: { children: string }) {
  return <ReactMarkdown components={INLINE_MARKDOWN_COMPONENTS}>{children}</ReactMarkdown>;
}

function reasoningLineIcon(text: string) {
  if (/收到|咨询请求/.test(text)) return <MessageSquare size={14} />;
  if (/记忆|会话历史|长期/.test(text)) return <Database size={14} />;
  if (/模型|LLM|finish_reason|tool_calls|stop|字符|用时/.test(text)) return <Brain size={14} />;
  if (/路由|Agent|LeadAgent|子任务|协作|Swarm|consultation_agent/.test(text)) return <GitBranch size={14} />;
  if (/Skill|assess_|search_|调用/.test(text)) return <ListChecks size={14} />;
  if (/完成|已处理|返回|生成/.test(text)) return <CheckCircle2 size={14} />;
  return <Stethoscope size={14} />;
}

function ReasoningBlock({
  message,
  onToggle,
}: {
  message: ChatMessage;
  onToggle: () => void;
}) {
  const text = message.streamTranscript?.reasoning ?? "";
  if (!text.trim()) return null;
  const lines = text.split(/\r?\n/).filter((line, index, allLines) => {
    if (line) return true;
    return message.isStreaming && index === allLines.length - 1;
  });

  const expanded = message.isStreaming || message.reasoningExpanded === true;
  const elapsed = formatProcessingDuration(
    progressElapsedSeconds(message.progressEvents ?? message.response?.progress_events, message.response?.total_time),
  );
  const collapsedLabel = `已处理${elapsed ? ` ${elapsed}` : ""}`;

  return (
    <section className={`reasoning-block ${expanded ? "expanded" : "collapsed"}`}>
      <button
        className="reasoning-toggle"
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
      >
        <span>
          {message.isStreaming ? <Loader2 size={15} className="spin" /> : <CheckCircle2 size={15} />}
          {message.isStreaming ? "推理中" : collapsedLabel}
        </span>
        {expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
      </button>
      {expanded ? (
        <div className="reasoning-content">
          {lines.map((line, index) => {
            const isLastLine = index === lines.length - 1;

            return (
              <div className="reasoning-line" key={`${line}-${index}`}>
                <span className="reasoning-line-icon" aria-hidden="true">
                  {line ? reasoningLineIcon(line) : <Loader2 size={14} className="spin" />}
                </span>
                <span>
                  {line}
                  {message.isStreaming && isLastLine ? <b aria-hidden="true" /> : null}
                </span>
              </div>
            );
          })}
        </div>
      ) : null}
    </section>
  );
}

export default function App() {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState(() => loadActiveSessionId());
  const [question, setQuestion] = useState("");
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [healthError, setHealthError] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [memoryPrefs, setMemoryPrefs] = useState<MemoryPreferences>(() => loadMemoryPreferences());
  const [memoryStatus, setMemoryStatus] = useState<MemoryStatus | null>(null);
  const [memoryError, setMemoryError] = useState("");
  const [memoryActionStatus, setMemoryActionStatus] = useState("");
  const [memoryPreviews, setMemoryPreviews] = useState<Record<string, MemorySummaryPreview>>({});
  const [confirmedMemorySessions, setConfirmedMemorySessions] = useState<Record<string, true>>({});
  const [isMemoryPreviewOpen, setIsMemoryPreviewOpen] = useState(false);
  const [isGeneratingMemorySummary, setIsGeneratingMemorySummary] = useState(false);
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
  const latestSessionId = latestResponse?.session_id;
  const latestMemoryPreview = latestSessionId ? memoryPreviews[latestSessionId] : undefined;
  const isCurrentMemorySaved = Boolean(latestSessionId && confirmedMemorySessions[latestSessionId]);
  const currentMemoryStatus = latestMemoryPreview ? "待确认" : isCurrentMemorySaved ? "已保存" : "本次未保存";
  const canOpenMemorySummary =
    Boolean(memoryPrefs.enabled && latestSessionId && latestResponse?.memory?.raw_session_saved) &&
    !isCurrentMemorySaved &&
    !isGeneratingMemorySummary;

  useEffect(() => {
    try {
      if (activeSessionId) {
        window.localStorage?.setItem(ACTIVE_SESSION_KEY, activeSessionId);
      }
    } catch {
      // 当前会话指针保存失败不影响会话文件本身。
    }
  }, [activeSessionId]);

  useEffect(() => {
    try {
      window.localStorage?.setItem(MEMORY_PREF_KEY, JSON.stringify(memoryPrefs));
    } catch {
      // 偏好保存失败不影响本次使用。
    }
  }, [memoryPrefs]);

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

    refreshMemoryStatus(controller.signal);
    refreshConfirmedMemorySessions(controller.signal);
    refreshSessions(controller.signal);

    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!activeSessionId) return;
    const session = sessions.find((item) => item.id === activeSessionId);
    if (!session || session.messages.length > 0) return;
    const controller = new AbortController();
    loadSessionDetails(activeSessionId, controller.signal);
    return () => controller.abort();
  }, [activeSessionId]);

  async function refreshSessions(signal?: AbortSignal) {
    try {
      const response = await fetch(`${API_BASE_URL}/sessions`, { signal });
      if (!response.ok) throw new Error(`sessions failed: ${response.status}`);
      const data = (await response.json()) as { sessions?: ChatSession[] };
      let nextSessions = data.sessions ?? [];

      if (nextSessions.length === 0) {
        const created = await createBackendSession(signal);
        nextSessions = [created];
      }

      const storedActive = loadActiveSessionId();
      const nextActive = nextSessions.some((session) => session.id === storedActive)
        ? storedActive
        : nextSessions[0]?.id ?? "";
      setSessions(nextSessions);
      setActiveSessionId(nextActive);
      if (nextActive) {
        await loadSessionDetails(nextActive, signal);
      }
      setHealthError("");
    } catch (error) {
      if (error instanceof Error && error.name === "AbortError") return;
      setHealthError(error instanceof Error ? error.message : "会话列表读取失败");
      if (sessions.length === 0) {
        const fallback = createSession();
        setSessions([fallback]);
        setActiveSessionId(fallback.id);
      }
    }
  }

  async function createBackendSession(signal?: AbortSignal) {
    const response = await fetch(`${API_BASE_URL}/sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: "新的咨询" }),
      signal,
    });
    if (!response.ok) throw new Error(`session create failed: ${response.status}`);
    return (await response.json()) as ChatSession;
  }

  async function loadSessionDetails(sessionId: string, signal?: AbortSignal) {
    try {
      const response = await fetch(`${API_BASE_URL}/sessions/${encodeURIComponent(sessionId)}`, { signal });
      if (!response.ok) throw new Error(`session load failed: ${response.status}`);
      const session = (await response.json()) as ChatSession;
      updateSession(enrichSessionWithReasoning(session));
    } catch (error) {
      if (error instanceof Error && error.name === "AbortError") return;
      setHealthError(error instanceof Error ? error.message : "会话读取失败");
    }
  }

  function updateSession(nextSession: ChatSession) {
    setSessions((current) =>
      current.some((session) => session.id === nextSession.id)
        ? current.map((session) => (session.id === nextSession.id ? nextSession : session))
        : [nextSession, ...current],
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

  function toggleReasoning(sessionId: string, messageId: string) {
    const updatedAt = new Date().toISOString();
    setSessions((current) =>
      current.map((session) =>
        session.id === sessionId
          ? {
              ...session,
              updatedAt,
              messages: session.messages.map((message) =>
                message.id === messageId
                  ? { ...message, reasoningExpanded: !(message.reasoningExpanded ?? false) }
                  : message,
              ),
            }
          : session,
      ),
    );
  }

  async function startSession() {
    try {
      const session = await createBackendSession();
      setSessions((current) => [session, ...current.filter((item) => item.id !== session.id)]);
      setActiveSessionId(session.id);
      setQuestion("");
    } catch (error) {
      setHealthError(error instanceof Error ? error.message : "新建会话失败");
    }
  }

  async function deleteSession(sessionId: string) {
    try {
      const response = await fetch(`${API_BASE_URL}/sessions/${encodeURIComponent(sessionId)}`, {
        method: "DELETE",
      });
      if (!response.ok) throw new Error(`session delete failed: ${response.status}`);
      deleteReasoningCacheSession(sessionId);
      setMemoryPreviews((current) => {
        const next = { ...current };
        delete next[sessionId];
        return next;
      });
      setConfirmedMemorySessions((current) => {
        const next = { ...current };
        delete next[sessionId];
        return next;
      });
      await refreshMemoryStatus();
      await refreshConfirmedMemorySessions();
    } catch (error) {
      setHealthError(error instanceof Error ? error.message : "删除会话失败");
      return;
    }

    setSessions((current) => {
      const next = current.filter((session) => session.id !== sessionId);
      if (next.length === 0) {
        void startSession();
        return [];
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

  async function refreshMemoryStatus(signal?: AbortSignal) {
    try {
      const response = await fetch(`${API_BASE_URL}/memory/status`, { signal });
      if (!response.ok) throw new Error(`memory status failed: ${response.status}`);
      const data = (await response.json()) as MemoryStatus;
      setMemoryStatus(data);
      setMemoryError("");
    } catch (error) {
      if (error instanceof Error && error.name === "AbortError") return;
      setMemoryError(error instanceof Error ? error.message : "记忆状态读取失败");
    }
  }

  async function refreshConfirmedMemorySessions(signal?: AbortSignal) {
    try {
      const response = await fetch(`${API_BASE_URL}/memory/local`, { signal });
      if (!response.ok) throw new Error(`memory list failed: ${response.status}`);
      const data = (await response.json()) as MemoryIndexSnapshot;
      const confirmed = (data.summaries ?? []).reduce<Record<string, true>>((acc, item) => {
        if (item.session_id) acc[item.session_id] = true;
        return acc;
      }, {});
      setConfirmedMemorySessions(confirmed);
    } catch (error) {
      if (error instanceof Error && error.name === "AbortError") return;
      setMemoryError(error instanceof Error ? error.message : "记忆索引读取失败");
    }
  }

  async function openMemorySummaryDialog() {
    if (!latestSessionId || !canOpenMemorySummary) return;
    if (latestMemoryPreview) {
      setIsMemoryPreviewOpen(true);
      return;
    }

    setIsGeneratingMemorySummary(true);
    setMemoryActionStatus("正在生成记忆摘要...");
    try {
      const response = await fetch(`${API_BASE_URL}/memory/sessions/${encodeURIComponent(latestSessionId)}/summary/generate`, {
        method: "POST",
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(typeof payload.detail === "string" ? payload.detail : `summary failed: ${response.status}`);
      }
      const data = (await response.json()) as { summary?: MemorySummaryPreview };
      if (!data.summary) throw new Error("摘要生成结果为空");
      setMemoryPreviews((current) => ({ ...current, [latestSessionId]: data.summary as MemorySummaryPreview }));
      setIsMemoryPreviewOpen(true);
      setMemoryActionStatus("摘要已生成，等待确认");
    } catch (error) {
      setMemoryActionStatus(error instanceof Error ? error.message : "摘要生成失败，可重试");
    } finally {
      setIsGeneratingMemorySummary(false);
    }
  }

  async function confirmMemorySummary() {
    if (!latestSessionId || !latestMemoryPreview) return;
    setMemoryActionStatus("正在保存长期记忆...");
    try {
      const response = await fetch(`${API_BASE_URL}/memory/sessions/${encodeURIComponent(latestSessionId)}/summary/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          backend: memoryPrefs.backend,
          summary: latestMemoryPreview,
        }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(typeof payload.detail === "string" ? payload.detail : `confirm failed: ${response.status}`);
      }
      setMemoryPreviews((current) => {
        const next = { ...current };
        delete next[latestSessionId];
        return next;
      });
      setIsMemoryPreviewOpen(false);
      setMemoryActionStatus("长期记忆已保存");
      await refreshMemoryStatus();
      await refreshConfirmedMemorySessions();
      setConfirmedMemorySessions((current) => ({ ...current, [latestSessionId]: true }));
    } catch (error) {
      setMemoryActionStatus(error instanceof Error ? error.message : "保存失败，可重试");
    }
  }

  function cancelMemorySummary() {
    if (!latestSessionId) return;
    setMemoryPreviews((current) => {
      const next = { ...current };
      delete next[latestSessionId];
      return next;
    });
    setIsMemoryPreviewOpen(false);
    setMemoryActionStatus("已取消保存");
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
      streamTranscript: { reasoning: "" },
      reasoningExpanded: true,
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
    let streamTranscript: StreamTranscript = { reasoning: "" };
    let streamedAnswer = "";
    let reasoningBuffer = "";
    let answerBuffer = "";

    const takeBufferedChars = (length: number) => {
      if (length > 600) return 64;
      if (length > 240) return 24;
      if (length > 80) return 8;
      return 1;
    };

    const flushStreamBuffers = (force = false) => {
      const patch: Partial<ChatMessage> = {};

      if (reasoningBuffer) {
        const count = force ? reasoningBuffer.length : Math.min(reasoningBuffer.length, takeBufferedChars(reasoningBuffer.length));
        streamTranscript = {
          reasoning: streamTranscript.reasoning + reasoningBuffer.slice(0, count),
        };
        reasoningBuffer = reasoningBuffer.slice(count);
        patch.streamTranscript = streamTranscript;
        patch.reasoningExpanded = true;
        patch.progressStatus = "正在生成推理过程...";
      }

      if (answerBuffer) {
        const count = force ? answerBuffer.length : Math.min(answerBuffer.length, takeBufferedChars(answerBuffer.length));
        streamedAnswer += answerBuffer.slice(0, count);
        answerBuffer = answerBuffer.slice(count);
        patch.content = streamedAnswer;
        patch.progressStatus = "正在输出最终回答...";
      }

      if (Object.keys(patch).length > 0) {
        patchMessage(activeSession.id, assistantMessageId, patch);
      }
    };

    const persistReasoning = (answer: string) => {
      if (!streamTranscript.reasoning.trim() || !answer.trim()) return;
      saveReasoningCacheEntry(activeSession.id, {
        question: submittedQuestion,
        answer,
        reasoning: streamTranscript.reasoning,
        updatedAt: new Date().toISOString(),
      });
    };

    const typewriterTimer = window.setInterval(() => flushStreamBuffers(false), 16);

    try {
      const response = await fetch(`${API_BASE_URL}/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: submittedQuestion,
          context: {},
          enable_swarm: true,
          session_id: activeSession.id,
          memory: {
            enabled: memoryPrefs.enabled,
            backend: memoryPrefs.backend,
          },
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
            continue;
          }

          if (streamEvent.event === "stream_delta" && typeof streamEvent.data === "object" && streamEvent.data) {
            const data = streamEvent.data as { channel?: unknown; delta?: unknown };
            const channel = data.channel as StreamChannel;
            const delta = typeof data.delta === "string" ? data.delta : "";
            if (!delta || !["reasoning", "answer"].includes(channel)) continue;

            if (channel === "answer") {
              answerBuffer += delta;
              continue;
            }

            reasoningBuffer += delta;
            continue;
          }

          if (streamEvent.event === "heartbeat") {
            patchMessage(activeSession.id, assistantMessageId, {
              progressStatus: "后端仍在执行，请等待...",
            });
            continue;
          }

          if (streamEvent.event === "interview_question" && typeof streamEvent.data === "object" && streamEvent.data) {
            flushStreamBuffers(true);
            const data = streamEvent.data as Record<string, unknown>;
            const questionText = (data.question as string) || "";
            const round = data.interview_round as number;
            const maxRounds = data.max_rounds as number;
            const covered = (data.covered_dimensions as string[]) || [];
            const remaining = (data.remaining_dimensions as string[]) || [];

            const visibleEvents = progressEvents.slice(-80);
            const finalQuestionText = streamedAnswer || questionText;
            persistReasoning(questionText || finalQuestionText);
            patchMessage(activeSession.id, assistantMessageId, {
              content: finalQuestionText,
              createdAt: new Date().toISOString(),
              isStreaming: false,
              progressEvents: visibleEvents,
              progressStatus: `第 ${round}/${maxRounds} 轮问诊 · 已覆盖: ${covered.join("、") || "无"} · 待追问: ${remaining.join("、") || "无"}`,
              streamTranscript,
              reasoningExpanded: false,
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
            flushStreamBuffers(true);
            const data = streamEvent.data as ChatResponse;
            const visibleEvents = progressEvents.slice(-80);
            const finalAnswer = data.answer || streamedAnswer || JSON.stringify(data, null, 2);
            persistReasoning(data.answer || finalAnswer);
            patchMessage(activeSession.id, assistantMessageId, {
              content: streamedAnswer || finalAnswer,
              createdAt: new Date().toISOString(),
              isStreaming: false,
              progressEvents: visibleEvents,
              progressStatus: "已完成",
              streamTranscript,
              reasoningExpanded: false,
              response: { ...data, progress_events: visibleEvents },
            });
            continue;
          }

          if (streamEvent.event === "done") {
            flushStreamBuffers(true);
            patchMessage(activeSession.id, assistantMessageId, {
              isStreaming: false,
              progressStatus: "已完成",
            });
            continue;
          }

          if (streamEvent.event === "error" && typeof streamEvent.data === "object" && streamEvent.data) {
            flushStreamBuffers(true);
            const statusCode = (streamEvent.data as { status_code?: unknown }).status_code;
            const fallback =
              statusCode === 400
                ? "本轮咨询请求参数有误，请调整后重试。"
                : "本轮咨询处理失败，请稍后重试或检查后端服务状态。";
            const visibleEvents = progressEvents.slice(-80);
            const finalError = streamedAnswer || fallback;
            persistReasoning(finalError);
            patchMessage(activeSession.id, assistantMessageId, {
              content: finalError,
              createdAt: new Date().toISOString(),
              isStreaming: false,
              progressEvents: visibleEvents,
              progressStatus: "处理失败",
              streamTranscript,
              reasoningExpanded: false,
              response: {
                status: "error",
                progress_events: visibleEvents,
              },
            });
            continue;
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
      window.clearInterval(typewriterTimer);
      flushStreamBuffers(true);
      controller.abort();
      setIsSending(false);
    }
  }

  return (
    <>
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
            </div>
          </div>
          {healthError ? <p className="memory-note error">{healthError}</p> : null}
          <div className="memory-panel">
            <div className="memory-panel-head">
              <div>
                <span>长期记忆</span>
                <strong>{memoryPrefs.enabled ? "开启" : "关闭"}</strong>
              </div>
              <label className="memory-toggle">
                <input
                  checked={memoryPrefs.enabled}
                  type="checkbox"
                  onChange={(event) =>
                    setMemoryPrefs((current) => ({ ...current, enabled: event.target.checked }))
                  }
                />
                <span />
              </label>
            </div>
            <div className="memory-setting-row">
              <span>记忆库</span>
              <div className="memory-backends" aria-label="记忆库">
                {(["local", "mem0"] as MemoryBackend[]).map((backend) => (
                  <button
                    className={memoryPrefs.backend === backend ? "active" : ""}
                    key={backend}
                    type="button"
                    onClick={() => setMemoryPrefs((current) => ({ ...current, backend }))}
                  >
                    {backend === "local" ? "本地" : "Mem0"}
                  </button>
                ))}
              </div>
            </div>
            <div className="memory-setting-row">
              <span>状态</span>
              <strong className={`memory-state ${currentMemoryStatus === "已保存" ? "saved" : ""}`}>
                {currentMemoryStatus}
              </strong>
            </div>
            {memoryError ? <p className="memory-note error">{memoryError}</p> : null}
            {latestResponse?.memory?.raw_session_error ? (
              <p className="memory-note error">{latestResponse.memory.raw_session_error}</p>
            ) : null}
            {memoryActionStatus ? <p className="memory-note">{memoryActionStatus}</p> : null}
            <div className="memory-actions">
              <button className="memory-save-button" type="button" onClick={openMemorySummaryDialog} disabled={!canOpenMemorySummary}>
                <Database size={15} />
                {isGeneratingMemorySummary ? "正在生成摘要..." : "将当前会话摘要并保存为长期记忆"}
              </button>
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
                    <ReasoningBlock
                      message={message}
                      onToggle={() => toggleReasoning(activeSession.id, message.id)}
                    />
                  ) : null}
                  <div className={`message-content ${message.role === "assistant" && message.content ? "message-answer" : ""}`}>
                    {message.role === "assistant" && message.content ? <span className="message-answer-label">最终输出</span> : null}
                    {message.role === "assistant" ? (
                      message.content ? (
                        message.isStreaming ? (
                          <p>{answerContentOnly(message.content)}</p>
                        ) : (
                          <ReactMarkdown>{answerContentOnly(message.content)}</ReactMarkdown>
                        )
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

      {isMemoryPreviewOpen && latestMemoryPreview ? (
        <div className="memory-modal-backdrop" role="presentation">
          <section className="memory-modal" role="dialog" aria-modal="true" aria-labelledby="memory-preview-title">
            <header className="memory-modal-head">
              <div>
                <span>长期记忆预览</span>
                <h3 id="memory-preview-title">{latestMemoryPreview.title}</h3>
              </div>
              <strong>保存到 {memoryPrefs.backend === "local" ? "本地" : "Mem0"}</strong>
            </header>
            <div className="memory-modal-body">
              <div className="memory-preview-block">
                <span>摘要</span>
                <p>{latestMemoryPreview.summary}</p>
              </div>
              {latestMemoryPreview.timeline ? (
                <div className="memory-preview-block">
                  <span>时间线</span>
                  <p>{latestMemoryPreview.timeline}</p>
                </div>
              ) : null}
              {latestMemoryPreview.care_recommendation ? (
                <div className="memory-preview-block">
                  <span>建议</span>
                  <p>{latestMemoryPreview.care_recommendation}</p>
                </div>
              ) : null}
              {latestMemoryPreview.tags.length ? (
                <div className="memory-tags">
                  {latestMemoryPreview.tags.slice(0, 8).map((tag) => (
                    <span key={tag}>{tag}</span>
                  ))}
                </div>
              ) : null}
              {latestMemoryPreview.profile_candidates.length ? (
                <div className="memory-profile-list">
                  <span>可沉淀信息</span>
                  {latestMemoryPreview.profile_candidates.slice(0, 4).map((item, index) => (
                    <div key={`${item.type}-${item.value}-${index}`}>
                      <strong>{item.value || item.type || "候选信息"}</strong>
                      <small>{item.evidence || "无额外依据"}</small>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
            <footer className="memory-modal-actions">
              <button type="button" className="secondary-action" onClick={cancelMemorySummary}>
                取消保存
              </button>
              <button type="button" className="primary-action" onClick={confirmMemorySummary}>
                <CheckCircle2 size={16} />
                确认保存
              </button>
            </footer>
          </section>
        </div>
      ) : null}
    </>
  );
}
