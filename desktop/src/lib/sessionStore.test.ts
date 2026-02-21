import { describe, expect, it } from "vitest";
import { makeMessage } from "./chat";
import { appendToSession, getSessionMessages } from "./sessionStore";

describe("session store", () => {
  it("keeps transcripts isolated by session id", () => {
    let store = {};
    store = appendToSession(store, "s1", makeMessage("user", "hello", "done"));
    store = appendToSession(store, "s2", makeMessage("user", "world", "done"));

    expect(getSessionMessages(store, "s1").length).toBe(1);
    expect(getSessionMessages(store, "s2").length).toBe(1);
    expect(getSessionMessages(store, "s1")[0].text).toBe("hello");
  });
});
