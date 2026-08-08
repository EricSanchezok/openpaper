/**
 * The shared keyboard-only focus treatment for native interactive controls.
 *
 * Pointer and touch interactions never receive a decorative focus ring. The
 * ring is intentionally a single semantic pixel so focus remains discoverable
 * without changing component geometry or introducing a high-contrast frame.
 */
export const keyboardFocusRing =
  "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-focus-ring)]";
