import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it } from "vitest";

import messages from "@/i18n/messages/en.json";

import { AsyncBoundary } from "./async-feedback";

function renderWithIntl(node: React.ReactNode) {
  return render(
    <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
      {node}
    </NextIntlClientProvider>,
  );
}

describe("AsyncBoundary", () => {
  it("renders data when the request succeeds", () => {
    renderWithIntl(
      <AsyncBoundary data={["paper"]}>
        {(items) => <p>{items[0]}</p>}
      </AsyncBoundary>,
    );
    expect(screen.getByText("paper")).toBeInTheDocument();
  });

  it("renders an empty state from the caller's domain rule", () => {
    renderWithIntl(
      <AsyncBoundary data={[]} empty={(items) => items.length === 0}>
        {() => <p>content</p>}
      </AsyncBoundary>,
    );
    expect(screen.getByText("Nothing here yet")).toBeInTheDocument();
  });
});
