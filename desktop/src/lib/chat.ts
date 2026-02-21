import type { ChatMessage, MessageRole } from "./types";

export function makeMessage(role: MessageRole, text: string, status: ChatMessage["status"]): ChatMessage {
  return {
    id: crypto.randomUUID(),
    role,
    text,
    status,
    createdAt: Date.now()
  };
}

export function appendMessage(list: ChatMessage[], message: ChatMessage): ChatMessage[] {
  return [...list, message];
}

export function appendChunkById(
  list: ChatMessage[],
  messageId: string,
  chunk: string
): ChatMessage[] {
  return list.map((m) =>
    m.id === messageId ? { ...m, text: `${m.text}${chunk}`, status: "streaming" } : m
  );
}

export function markMessageStatus(
  list: ChatMessage[],
  messageId: string,
  status: ChatMessage["status"]
): ChatMessage[] {
  return list.map((m) => (m.id === messageId ? { ...m, status } : m));
}
