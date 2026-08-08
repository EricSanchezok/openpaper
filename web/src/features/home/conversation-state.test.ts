import { describe, expect, it } from "vitest";

import { createLiveTurn, reduceLiveTurn } from "./conversation-state";

const running = {
  id: "search-1",
  sequence: 1,
  category: "search" as const,
  state: "running" as const,
  tool_name: "search_papers",
  subject: "reasoning compression",
};

describe("Home live Conversation state", () => {
  it("updates activity by ID and preserves sequence order", () => {
    let turn = createLiveTurn("turn-1", "Compare the papers");
    turn = reduceLiveTurn(turn, { type: "activity", activity: running })!;
    turn = reduceLiveTurn(turn, {
      type: "activity",
      activity: {
        id: "read-2",
        sequence: 2,
        category: "read",
        state: "running",
        tool_name: "get_paper_content",
      },
    })!;
    turn = reduceLiveTurn(turn, {
      type: "activity",
      activity: { ...running, state: "succeeded", source_count: 2 },
    })!;

    expect(turn.activities.map(({ id, state }) => ({ id, state }))).toEqual([
      { id: "search-1", state: "succeeded" },
      { id: "read-2", state: "running" },
    ]);
  });

  it("ignores a stale running update after a terminal activity state", () => {
    let turn = createLiveTurn("turn-1", "Compare the papers");
    turn = reduceLiveTurn(turn, {
      type: "activity",
      activity: { ...running, state: "failed" },
    })!;
    turn = reduceLiveTurn(turn, { type: "activity", activity: running })!;

    expect(turn.activities[0]?.state).toBe("failed");
  });

  it("uses the terminal trace as the canonical completed history", () => {
    const turn = reduceLiveTurn(createLiveTurn("turn-1", "Question"), {
      type: "complete",
      turn_id: "turn-1",
      artifacts: [],
      trace: {
        activities: [{ ...running, state: "succeeded" }],
        citation_summary: {
          source_count: 3,
          annotation_count: 2,
          rejected_source_count: 0,
        },
      },
    });

    expect(turn?.state).toBe("complete");
    expect(turn?.activities[0]?.state).toBe("succeeded");
    expect(turn?.trace?.citation_summary?.source_count).toBe(3);
  });
});
