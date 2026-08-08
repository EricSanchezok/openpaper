import { describe, expect, it } from "vitest";

import { annotateMarkdownContent } from "./message-content";

describe("annotateMarkdownContent", () => {
  it("groups source keys that annotate the same answer span", () => {
    expect(
      annotateMarkdownContent("Grounded answer.", [
        { start_offset: 0, end_offset: 8, source_keys: [2] },
        { start_offset: 0, end_offset: 8, source_keys: [1, 2] },
      ]),
    ).toBe("Grounded [1,2](#scholens-source=1,2) answer.");
  });

  it("inserts citations from the end so earlier offsets stay stable", () => {
    expect(
      annotateMarkdownContent("Alpha and beta", [
        { start_offset: 0, end_offset: 5, source_keys: [1] },
        { start_offset: 10, end_offset: 14, source_keys: [2] },
      ]),
    ).toBe("Alpha [1](#scholens-source=1) and beta [2](#scholens-source=2)");
  });

  it("ignores annotations outside the final answer", () => {
    expect(
      annotateMarkdownContent("Answer", [
        { start_offset: -1, end_offset: 3, source_keys: [1] },
        { start_offset: 0, end_offset: 20, source_keys: [2] },
      ]),
    ).toBe("Answer");
  });
});
