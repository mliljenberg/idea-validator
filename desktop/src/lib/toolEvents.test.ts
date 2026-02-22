import { describe, expect, it } from "vitest";
import { buildToolEventKey, upsertToolEvent } from "./toolEvents";

describe("tool event dedupe", () => {
  it("normalizes equivalent events into the same key", () => {
    const a = buildToolEventKey({
      kind: "stream_tool",
      requestId: "r1",
      phase: "start",
      name: "Plan_Generator",
      query: "  Desktop app  ",
      detail: "Args: Request"
    });
    const b = buildToolEventKey({
      kind: "stream_tool",
      requestId: "r1",
      phase: "start",
      name: "plan_generator",
      query: "desktop app",
      detail: "args:  request"
    });
    expect(a).toBe(b);
  });

  it("collapses consecutive duplicates inside time window", () => {
    let events = upsertToolEvent(
      [],
      {
        kind: "stream_tool",
        requestId: "r1",
        phase: "start",
        name: "plan_generator",
        detail: "args: request"
      },
      1000
    );
    events = upsertToolEvent(
      events,
      {
        kind: "stream_tool",
        requestId: "r1",
        phase: "start",
        name: "plan_generator",
        detail: "args: request"
      },
      1800
    );
    expect(events).toHaveLength(1);
    expect(events[0].count).toBe(2);
  });

  it("creates a new row when outside dedupe window", () => {
    let events = upsertToolEvent(
      [],
      {
        kind: "stream_tool",
        requestId: "r1",
        phase: "start",
        name: "plan_generator",
        detail: "args: request"
      },
      1000
    );
    events = upsertToolEvent(
      events,
      {
        kind: "stream_tool",
        requestId: "r1",
        phase: "start",
        name: "plan_generator",
        detail: "args: request"
      },
      5000
    );
    expect(events).toHaveLength(2);
    expect(events[0].count).toBe(1);
    expect(events[1].count).toBe(1);
  });
});
