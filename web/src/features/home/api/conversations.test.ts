import { describe, expect, it } from "vitest";

import { parseConversationEventBlock } from "./conversations";

describe("conversation SSE parsing", () => {
  it("parses a typed standard SSE event", () => {
    expect(
      parseConversationEventBlock(
        'event: content_delta\ndata: {"type":"content_delta","delta":"hello"}',
      ),
    ).toEqual({ type: "content_delta", delta: "hello" });
  });

  it("joins multiline data fields and ignores comments", () => {
    expect(
      parseConversationEventBlock(
        ': keep-alive\nevent: status\ndata: {"type":"status",\ndata: "message":"Searching"}',
      ),
    ).toEqual({ type: "status", message: "Searching" });
  });

  it("ignores blocks without data", () => {
    expect(parseConversationEventBlock(": keep-alive")).toBeUndefined();
  });
});
