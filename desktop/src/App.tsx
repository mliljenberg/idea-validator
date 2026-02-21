import { useEffect, useMemo, useRef, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  backendListApps,
  backendStart,
  backendStatus,
  keysGetMasked,
  keysSet,
  sessionCreate,
  sessionList,
  streamCancel,
  streamRun
} from "./lib/api";
import { appendMessage, makeMessage } from "./lib/chat";
import type {
  AgentStreamPayload,
  BackendStatus,
  ChatMessage,
  KeyPresence,
  RunState,
  SessionMeta
} from "./lib/types";

const USER_ID = "local-user";
const APP_STORAGE_KEY = "pv_desktop_selected_app";
const SESSION_NAMES_STORAGE_KEY = "pv_desktop_session_names";
const SESSION_MESSAGES_STORAGE_KEY = "pv_desktop_session_messages";
type StreamProgressPayload = Extract<AgentStreamPayload, { kind: "stream_progress" }>;
type StreamToolPayload = Extract<AgentStreamPayload, { kind: "stream_tool" }> & { at: number };
type SummarySection = { title: string; body: string };

function hasRequiredKeys(keys: KeyPresence | null): boolean {
  if (!keys) return false;
  return keys.googleApiKeySet && keys.braveApiKeySet;
}

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function stripStructuredJsonBlocks(input: string): string {
  const looksLikeRecommendationPayload = (value: unknown): boolean => {
    if (!value || typeof value !== "object" || Array.isArray(value)) return false;
    const obj = value as Record<string, unknown>;
    return (
      typeof obj.recommendation === "string" ||
      typeof obj.signal_score === "number" ||
      typeof obj.signalScore === "number" ||
      typeof obj.confidence === "string" ||
      typeof obj.evidence_strength === "number" ||
      typeof obj.evidenceStrength === "number"
    );
  };

  let out = "";
  let i = 0;
  while (i < input.length) {
    const char = input[i];
    if (char !== "{") {
      out += char;
      i += 1;
      continue;
    }

    let j = i;
    let depth = 0;
    let inString = false;
    let escaped = false;
    let found = false;

    while (j < input.length) {
      const c = input[j];
      if (inString) {
        if (escaped) {
          escaped = false;
        } else if (c === "\\") {
          escaped = true;
        } else if (c === "\"") {
          inString = false;
        }
      } else if (c === "\"") {
        inString = true;
      } else if (c === "{") {
        depth += 1;
      } else if (c === "}") {
        depth -= 1;
        if (depth === 0) {
          found = true;
          j += 1;
          break;
        }
      }
      j += 1;
    }

    if (!found) {
      out += char;
      i += 1;
      continue;
    }

    const candidate = input.slice(i, j).trim();
    try {
      const parsed = JSON.parse(candidate) as unknown;
      if (looksLikeRecommendationPayload(parsed)) {
        i = j;
        continue;
      }
    } catch {
      // Keep non-JSON content as-is.
    }

    out += input.slice(i, j);
    i = j;
  }

  return out;
}

function sanitizeAgentText(input: string): string {
  return stripStructuredJsonBlocks(input)
    .replace(/Source not selected\.\s*/gi, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function extractSummarySections(text: string): { preface: string; sections: SummarySection[] } {
  const lines = text.split(/\r?\n/);
  const markdownHeading = /^(?:#{1,6}\s*)(.+?)\s*$/;
  const titledLine = /^([A-Z][A-Za-z0-9/&()\- ,]{3,100})\s*:?\s*$/;
  const sourceHints: Array<{ needle: string; title: string }> = [
    { needle: "reddit", title: "Reddit Summary" },
    { needle: "hacker news", title: "Hacker News Summary" },
    { needle: "google trends", title: "Google Trends Summary" },
    { needle: "competitor", title: "Competitor Summary" },
    { needle: "jobs signal", title: "Jobs Signal Summary" },
    { needle: "seo intent", title: "SEO Intent Summary" },
    { needle: "review sites", title: "Review Sites Summary" },
    { needle: "github", title: "GitHub Summary" },
    { needle: "openalex", title: "OpenAlex Summary" },
    { needle: "brave search", title: "Brave Search Summary" }
  ];
  const sections: SummarySection[] = [];
  const preface: string[] = [];

  let currentTitle: string | null = null;
  let currentBody: string[] = [];

  const flush = () => {
    if (!currentTitle) return;
    const body = currentBody.join("\n").trim();
    if (body) {
      sections.push({ title: currentTitle, body });
    }
    currentTitle = null;
    currentBody = [];
  };

  const normalizeTitle = (raw: string): string => {
    const cleaned = raw
      .replace(/^#+\s*/, "")
      .replace(/\*\*/g, "")
      .replace(/^\d+[\).\s-]+/, "")
      .replace(/\s+/g, " ")
      .trim();
    return cleaned;
  };

  const sourceTitleFrom = (raw: string): string | null => {
    const cleaned = normalizeTitle(raw);
    if (!cleaned) return null;

    const lower = cleaned.toLowerCase();
    const hasSummaryWord = /summary|report|findings/.test(lower);
    for (const hint of sourceHints) {
      if (lower.includes(hint.needle) && hasSummaryWord) {
        return hint.title;
      }
    }
    return null;
  };

  const titleFromLine = (line: string): string | null => {
    const trimmed = line.trim();
    if (!trimmed) return null;

    const markdown = trimmed.match(markdownHeading);
    if (markdown) {
      return sourceTitleFrom(markdown[1]);
    }

    const titled = trimmed.match(titledLine);
    if (titled) {
      return sourceTitleFrom(titled[1]);
    }

    return null;
  };

  for (const line of lines) {
    const sectionTitle = titleFromLine(line);
    if (sectionTitle) {
      flush();
      currentTitle = sectionTitle;
      continue;
    }

    if (currentTitle) {
      currentBody.push(line);
    } else {
      preface.push(line);
    }
  }

  flush();
  return { preface: preface.join("\n").trim(), sections };
}

export default function App() {
  const [status, setStatus] = useState<BackendStatus>({
    running: false,
    port: 8765,
    health: false,
    host: "127.0.0.1",
    baseUrl: "http://127.0.0.1:8765",
    lastError: undefined
  });
  const [apps, setApps] = useState<string[]>([]);
  const [selectedApp, setSelectedApp] = useState<string>("");
  const [sessions, setSessions] = useState<SessionMeta[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string>("");
  const [messagesBySession, setMessagesBySession] = useState<Record<string, ChatMessage[]>>({});
  const [pendingAssistantBySession, setPendingAssistantBySession] = useState<Record<string, string>>({});
  const [sessionNames, setSessionNames] = useState<Record<string, string>>({});
  const [progressBySession, setProgressBySession] = useState<Record<string, StreamProgressPayload>>({});
  const [toolEventsBySession, setToolEventsBySession] = useState<Record<string, StreamToolPayload[]>>({});
  const [composer, setComposer] = useState("");
  const [runState, setRunState] = useState<RunState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>("");
  const [keyPresence, setKeyPresence] = useState<KeyPresence | null>(null);
  const [keyForm, setKeyForm] = useState({ googleApiKey: "", braveApiKey: "", geminiApiKey: "" });
  const [autoScroll, setAutoScroll] = useState(true);

  const transcriptRef = useRef<HTMLDivElement | null>(null);
  const googleKeyInputRef = useRef<HTMLInputElement | null>(null);
  const braveKeyInputRef = useRef<HTMLInputElement | null>(null);
  const geminiKeyInputRef = useRef<HTMLInputElement | null>(null);

  const activeMessages = messagesBySession[activeSessionId] || [];
  const activePendingAssistant = pendingAssistantBySession[activeSessionId] || "";
  const activeProgress = progressBySession[activeSessionId];
  const activeToolEvents = toolEventsBySession[activeSessionId] || [];
  const progressPercent = activeProgress?.percent ?? (runState?.running ? 8 : 0);
  const progressStage = activeProgress?.stage ?? (runState?.running ? "Starting run" : "Idle");
  const latestToolActivity = activeToolEvents.slice(0, 8);
  const showRunStatusCard = Boolean(runState?.running && runState.sessionId === activeSessionId);
  const needsInitialKeySetup = keyPresence !== null && !hasRequiredKeys(keyPresence);
  const googleReady = Boolean(keyPresence?.googleApiKeySet || keyForm.googleApiKey.trim());
  const braveReady = Boolean(keyPresence?.braveApiKeySet || keyForm.braveApiKey.trim());
  const canSubmitRequiredKeys = googleReady && braveReady && !busy;

  const boot = async () => {
    setBusy(true);
    setError("");
    try {
      const keys = await keysGetMasked();
      setKeyPresence(keys);

      if (!hasRequiredKeys(keys)) {
        setStatus((prev) => ({ ...prev, running: false, health: false, lastError: undefined }));
        setApps([]);
        setSelectedApp("");
        setSessions([]);
        setActiveSessionId("");
        return;
      }

      const started = await backendStart({ host: "127.0.0.1", port: 8765 });
      const appNames = await backendListApps();
      setStatus(started);
      setApps(appNames);

      const savedApp = localStorage.getItem(APP_STORAGE_KEY) || "";
      const preferred =
        (savedApp && appNames.includes(savedApp) && savedApp) ||
        (started.appName && appNames.includes(started.appName) && started.appName) ||
        appNames[0] ||
        "";

      if (preferred) {
        setSelectedApp(preferred);
        localStorage.setItem(APP_STORAGE_KEY, preferred);
        await refreshSessions(preferred);
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const refreshSessions = async (appName: string) => {
    const result = await sessionList({ appName, userId: USER_ID });
    const ordered = [...result].sort((a, b) => (b.lastUpdateTime || 0) - (a.lastUpdateTime || 0));

    let effective = ordered;
    if (!effective.length) {
      const created = await sessionCreate({ appName, userId: USER_ID });
      effective = [created];
    }

    setSessions(effective);
    setActiveSessionId((prev) => {
      if (prev && effective.some((s) => s.id === prev)) {
        return prev;
      }
      return effective[0].id;
    });
  };

  const newSession = async () => {
    if (!selectedApp) return;
    const created = await sessionCreate({ appName: selectedApp, userId: USER_ID });
    setSessions((prev) => [created, ...prev]);
    setActiveSessionId(created.id);
  };

  useEffect(() => {
    void boot();
  }, []);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(SESSION_NAMES_STORAGE_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw) as Record<string, string>;
      if (parsed && typeof parsed === "object") {
        setSessionNames(parsed);
      }
    } catch {
      // Ignore malformed local storage.
    }
  }, []);

  useEffect(() => {
    localStorage.setItem(SESSION_NAMES_STORAGE_KEY, JSON.stringify(sessionNames));
  }, [sessionNames]);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(SESSION_MESSAGES_STORAGE_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw) as Record<string, ChatMessage[]>;
      if (parsed && typeof parsed === "object") {
        setMessagesBySession(parsed);
      }
    } catch {
      // Ignore malformed local storage.
    }
  }, []);

  useEffect(() => {
    const compact: Record<string, ChatMessage[]> = {};
    for (const [sessionId, messages] of Object.entries(messagesBySession)) {
      if (!messages.length) continue;
      compact[sessionId] = messages.slice(-40);
    }
    localStorage.setItem(SESSION_MESSAGES_STORAGE_KEY, JSON.stringify(compact));
  }, [messagesBySession]);

  useEffect(() => {
    if (needsInitialKeySetup) {
      return;
    }

    const timer = window.setInterval(() => {
      void backendStatus()
        .then((next) => {
          setStatus(next);
          if (!next.running && next.lastError) {
            setError(next.lastError);
          }
        })
        .catch(() => undefined);
    }, 4000);

    let unlisten: (() => void) | null = null;
    void listen<{ message?: string }>("backend-exited", (event) => {
      setError(event.payload?.message || "Backend exited unexpectedly.");
      void backendStatus().then((next) => setStatus(next));
    }).then((fn) => {
      unlisten = fn;
    });

    return () => {
      window.clearInterval(timer);
      if (unlisten) {
        unlisten();
      }
    };
  }, [needsInitialKeySetup]);

  useEffect(() => {
    if (!autoScroll || !transcriptRef.current) return;
    transcriptRef.current.scrollTop = transcriptRef.current.scrollHeight;
  }, [activeMessages, autoScroll]);

  const readKeysWithRetry = async () => {
    let snapshot = await keysGetMasked();
    if (hasRequiredKeys(snapshot)) {
      return snapshot;
    }

    for (let attempt = 0; attempt < 5; attempt += 1) {
      await wait(180);
      snapshot = await keysGetMasked();
      if (hasRequiredKeys(snapshot)) {
        return snapshot;
      }
    }

    return snapshot;
  };

  const saveKeys = async () => {
    setBusy(true);
    setError("");
    try {
      const googleInput = (googleKeyInputRef.current?.value ?? keyForm.googleApiKey).trim();
      const braveInput = (braveKeyInputRef.current?.value ?? keyForm.braveApiKey).trim();
      const geminiInput = (geminiKeyInputRef.current?.value ?? keyForm.geminiApiKey).trim();
      const missingGoogle = !keyPresence?.googleApiKeySet && !googleInput;
      const missingBrave = !keyPresence?.braveApiKeySet && !braveInput;
      if (missingGoogle || missingBrave) {
        setError("Google API key and Brave Search API key are required to continue.");
        return;
      }

      await keysSet({
        googleApiKey: googleInput || undefined,
        braveApiKey: braveInput || undefined,
        geminiApiKey: geminiInput || undefined
      });

      const nextKeys = await readKeysWithRetry();
      setKeyPresence(nextKeys);
      if (!hasRequiredKeys(nextKeys)) {
        setError(
          `Key save verification failed (google=${nextKeys.googleApiKeySet}, brave=${nextKeys.braveApiKeySet}). ` +
            "Try saving again. If this persists, run with terminal logs enabled to inspect keychain errors."
        );
        return;
      }

      setKeyForm({ googleApiKey: "", braveApiKey: "", geminiApiKey: "" });
      await boot();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const sendMessage = async () => {
    const text = composer.trim();
    if (!text || !selectedApp || runState?.running) return;
    if (!hasRequiredKeys(keyPresence)) {
      setError("Add required API keys before running validation.");
      return;
    }
    setError("");

    let sessionId = activeSessionId;
    if (!sessionId) {
      const created = await sessionCreate({ appName: selectedApp, userId: USER_ID });
      sessionId = created.id;
      setSessions((prev) => [created, ...prev]);
      setActiveSessionId(sessionId);
    }

    const userMessage = makeMessage("user", text, "done");

    setSessionNames((prev) => {
      if (prev[sessionId]) {
        return prev;
      }
      const normalized = text.replace(/\s+/g, " ").trim();
      if (!normalized) {
        return prev;
      }
      return {
        ...prev,
        [sessionId]: normalized.length > 44 ? `${normalized.slice(0, 44)}...` : normalized
      };
    });

    setMessagesBySession((prev) => ({
      ...prev,
      [sessionId]: appendMessage(prev[sessionId] || [], userMessage)
    }));

    setComposer("");

    const requestId = crypto.randomUUID();
    setRunState({ requestId, sessionId, running: true, startedAt: Date.now() });
    setPendingAssistantBySession((prev) => ({
      ...prev,
      [sessionId]: ""
    }));
    setProgressBySession((prev) => ({
      ...prev,
      [sessionId]: {
        kind: "stream_progress",
        requestId,
        percent: 5,
        stage: "Queued",
        toolsCompleted: 0,
        toolsTotal: 0
      }
    }));

    let latestAssistantText = "";
    const unlisten = await listen<AgentStreamPayload>(`agent-stream:${requestId}`, (evt) => {
      const payload = evt.payload;
      if (!payload || typeof payload !== "object" || !("kind" in payload)) {
        return;
      }

      if (payload.kind === "stream_message") {
        const nextText = payload.text?.trim() || "";
        if (nextText) {
          latestAssistantText = nextText;
          setPendingAssistantBySession((prev) => ({
            ...prev,
            [sessionId]: nextText
          }));
        }
      }

      if (payload.kind === "stream_progress") {
        setProgressBySession((prev) => ({
          ...prev,
          [sessionId]: payload
        }));
      }

      if (payload.kind === "stream_tool") {
        setToolEventsBySession((prev) => ({
          ...prev,
          [sessionId]: [{ ...payload, at: Date.now() }, ...(prev[sessionId] || [])].slice(0, 120)
        }));
      }

      if (payload.kind === "stream_error") {
        setPendingAssistantBySession((prev) => ({
          ...prev,
          [sessionId]: ""
        }));
        setMessagesBySession((prev) => ({
          ...prev,
          [sessionId]: appendMessage(
            prev[sessionId] || [],
            makeMessage("assistant", `Error: ${payload.message}`, "error")
          )
        }));
        setProgressBySession((prev) => ({
          ...prev,
          [sessionId]: {
            kind: "stream_progress",
            requestId,
            percent: 100,
            stage: "Failed",
            toolsCompleted: prev[sessionId]?.toolsCompleted || 0,
            toolsTotal: prev[sessionId]?.toolsTotal || 0
          }
        }));
        setRunState((prev) =>
          prev && prev.requestId === requestId ? { ...prev, running: false, error: payload.message } : prev
        );
        void unlisten();
      }

      if (payload.kind === "stream_done") {
        const finalText = latestAssistantText.trim();
        if (finalText) {
          setMessagesBySession((prev) => ({
            ...prev,
            [sessionId]: appendMessage(
              prev[sessionId] || [],
              makeMessage("assistant", finalText, "done")
            )
          }));
        }
        setPendingAssistantBySession((prev) => ({
          ...prev,
          [sessionId]: ""
        }));
        setProgressBySession((prev) => ({
          ...prev,
          [sessionId]: {
            kind: "stream_progress",
            requestId,
            percent: 100,
            stage: "Complete",
            toolsCompleted: prev[sessionId]?.toolsCompleted || 0,
            toolsTotal: prev[sessionId]?.toolsTotal || 0
          }
        }));
        setRunState((prev) =>
          prev && prev.requestId === requestId ? { ...prev, running: false } : prev
        );
        void unlisten();
      }
    });

    try {
      await streamRun({
        requestId,
        appName: selectedApp,
        userId: USER_ID,
        sessionId,
        text
      });
      await refreshSessions(selectedApp);
    } catch (e) {
      setPendingAssistantBySession((prev) => ({
        ...prev,
        [sessionId]: ""
      }));
      setMessagesBySession((prev) => ({
        ...prev,
        [sessionId]: appendMessage(
          prev[sessionId] || [],
          makeMessage("assistant", `Error: ${String(e)}`, "error")
        )
      }));
      setRunState((prev) =>
        prev && prev.requestId === requestId ? { ...prev, running: false, error: String(e) } : prev
      );
      void unlisten();
    }
  };

  const stopRun = async () => {
    if (!runState?.running) return;
    await streamCancel(runState.requestId);
    setPendingAssistantBySession((prev) => ({
      ...prev,
      [runState.sessionId]: ""
    }));
    setRunState((prev) => (prev ? { ...prev, running: false } : prev));
  };

  const statusLabel = useMemo(() => {
    if (!status.running && status.lastError) return "Crashed";
    if (!status.running) return "Stopped";
    if (status.running && !status.health) return "Booting";
    return "Online";
  }, [status]);

  const onScrollTranscript = () => {
    const el = transcriptRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - (el.scrollTop + el.clientHeight) < 36;
    setAutoScroll(nearBottom);
  };

  const switchApp = async (value: string) => {
    setSelectedApp(value);
    localStorage.setItem(APP_STORAGE_KEY, value);
    await refreshSessions(value);
  };

  const sessionLabel = (sessionId: string, index: number): string => {
    const persisted = sessionNames[sessionId]?.trim();
    if (persisted) {
      return persisted;
    }
    const messages = messagesBySession[sessionId] || [];
    const firstUserMessage = messages.find((m) => m.role === "user");
    const seed = firstUserMessage?.text?.replace(/\s+/g, " ").trim();
    if (!seed) {
      return `Session ${index + 1}`;
    }
    return seed.length > 44 ? `${seed.slice(0, 44)}...` : seed;
  };

  if (keyPresence === null) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-ink-950 text-slate-100">
        <div className="rounded-2xl border border-white/10 bg-ink-900/70 px-6 py-5 text-sm text-slate-300">
          Checking keychain...
        </div>
      </div>
    );
  }

  if (needsInitialKeySetup) {
    return (
      <div className="min-h-screen bg-ink-950 text-slate-100">
        <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(ellipse_at_top_right,_rgba(0,208,255,0.14),_transparent_45%),radial-gradient(ellipse_at_bottom_left,_rgba(255,79,136,0.12),_transparent_45%)]" />
        <div className="relative mx-auto flex min-h-screen w-full max-w-3xl items-center justify-center p-6">
          <section className="panel w-full max-w-xl p-6">
            <p className="text-xs uppercase tracking-[0.2em] text-neon-cyan">Initial Setup</p>
            <h1 className="mt-2 text-2xl font-semibold">Add Required API Keys</h1>
            <p className="mt-2 text-sm text-slate-300">
              Google API key and Brave Search API key are required before you can use the validator.
            </p>

            <form
              className="mt-4 space-y-2"
              onSubmit={(e) => {
                e.preventDefault();
                if (canSubmitRequiredKeys) {
                  void saveKeys();
                }
              }}
            >
              <input
                type="password"
                placeholder="Google API key (required)"
                value={keyForm.googleApiKey}
                onChange={(e) => setKeyForm((p) => ({ ...p, googleApiKey: e.target.value }))}
                ref={googleKeyInputRef}
                className="field"
              />
              {keyPresence.googleApiKeyMasked ? (
                <p className="text-[11px] text-slate-400">Saved: {keyPresence.googleApiKeyMasked}</p>
              ) : null}

              <input
                type="password"
                placeholder="Brave Search API key (required)"
                value={keyForm.braveApiKey}
                onChange={(e) => setKeyForm((p) => ({ ...p, braveApiKey: e.target.value }))}
                ref={braveKeyInputRef}
                className="field"
              />
              {keyPresence.braveApiKeyMasked ? (
                <p className="text-[11px] text-slate-400">Saved: {keyPresence.braveApiKeyMasked}</p>
              ) : null}

              <input
                type="password"
                placeholder="Gemini API key (optional)"
                value={keyForm.geminiApiKey}
                onChange={(e) => setKeyForm((p) => ({ ...p, geminiApiKey: e.target.value }))}
                ref={geminiKeyInputRef}
                className="field"
              />
              {keyPresence.geminiApiKeyMasked ? (
                <p className="text-[11px] text-slate-400">Saved: {keyPresence.geminiApiKeyMasked}</p>
              ) : null}

              <div className="mt-4">
                <button className="btn-primary w-full" type="submit" disabled={!canSubmitRequiredKeys}>
                Save Keys and Continue
                </button>
              </div>
            </form>

            {error ? (
              <div className="mt-3 rounded-xl border border-neon-rose/60 bg-neon-rose/10 p-3 text-xs text-rose-100">
                {error}
              </div>
            ) : null}
          </section>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-ink-950 text-slate-100">
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(ellipse_at_top_right,_rgba(0,208,255,0.14),_transparent_45%),radial-gradient(ellipse_at_bottom_left,_rgba(255,79,136,0.12),_transparent_45%)]" />

      <div className="relative mx-auto grid h-screen max-w-[1600px] grid-cols-[270px_1fr] gap-4 p-4">
        <aside className="panel flex flex-col gap-4">
          <div>
            <p className="text-xs uppercase tracking-[0.2em] text-neon-cyan">Product Validator</p>
            <h1 className="mt-2 text-2xl font-semibold leading-tight">Agent Control Center</h1>
          </div>

          <div className="rounded-xl border border-white/10 bg-white/5 p-3">
            <label className="text-xs text-slate-300">Agent App</label>
            <select
              className="mt-2 w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm"
              value={selectedApp}
              onChange={(e) => void switchApp(e.target.value)}
            >
              {apps.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </div>

          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium text-slate-300">Sessions</h2>
            <button className="btn-primary" onClick={() => void newSession()}>
              New
            </button>
          </div>

          <div className="scrollbar flex-1 space-y-2 overflow-auto pr-1">
            {sessions.map((s, idx) => (
              <button
                key={s.id}
                onClick={() => setActiveSessionId(s.id)}
                className={`w-full rounded-xl border px-3 py-2 text-left text-xs transition ${
                  s.id === activeSessionId
                    ? "border-neon-cyan/70 bg-neon-cyan/10 text-white"
                    : "border-white/10 bg-white/5 text-slate-300 hover:bg-white/10"
                }`}
              >
                <div className="text-sm font-medium text-slate-100">{sessionLabel(s.id, idx)}</div>
                <div className="mt-1 text-[11px] text-slate-400">
                  {s.lastUpdateTime ? new Date(s.lastUpdateTime * 1000).toLocaleString() : "No updates"}
                </div>
                <div className="mt-1 font-mono text-[10px] text-slate-500">{s.id.slice(0, 8)}</div>
              </button>
            ))}
          </div>
        </aside>

        <main className="panel relative flex flex-col overflow-hidden">
          <div className="border-b border-white/10 px-5 py-3">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs uppercase tracking-[0.18em] text-neon-mint">Live Stream</p>
                <h2 className="text-lg font-semibold">Conversation</h2>
              </div>
              <div className="flex items-center gap-2 text-xs">
                <span className={`h-2.5 w-2.5 rounded-full ${status.running && status.health ? "bg-neon-mint" : "bg-neon-rose"} ${status.running ? "animate-pulseSoft" : ""}`} />
                <span>{statusLabel}</span>
                <span className="rounded bg-white/10 px-2 py-1 font-mono">{status.host}:{status.port}</span>
              </div>
            </div>

            <div className="mt-3">
              <div className="h-2 w-full overflow-hidden rounded-full bg-white/10">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-neon-cyan via-neon-mint to-neon-cyan transition-all duration-300"
                  style={{ width: `${progressPercent}%` }}
                />
              </div>
              <div className="mt-1 flex items-center justify-between text-[11px] text-slate-400">
                <span>{progressStage}</span>
                <span>{progressPercent}%</span>
              </div>
            </div>
          </div>

          <div ref={transcriptRef} onScroll={onScrollTranscript} className="scrollbar flex-1 space-y-3 overflow-auto px-5 py-4">
            {activeMessages.length === 0 && !showRunStatusCard ? (
              <div className="rounded-2xl border border-dashed border-white/20 bg-white/5 p-8 text-center text-slate-300">
                Start by sending a product idea. Streaming output and function/tool events will appear live.
              </div>
            ) : null}

            {showRunStatusCard ? (
              <div className="animate-riseIn max-w-[88%] rounded-2xl border border-neon-cyan/35 bg-gradient-to-br from-neon-cyan/10 via-white/5 to-neon-mint/10 px-4 py-3">
                <div className="mb-1 flex items-center gap-2 text-[11px] uppercase tracking-[0.16em] text-slate-300">
                  <span className="h-2 w-2 rounded-full bg-neon-cyan animate-pulseSoft" />
                  <span>Thinking</span>
                </div>
                <p className="text-sm text-slate-100">
                  {progressStage}
                </p>
                <p className="mt-1 text-xs text-slate-400">Progress {progressPercent}%</p>
                {activePendingAssistant ? (
                  <p className="mt-2 text-xs text-slate-300">
                    Drafting response...
                  </p>
                ) : null}
                {latestToolActivity.length > 0 ? (
                  <div className="mt-3 space-y-1.5">
                    {latestToolActivity.map((event, eventIdx) => (
                      <div key={`${event.at}-${eventIdx}`} className="rounded-lg border border-white/10 bg-black/35 px-2.5 py-1.5 text-xs">
                        <div className="flex items-center justify-between gap-2">
                          <span
                            className={`rounded px-1.5 py-0.5 text-[10px] uppercase tracking-[0.12em] ${
                              event.phase === "start"
                                ? "bg-neon-cyan/20 text-cyan-200"
                                : event.phase === "done"
                                  ? "bg-neon-mint/20 text-emerald-200"
                                  : "bg-white/15 text-slate-200"
                            }`}
                          >
                            {event.phase}
                          </span>
                          <span className="text-[10px] text-slate-400">{new Date(event.at).toLocaleTimeString()}</span>
                        </div>
                        <div className="mt-1 text-slate-100">{event.name.replace(/[_-]/g, " ")}</div>
                        {event.query ? (
                          <div className="mt-1 break-words text-[11px] text-neon-cyan">{event.query}</div>
                        ) : null}
                        {event.detail ? (
                          <div className="mt-1 break-words text-[11px] text-slate-300">{event.detail}</div>
                        ) : null}
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="mt-1 text-xs text-slate-400">Preparing source agents and collecting evidence...</p>
                )}
              </div>
            ) : null}

            {activeMessages.map((m, idx) => {
              const isLatest = idx === activeMessages.length - 1;
              const cleanedAssistantText = m.role === "assistant" ? sanitizeAgentText(m.text) : m.text;
              const split = m.role === "assistant" ? extractSummarySections(cleanedAssistantText) : { preface: "", sections: [] as SummarySection[] };
              const hasSummarySections = split.sections.length > 0;
              const showLiveWorkingState =
                m.role === "assistant" &&
                isLatest &&
                m.status === "streaming" &&
                !cleanedAssistantText;

              if (m.role === "assistant" && hasSummarySections) {
                return (
                  <div key={m.id} className="animate-riseIn max-w-[92%] space-y-2">
                    <div className="text-[11px] uppercase tracking-[0.16em] text-slate-400">Agent</div>

                    {split.preface ? (
                      <div className="rounded-2xl border border-white/15 bg-white/5 px-4 py-3">
                        <article className="markdown-body text-sm leading-relaxed">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>{split.preface}</ReactMarkdown>
                        </article>
                      </div>
                    ) : null}

                    {split.sections.map((section, sectionIdx) => (
                      <details
                        key={`${m.id}-summary-${sectionIdx}`}
                        className="summary-bar overflow-hidden rounded-xl border border-white/15 bg-black/35"
                        open={sectionIdx === 0}
                      >
                        <summary className="cursor-pointer list-none px-3 py-2 text-sm font-semibold text-slate-100">
                          <span>{section.title}</span>
                        </summary>
                        <div className="border-t border-white/10 px-3 py-2">
                          <article className="markdown-body text-sm leading-relaxed">
                            <ReactMarkdown remarkPlugins={[remarkGfm]}>{section.body}</ReactMarkdown>
                          </article>
                        </div>
                      </details>
                    ))}

                    <div className="text-[11px] text-slate-400">
                      {new Date(m.createdAt).toLocaleTimeString()} · {m.status}
                    </div>
                  </div>
                );
              }

              return (
                <div key={m.id} className="animate-riseIn">
                  <div
                    className={`max-w-[84%] rounded-2xl border px-4 py-3 ${
                      m.role === "user"
                        ? "ml-auto border-neon-cyan/40 bg-neon-cyan/10"
                        : m.status === "error"
                          ? "border-neon-rose/50 bg-neon-rose/10"
                          : "border-white/15 bg-white/5"
                    }`}
                  >
                    <div className="mb-1 text-[11px] uppercase tracking-[0.16em] text-slate-400">
                      {m.role === "user" ? "You" : "Agent"}
                    </div>

                    {m.role === "assistant" && cleanedAssistantText ? (
                      <article className="markdown-body text-sm leading-relaxed">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{cleanedAssistantText}</ReactMarkdown>
                      </article>
                    ) : showLiveWorkingState ? (
                      <div className="space-y-2">
                        <p className="text-sm text-slate-100">
                          Working on: <span className="text-neon-cyan">{progressStage}</span>
                        </p>
                        <p className="text-xs text-slate-400">Progress {progressPercent}%</p>
                        {latestToolActivity.length > 0 ? (
                          <div className="space-y-1">
                            {latestToolActivity.map((event, eventIdx) => (
                              <div key={`${event.at}-${eventIdx}`} className="rounded border border-white/10 bg-black/30 px-2 py-1 text-xs">
                                <span className="uppercase text-[10px] tracking-[0.12em] text-slate-400">{event.phase}</span>
                                <span className="ml-2 text-slate-200">{event.name.replace(/[_-]/g, " ")}</span>
                                {event.query ? (
                                  <div className="mt-1 break-words text-[11px] text-neon-cyan">{event.query}</div>
                                ) : null}
                              </div>
                            ))}
                          </div>
                        ) : (
                          <p className="text-xs text-slate-400">Preparing source agents and collecting evidence...</p>
                        )}
                      </div>
                    ) : (
                      <p className="whitespace-pre-wrap text-sm leading-relaxed">
                        {m.text || (m.status === "streaming" ? <span className="typing-cursor">Thinking</span> : "")}
                      </p>
                    )}

                    <div className="mt-2 text-[11px] text-slate-400">
                      {new Date(m.createdAt).toLocaleTimeString()} · {m.status}
                    </div>
                  </div>
                  {isLatest && m.status === "streaming" ? (
                    <div className="mt-2 h-[2px] w-24 animate-pulseSoft rounded bg-gradient-to-r from-neon-cyan to-neon-mint" />
                  ) : null}
                </div>
              );
            })}
          </div>

          {!autoScroll ? (
            <button
              className="absolute bottom-28 right-8 rounded-full border border-white/20 bg-black/50 px-3 py-1 text-xs"
              onClick={() => {
                setAutoScroll(true);
                if (transcriptRef.current) {
                  transcriptRef.current.scrollTop = transcriptRef.current.scrollHeight;
                }
              }}
            >
              Jump to latest
            </button>
          ) : null}

          <div className="border-t border-white/10 px-5 py-4">
            <textarea
              value={composer}
              onChange={(e) => setComposer(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void sendMessage();
                }
              }}
              placeholder="Describe a product idea, niche, or pivot to validate..."
              className="h-24 w-full resize-none rounded-xl border border-white/15 bg-black/40 px-3 py-2 text-sm outline-none ring-neon-cyan/50 transition focus:ring"
            />
            <div className="mt-3 flex items-center justify-between">
              <div className="text-xs text-slate-400">Enter to send · Shift+Enter newline</div>
              <div className="flex gap-2">
                <button className="btn-secondary" onClick={() => void stopRun()} disabled={!runState?.running}>
                  Stop
                </button>
                <button className="btn-primary" onClick={() => void sendMessage()} disabled={busy || !!runState?.running}>
                  Send
                </button>
              </div>
            </div>
          </div>
        </main>

      </div>
      {runState?.error || error ? (
        <div className="fixed bottom-5 right-5 z-50 max-w-md rounded-xl border border-neon-rose/60 bg-neon-rose/10 p-3 text-xs text-rose-100 shadow-[0_10px_30px_rgba(0,0,0,0.35)]">
          {runState?.error || error}
        </div>
      ) : null}
    </div>
  );
}
