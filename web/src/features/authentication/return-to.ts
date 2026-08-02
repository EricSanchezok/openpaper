export function safeReturnTo(value: string | null | undefined, fallback = "/") {
  if (!value?.startsWith("/") || value.startsWith("//")) return fallback;
  try {
    const target = new URL(value, "https://scholens.local");
    return target.origin === "https://scholens.local"
      ? `${target.pathname}${target.search}${target.hash}`
      : fallback;
  } catch {
    return fallback;
  }
}
