"use client";

import * as React from "react";

const MINIMUM_KEYBOARD_OCCLUSION = 96;
const CLOSED_KEYBOARD_STATE = {
  open: false,
  viewportHeight: undefined as number | undefined,
};

export type VisualViewportMetrics = {
  height: number;
  offsetTop: number;
};

export function calculateMobileKeyboardState({
  composerFocused,
  layoutViewportHeight,
  visualViewport,
}: {
  composerFocused: boolean;
  layoutViewportHeight: number;
  visualViewport?: VisualViewportMetrics;
}) {
  if (!composerFocused) return false;
  if (!visualViewport) return true;

  const occludedHeight =
    layoutViewportHeight - visualViewport.height - visualViewport.offsetTop;
  return occludedHeight >= MINIMUM_KEYBOARD_OCCLUSION;
}

export function useMobileKeyboard(
  dockRef: React.RefObject<HTMLElement | null>,
  enabled: boolean,
) {
  const [state, setState] = React.useState(CLOSED_KEYBOARD_STATE);

  React.useEffect(() => {
    if (!enabled) return;

    const visualViewport = window.visualViewport;
    let focusTimer: number | undefined;

    function update() {
      const activeElement = document.activeElement;
      const composerFocused = Boolean(
        activeElement instanceof HTMLElement &&
        dockRef.current?.contains(activeElement) &&
        activeElement.matches("[data-mobile-composer-input]"),
      );
      const open = calculateMobileKeyboardState({
        composerFocused,
        layoutViewportHeight: window.innerHeight,
        visualViewport: visualViewport
          ? {
              height: visualViewport.height,
              offsetTop: visualViewport.offsetTop,
            }
          : undefined,
      });
      setState({
        open,
        viewportHeight: open ? visualViewport?.height : undefined,
      });
    }

    function scheduleUpdate() {
      window.clearTimeout(focusTimer);
      focusTimer = window.setTimeout(update, 0);
    }

    update();
    window.addEventListener("resize", update);
    document.addEventListener("focusin", scheduleUpdate);
    document.addEventListener("focusout", scheduleUpdate);
    visualViewport?.addEventListener("resize", update);
    visualViewport?.addEventListener("scroll", update);

    return () => {
      window.clearTimeout(focusTimer);
      window.removeEventListener("resize", update);
      document.removeEventListener("focusin", scheduleUpdate);
      document.removeEventListener("focusout", scheduleUpdate);
      visualViewport?.removeEventListener("resize", update);
      visualViewport?.removeEventListener("scroll", update);
    };
  }, [dockRef, enabled]);

  return enabled ? state : CLOSED_KEYBOARD_STATE;
}
