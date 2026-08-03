import type { Route } from "next";

export function safeReturnTo(value: string | null | undefined, fallback = "/") {
  return validatedReturnTo(value) ?? fallback;
}

export function validatedReturnTo(
  value: string | null | undefined,
): Route | undefined {
  if (!value?.startsWith("/") || value.startsWith("//")) return undefined;
  try {
    const target = new URL(value, "https://scholens.local");
    return target.origin === "https://scholens.local"
      ? (`${target.pathname}${target.search}${target.hash}` as Route)
      : undefined;
  } catch {
    return undefined;
  }
}
