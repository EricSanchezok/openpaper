"use client";

import * as React from "react";

const MINIMUM_KEYBOARD_OCCLUSION = 96;
const CLOSED_KEYBOARD_STATE = {
  open: false,
  viewportHeight: undefined as number | undefined,
  viewportOffsetTop: undefined as number | undefined,
};

export type VisualViewportMetrics = {
  height: number;
  offsetTop: number;
};

export function calculateMobileKeyboardState({
  composerFocused,
  baselineViewportHeight,
  visualViewport,
}: {
  composerFocused: boolean;
  baselineViewportHeight: number;
  visualViewport?: VisualViewportMetrics;
}) {
  if (!composerFocused) return false;
  if (!visualViewport) return true;

  // offsetTop changes while Chrome pans the visual viewport during a swipe. It
  // does not mean the keyboard closed, so keyboard state must be derived from
  // the stable pre-focus height and the current visible height only.
  const occludedHeight = baselineViewportHeight - visualViewport.height;
  return occludedHeight >= MINIMUM_KEYBOARD_OCCLUSION;
}

export function useMobileKeyboard(
  dockRef: React.RefObject<HTMLElement | null>,
  enabled: boolean,
) {
  const [state, setState] = React.useState(CLOSED_KEYBOARD_STATE);
  const baselineViewportHeight = React.useRef<number | undefined>(undefined);

  React.useEffect(() => {
    if (!enabled) return;

    const visualViewport = window.visualViewport;
    let focusTimer: number | undefined;

    function currentViewportHeight() {
      return Math.max(
        window.innerHeight,
        visualViewport
          ? visualViewport.height + visualViewport.offsetTop
          : window.innerHeight,
      );
    }

    function update() {
      const activeElement = document.activeElement;
      const composerFocused = Boolean(
        activeElement instanceof HTMLElement &&
        dockRef.current?.contains(activeElement) &&
        activeElement.matches("[data-mobile-composer-input]"),
      );
      const open = calculateMobileKeyboardState({
        composerFocused,
        baselineViewportHeight:
          baselineViewportHeight.current ?? currentViewportHeight(),
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
        viewportOffsetTop: open ? visualViewport?.offsetTop : undefined,
      });
    }

    function scheduleUpdate() {
      window.clearTimeout(focusTimer);
      focusTimer = window.setTimeout(update, 0);
    }

    function handleFocusIn(event: FocusEvent) {
      const target = event.target;
      if (
        target instanceof HTMLElement &&
        dockRef.current?.contains(target) &&
        target.matches("[data-mobile-composer-input]")
      ) {
        baselineViewportHeight.current = currentViewportHeight();
      }
      scheduleUpdate();
    }

    function handleFocusOut() {
      scheduleUpdate();
      window.setTimeout(() => {
        const activeElement = document.activeElement;
        if (!(
          activeElement instanceof HTMLElement &&
          dockRef.current?.contains(activeElement) &&
          activeElement.matches("[data-mobile-composer-input]")
        )) {
          baselineViewportHeight.current = undefined;
        }
      }, 0);
    }

    update();
    window.addEventListener("resize", update);
    document.addEventListener("focusin", handleFocusIn);
    document.addEventListener("focusout", handleFocusOut);
    visualViewport?.addEventListener("resize", update);
    visualViewport?.addEventListener("scroll", update);

    return () => {
      window.clearTimeout(focusTimer);
      window.removeEventListener("resize", update);
      document.removeEventListener("focusin", handleFocusIn);
      document.removeEventListener("focusout", handleFocusOut);
      visualViewport?.removeEventListener("resize", update);
      visualViewport?.removeEventListener("scroll", update);
    };
  }, [dockRef, enabled]);

  return enabled ? state : CLOSED_KEYBOARD_STATE;
}
