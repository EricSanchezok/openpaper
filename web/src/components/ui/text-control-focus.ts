"use client";

import * as React from "react";

type FocusOrigin = "keyboard" | "pointer" | null;

let lastInteraction: Exclude<FocusOrigin, null> = "pointer";
let listening = false;

function listenForInputModality() {
  if (listening || typeof document === "undefined") return;
  listening = true;

  document.addEventListener(
    "keydown",
    () => {
      lastInteraction = "keyboard";
    },
    true,
  );
  document.addEventListener(
    "pointerdown",
    () => {
      lastInteraction = "pointer";
    },
    true,
  );
}

type FocusHandlers<T extends HTMLElement> = Pick<
  React.HTMLAttributes<T>,
  "onBlur" | "onFocus"
>;

export function useTextControlFocus<T extends HTMLElement>({
  onBlur,
  onFocus,
}: FocusHandlers<T> = {}) {
  const [focusOrigin, setFocusOrigin] = React.useState<FocusOrigin>(null);

  React.useEffect(listenForInputModality, []);

  return {
    focusOrigin,
    focusHandlers: {
      onBlur(event: React.FocusEvent<T>) {
        setFocusOrigin(null);
        onBlur?.(event);
      },
      onFocus(event: React.FocusEvent<T>) {
        setFocusOrigin(lastInteraction);
        onFocus?.(event);
      },
    },
  };
}
