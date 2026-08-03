import type { Route } from "next";

import { validatedReturnTo } from "./return-to";

export type AuthenticationMode =
  "sign-in" | "register" | "forgot" | "verify" | "reset";

const queryModes = new Set<AuthenticationMode>([
  "register",
  "forgot",
  "verify",
  "reset",
]);

export function firstQueryValue(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : value;
}

export function parseAuthenticationMode(
  value: string | null | undefined,
): AuthenticationMode {
  return value && queryModes.has(value as AuthenticationMode)
    ? (value as AuthenticationMode)
    : "sign-in";
}

export function authenticationHref({
  mode,
  returnTo,
}: {
  mode: AuthenticationMode;
  returnTo?: string;
}): Route {
  const query = new URLSearchParams();
  if (mode !== "sign-in") query.set("mode", mode);
  const safeReturnTo = validatedReturnTo(returnTo);
  if (safeReturnTo) query.set("returnTo", safeReturnTo);
  const suffix = query.toString();
  return (suffix ? `/login?${suffix}` : "/login") as Route;
}
