import { describe, expect, it } from "vitest";

import { createLiveTurn, reduceLiveTurn } from "./conversation-state";

const running = {
  kind: "activity" as const,
  id: "search-1",
  sequence: 2,
  category: "search" as const,
  state: "running" as const,
  subject: "reasoning compression",
};
const responseId = "60000000-0000-4000-8000-000000000001";

function event<T extends object>(payload: T) {
  return { response_id: responseId, ...payload };
}

describe("Home live conversation state", () => {
  it("classifies one provisional item as progress without duplicating text", () => {
    let turn = createLiveTurn("turn-1", responseId, "Compare the papers");
    turn = reduceLiveTurn(
      turn,
      event({
        type: "assistant_item_start",
        item_id: "assistant:turn-1:1",
        sequence: 1,
      }),
    )!;
    turn = reduceLiveTurn(
      turn,
      event({
        type: "assistant_item_delta",
        item_id: "assistant:turn-1:1",
        delta: "I’ll inspect the available research.",
      }),
    )!;
    expect(turn.provisionalItems[0]?.content).toBe(
      "I’ll inspect the available research.",
    );

    turn = reduceLiveTurn(
      turn,
      event({
        type: "assistant_item_complete",
        item: {
          id: "assistant:turn-1:1",
          sequence: 1,
          phase: "progress",
          content: "I’ll inspect the available research.",
        },
      }),
    )!;

    expect(turn.provisionalItems).toEqual([]);
    expect(turn.content).toBe("");
    expect(turn.entries).toEqual([
      {
        kind: "progress",
        id: "assistant:turn-1:1",
        sequence: 1,
        content: "I’ll inspect the available research.",
      },
    ]);
  });

  it("keeps final text in the answer and ignores late deltas", () => {
    let turn = createLiveTurn("turn-1", responseId, "Question");
    turn = reduceLiveTurn(
      turn,
      event({
        type: "assistant_item_start",
        item_id: "assistant:turn-1:3",
        sequence: 3,
      }),
    )!;
    turn = reduceLiveTurn(
      turn,
      event({
        type: "assistant_item_delta",
        item_id: "assistant:turn-1:3",
        delta: "Final answer",
      }),
    )!;
    turn = reduceLiveTurn(
      turn,
      event({
        type: "assistant_item_complete",
        item: {
          id: "assistant:turn-1:3",
          sequence: 3,
          phase: "final",
          content: "Final answer",
        },
      }),
    )!;
    turn = reduceLiveTurn(
      turn,
      event({
        type: "assistant_item_delta",
        item_id: "assistant:turn-1:3",
        delta: " duplicated",
      }),
    )!;

    expect(turn.content).toBe("Final answer");
    expect(turn.provisionalItems).toEqual([]);
  });

  it("updates activity by ID, preserves order, and rejects stale running state", () => {
    let turn = createLiveTurn("turn-1", responseId, "Compare the papers");
    turn = reduceLiveTurn(
      turn,
      event({ type: "activity", activity: running }),
    )!;
    turn = reduceLiveTurn(
      turn,
      event({
        type: "activity",
        activity: {
          kind: "activity",
          id: "read-2",
          sequence: 3,
          category: "read",
          state: "running",
        },
      }),
    )!;
    turn = reduceLiveTurn(
      turn,
      event({
        type: "activity",
        activity: { ...running, state: "failed" },
      }),
    )!;
    turn = reduceLiveTurn(
      turn,
      event({ type: "activity", activity: running }),
    )!;

    expect(
      turn.entries.map((entry) =>
        entry.kind === "activity" ? [entry.id, entry.state] : [entry.id],
      ),
    ).toEqual([
      ["search-1", "failed"],
      ["read-2", "running"],
    ]);
  });

  it("uses terminal trace entries as canonical completed history", () => {
    let turn = reduceLiveTurn(
      createLiveTurn("turn-1", responseId, "Question"),
      event({
        type: "complete",
        turn_id: "turn-1",
        artifacts: [],
        trace: {
          entries: [{ ...running, state: "succeeded" }],
          citation_summary: {
            source_count: 3,
            annotation_count: 2,
            rejected_source_count: 0,
          },
        },
      }),
    );

    expect(turn?.state).toBe("complete");
    expect(turn?.entries[0]).toMatchObject({ state: "succeeded" });
    expect(turn?.trace?.citation_summary?.source_count).toBe(3);

    turn = reduceLiveTurn(
      turn,
      event({
        type: "activity",
        activity: { ...running, state: "failed" },
      }),
    );
    turn = reduceLiveTurn(
      turn,
      event({
        type: "assistant_item_delta",
        item_id: "assistant:turn-1:late",
        delta: "late text",
      }),
    );

    expect(turn?.entries[0]).toMatchObject({ state: "succeeded" });
    expect(turn?.provisionalItems).toEqual([]);
  });

  it("retains safe diagnostics from a terminal stream error", () => {
    const turn = reduceLiveTurn(
      createLiveTurn("turn-1", responseId, "Question"),
      event({
        type: "error",
        error: {
          code: "chat_stream_failed",
          kind: "dependency_failure",
          retryable: true,
          diagnostic_id: "diagnostic-123",
        },
      }),
    );

    expect(turn?.state).toBe("error");
    expect(turn?.failure).toEqual({
      code: "chat_stream_failed",
      kind: "dependency_failure",
      retryable: true,
      correlationId: undefined,
      diagnosticId: "diagnostic-123",
    });
  });

  it("ignores events emitted for a different response variant", () => {
    const turn = createLiveTurn("turn-1", responseId, "Question", "retry");
    const next = reduceLiveTurn(turn, {
      type: "assistant_item_delta",
      response_id: "60000000-0000-4000-8000-000000000099",
      item_id: "assistant:turn-1:late",
      delta: "stale variant",
    });

    expect(next).toEqual(turn);
  });
});
