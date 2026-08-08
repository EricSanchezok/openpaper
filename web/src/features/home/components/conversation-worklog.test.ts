import { describe, expect, it } from "vitest";

import type { ConversationTraceEntry } from "../conversation-state";
import { groupWorklogEntries } from "./conversation-worklog";

function activity(
  id: string,
  sequence: number,
  category: "search" | "read",
): ConversationTraceEntry {
  return {
    kind: "activity",
    id,
    sequence,
    category,
    state: "succeeded",
  };
}

describe("conversation worklog grouping", () => {
  it("groups consecutive tool activities into one batch", () => {
    const rows = groupWorklogEntries([
      activity("search-1", 1, "search"),
      activity("read-2", 2, "read"),
    ]);

    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ kind: "batch" });
    if (rows[0]?.kind === "batch") {
      expect(rows[0].activities.map((item) => item.id)).toEqual([
        "search-1",
        "read-2",
      ]);
    }
  });

  it("uses progress entries to split tool batches in sequence order", () => {
    const entries: ConversationTraceEntry[] = [
      activity("read-3", 3, "read"),
      activity("search-1", 1, "search"),
      {
        kind: "progress",
        id: "assistant-2",
        sequence: 2,
        content: "The first strategy was too narrow, so I’ll broaden it.",
      },
    ];

    expect(groupWorklogEntries(entries).map((row) => row.kind)).toEqual([
      "batch",
      "progress",
      "batch",
    ]);
  });
});
