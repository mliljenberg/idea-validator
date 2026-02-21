export type MessageRole = "user" | "assistant" | "system";
export type MessageStatus = "done" | "streaming" | "error";

export interface ChatMessage {
  id: string;
  role: MessageRole;
  text: string;
  createdAt: number;
  status: MessageStatus;
}

export interface RunState {
  requestId: string;
  sessionId: string;
  running: boolean;
  startedAt: number;
  error?: string;
}

export interface BackendStatus {
  running: boolean;
  port: number;
  health: boolean;
  appName?: string;
  host: string;
  baseUrl: string;
  lastError?: string;
}

export interface SessionMeta {
  id: string;
  appName: string;
  userId: string;
  lastUpdateTime?: number;
}

export interface Ack {
  ok: boolean;
  message?: string;
}

export interface KeyPresence {
  googleApiKeySet: boolean;
  braveApiKeySet: boolean;
  geminiApiKeySet: boolean;
  googleApiKeyMasked?: string;
  braveApiKeyMasked?: string;
  geminiApiKeyMasked?: string;
}

export type AgentStreamPayload =
  | { kind: "stream_open"; requestId: string }
  | { kind: "stream_meta"; requestId: string; invocationId: string }
  | { kind: "stream_message"; requestId: string; text: string; source?: string }
  | {
      kind: "stream_progress";
      requestId: string;
      percent: number;
      stage: string;
      toolsCompleted: number;
      toolsTotal: number;
    }
  | {
      kind: "stream_tool";
      requestId: string;
      phase: "start" | "done" | "info";
      name: string;
      query?: string;
      detail?: string;
    }
  | { kind: "stream_event_raw"; requestId: string; event: unknown }
  | { kind: "stream_error"; requestId: string; message: string; retryable: boolean }
  | { kind: "stream_done"; requestId: string; usage?: unknown };

export interface StreamRunInput {
  requestId: string;
  appName: string;
  userId: string;
  sessionId: string;
  text: string;
  invocationId?: string;
}

export interface SessionCreateInput {
  appName: string;
  userId: string;
  sessionId?: string;
}

export interface SessionListInput {
  appName: string;
  userId: string;
}

export interface BackendStartConfig {
  host?: string;
  port?: number;
  repoRoot?: string;
  forceRestart?: boolean;
}
