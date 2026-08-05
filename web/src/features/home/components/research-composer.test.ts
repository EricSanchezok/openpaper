import { describe, expect, it } from "vitest";

import { getResearchContextDisplay } from "./research-composer";

const projects = [{ id: "project-1", title: "A very long project title" }];
const papers = [
  {
    document: {
      document_id: "paper-1",
      original_filename: "paper-1.pdf",
      title: "Paper title",
    },
    metadata_overrides: { title: "Curated paper title" },
  },
  {
    document: {
      document_id: "paper-2",
      original_filename: "paper-2.pdf",
      title: "Second paper",
    },
    metadata_overrides: {},
  },
];

describe("research context display", () => {
  it("shows the entire library and an empty selection distinctly", () => {
    expect(
      getResearchContextDisplay({ kind: "library" }, papers, projects),
    ).toEqual({ kind: "library" });
    expect(
      getResearchContextDisplay(
        { kind: "selection", project_ids: [], document_ids: [] },
        papers,
        projects,
      ),
    ).toEqual({ kind: "empty" });
  });

  it("uses the full title for one selected project or paper", () => {
    expect(
      getResearchContextDisplay(
        {
          kind: "selection",
          project_ids: ["project-1"],
          document_ids: [],
        },
        papers,
        projects,
      ),
    ).toEqual({ kind: "project", title: "A very long project title" });
    expect(
      getResearchContextDisplay(
        {
          kind: "selection",
          project_ids: [],
          document_ids: ["paper-1"],
        },
        papers,
        projects,
      ),
    ).toEqual({ kind: "paper", title: "Curated paper title" });
  });

  it("summarizes multiple papers and mixed selections by count", () => {
    expect(
      getResearchContextDisplay(
        {
          kind: "selection",
          project_ids: [],
          document_ids: ["paper-1", "paper-2"],
        },
        papers,
        projects,
      ),
    ).toEqual({ kind: "papers", count: 2 });
    expect(
      getResearchContextDisplay(
        {
          kind: "selection",
          project_ids: ["project-1"],
          document_ids: ["paper-1", "paper-2"],
        },
        papers,
        projects,
      ),
    ).toEqual({ kind: "items", count: 3 });
  });
});
