import type { ChatMessage } from "./types";

export type SessionMessageMap = Record<string, ChatMessage[]>;

export function appendToSession(
  store: SessionMessageMap,
  sessionId: string,
  message: ChatMessage
): SessionMessageMap {
  return {
    ...store,
    [sessionId]: [...(store[sessionId] || []), message]
  };
}

export function getSessionMessages(store: SessionMessageMap, sessionId: string): ChatMessage[] {
  return store[sessionId] || [];
}
