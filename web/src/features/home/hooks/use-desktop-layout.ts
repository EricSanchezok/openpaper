"use client";

import * as React from "react";

const DESKTOP_QUERY = "(min-width: 64rem)";

function subscribe(onStoreChange: () => void) {
  const mediaQuery = window.matchMedia(DESKTOP_QUERY);
  mediaQuery.addEventListener("change", onStoreChange);
  return () => mediaQuery.removeEventListener("change", onStoreChange);
}

function getSnapshot() {
  return window.matchMedia(DESKTOP_QUERY).matches;
}

function getServerSnapshot() {
  return false;
}

export function useDesktopLayout() {
  return React.useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
