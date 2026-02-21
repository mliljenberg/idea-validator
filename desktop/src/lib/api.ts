import { invoke } from "@tauri-apps/api/core";
import type {
  Ack,
  BackendStartConfig,
  BackendStatus,
  KeyPresence,
  SessionCreateInput,
  SessionListInput,
  SessionMeta,
  StreamRunInput
} from "./types";

export const backendStart = (config?: BackendStartConfig) =>
  invoke<BackendStatus>("backend_start", { config });

export const backendStop = () => invoke<BackendStatus>("backend_stop");

export const backendStatus = () => invoke<BackendStatus>("backend_status");

export const backendListApps = () => invoke<string[]>("backend_list_apps");

export const sessionCreate = (input: SessionCreateInput) =>
  invoke<SessionMeta>("session_create", { input });

export const sessionList = (input: SessionListInput) =>
  invoke<SessionMeta[]>("session_list", { input });

export const streamRun = (input: StreamRunInput) =>
  invoke<Ack>("stream_run", { input });

export const streamCancel = (requestId: string) =>
  invoke<Ack>("stream_cancel", { requestId });

export const keysSet = (keys: {
  googleApiKey?: string;
  braveApiKey?: string;
  geminiApiKey?: string;
}) => invoke<Ack>("keys_set", { keys });

export const keysGetMasked = () => invoke<KeyPresence>("keys_get_masked");

export const keysClear = () => invoke<Ack>("keys_clear");
