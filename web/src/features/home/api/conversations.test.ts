import { describe, expect, it } from "vitest";

import { parseConversationEventBlock } from "./conversations";

describe("conversation SSE parsing", () => {
  it("parses a typed standard SSE event", () => {
    expect(
      parseConversationEventBlock(
        'event: assistant_item_delta\ndata: {"type":"assistant_item_delta","item_id":"assistant-1","delta":"hello"}',
      ),
    ).toEqual({
      type: "assistant_item_delta",
      item_id: "assistant-1",
      delta: "hello",
    });
  });

  it("joins multiline data fields and ignores comments", () => {
    expect(
      parseConversationEventBlock(
        ': keep-alive\nevent: activity\ndata: {"type":"activity",\ndata: "activity":{"kind":"activity","id":"search-1","sequence":1,"category":"search","state":"running"}}',
      ),
    ).toEqual({
      type: "activity",
      activity: {
        kind: "activity",
        id: "search-1",
        sequence: 1,
        category: "search",
        state: "running",
      },
    });
  });

  it("ignores blocks without data", () => {
    expect(parseConversationEventBlock(": keep-alive")).toBeUndefined();
  });

  it("rejects event discriminators outside the generated contract", () => {
    expect(() =>
      parseConversationEventBlock(
        'data: {"type":"content_delta","delta":"legacy"}',
      ),
    ).toThrow("Conversation stream event was malformed");
  });
});
