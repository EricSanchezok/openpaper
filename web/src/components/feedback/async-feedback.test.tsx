import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AsyncBoundary } from "./async-feedback";

describe("AsyncBoundary", () => {
  it("renders data when the request succeeds", () => {
    render(
      <AsyncBoundary data={["paper"]}>
        {(items) => <p>{items[0]}</p>}
      </AsyncBoundary>,
    );
    expect(screen.getByText("paper")).toBeInTheDocument();
  });

  it("renders an empty state from the caller's domain rule", () => {
    render(
      <AsyncBoundary data={[]} empty={(items) => items.length === 0}>
        {() => <p>content</p>}
      </AsyncBoundary>,
    );
    expect(screen.getByText("Nothing here yet")).toBeInTheDocument();
  });
});
