import type { AgentStreamPayload } from "./types";

type IncomingToolEvent = Extract<AgentStreamPayload, { kind: "stream_tool" }>;

export type StreamToolDisplayEvent = IncomingToolEvent & {
  at: number;
  count: number;
  dedupeKey: string;
};

function normalizePart(value: string | undefined): string {
  return (value || "").trim().toLowerCase().replace(/\s+/g, " ");
}

export function buildToolEventKey(event: IncomingToolEvent): string {
  return [
    normalizePart(event.phase),
    normalizePart(event.name),
    normalizePart(event.query),
    normalizePart(event.detail)
  ].join("|");
}

export function upsertToolEvent(
  events: StreamToolDisplayEvent[],
  event: IncomingToolEvent,
  now: number,
  windowMs = 2000,
  maxItems = 120
): StreamToolDisplayEvent[] {
  const dedupeKey = buildToolEventKey(event);
  const latest = events[0];

  if (latest && latest.dedupeKey === dedupeKey && now - latest.at <= windowMs) {
    const merged: StreamToolDisplayEvent = {
      ...latest,
      at: now,
      count: latest.count + 1
    };
    return [merged, ...events.slice(1, maxItems)];
  }

  const next: StreamToolDisplayEvent = {
    ...event,
    at: now,
    count: 1,
    dedupeKey
  };
  return [next, ...events].slice(0, maxItems);
}
