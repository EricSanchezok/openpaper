import { describe, expect, it } from "vitest";

import { calculateMobileKeyboardState } from "./use-mobile-keyboard";

describe("mobile keyboard state", () => {
  it("stays closed when the Composer is not focused", () => {
    expect(
      calculateMobileKeyboardState({
        composerFocused: false,
        layoutViewportHeight: 844,
        visualViewport: { height: 500, offsetTop: 0 },
      }),
    ).toBe(false);
  });

  it("opens when the visual viewport is materially occluded", () => {
    expect(
      calculateMobileKeyboardState({
        composerFocused: true,
        layoutViewportHeight: 844,
        visualViewport: { height: 520, offsetTop: 0 },
      }),
    ).toBe(true);
  });

  it("does not hide navigation for a hardware keyboard", () => {
    expect(
      calculateMobileKeyboardState({
        composerFocused: true,
        layoutViewportHeight: 844,
        visualViewport: { height: 800, offsetTop: 0 },
      }),
    ).toBe(false);
  });

  it("falls back to focus when visualViewport is unavailable", () => {
    expect(
      calculateMobileKeyboardState({
        composerFocused: true,
        layoutViewportHeight: 844,
      }),
    ).toBe(true);
  });
});
