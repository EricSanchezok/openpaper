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
        ': keep-alive\nevent: activity\ndata: {"type":"activity",\ndata: "activity":{"id":"search-1","sequence":1,"category":"search","state":"running","tool_name":"search_papers"}}',
      ),
    ).toEqual({
      type: "activity",
      activity: {
        id: "search-1",
        sequence: 1,
        category: "search",
        state: "running",
        tool_name: "search_papers",
      },
    });
  });

  it("ignores blocks without data", () => {
    expect(parseConversationEventBlock(": keep-alive")).toBeUndefined();
  });
});
