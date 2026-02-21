import { describe, expect, it } from "vitest";
import { appendChunkById, appendMessage, makeMessage, markMessageStatus } from "./chat";

describe("chat helpers", () => {
  it("appends chunks to the expected assistant message", () => {
    const assistant = makeMessage("assistant", "Hel", "streaming");
    const initial = [assistant];

    const updated = appendChunkById(initial, assistant.id, "lo");

    expect(updated[0].text).toBe("Hello");
    expect(updated[0].status).toBe("streaming");
  });

  it("marks message status transitions", () => {
    const assistant = makeMessage("assistant", "Done", "streaming");
    const updated = markMessageStatus([assistant], assistant.id, "done");
    expect(updated[0].status).toBe("done");
  });

  it("appends messages preserving order", () => {
    const first = makeMessage("user", "A", "done");
    const second = makeMessage("assistant", "B", "done");
    const merged = appendMessage(appendMessage([], first), second);
    expect(merged.map((m) => m.text)).toEqual(["A", "B"]);
  });
});
