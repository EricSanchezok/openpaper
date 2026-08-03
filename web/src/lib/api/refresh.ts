import { clientEnvironment } from "@/lib/env/client";
import { clearAccessToken, setAccessToken } from "./access-token";
import { toApiError } from "./errors";

type TokenResponse = { access_token: string };

let refreshFlight: Promise<string> | undefined;
const storageLockKey = "scholens-auth-refresh-lock";
const lockLeaseMs = 10_000;

function wait(milliseconds: number) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

async function withStorageRefreshLock<T>(operation: () => Promise<T>) {
  if (typeof window === "undefined" || !window.localStorage) return operation();
  const owner = crypto.randomUUID();
  const deadline = Date.now() + lockLeaseMs;

  while (Date.now() < deadline) {
    const now = Date.now();
    const rawLease = window.localStorage.getItem(storageLockKey);
    const lease = rawLease
      ? (JSON.parse(rawLease) as { owner: string; expiresAt: number })
      : undefined;
    if (!lease || lease.expiresAt <= now) {
      window.localStorage.setItem(
        storageLockKey,
        JSON.stringify({ owner, expiresAt: now + lockLeaseMs }),
      );
      const acquired = JSON.parse(
        window.localStorage.getItem(storageLockKey) ?? "{}",
      ) as { owner?: string };
      if (acquired.owner === owner) {
        try {
          return await operation();
        } finally {
          const current = JSON.parse(
            window.localStorage.getItem(storageLockKey) ?? "{}",
          ) as { owner?: string };
          if (current.owner === owner)
            window.localStorage.removeItem(storageLockKey);
        }
      }
    }
    await wait(50);
  }

  throw new Error("Timed out waiting for the authentication refresh lock");
}

async function withCrossTabRefreshLock<T>(operation: () => Promise<T>) {
  if (typeof navigator !== "undefined" && navigator.locks) {
    return navigator.locks.request("scholens-auth-refresh", operation);
  }
  return withStorageRefreshLock(operation);
}

async function requestRefresh(): Promise<string> {
  const response = await fetch(
    `${clientEnvironment.NEXT_PUBLIC_API_URL}/api/v1/auth/refresh`,
    { method: "POST", credentials: "include" },
  );
  if (!response.ok) {
    if (response.status === 401) clearAccessToken();
    throw await toApiError(response);
  }
  const body = (await response.json()) as TokenResponse;
  setAccessToken(body.access_token);
  return body.access_token;
}

export function refreshAccessToken(): Promise<string> {
  refreshFlight ??= withCrossTabRefreshLock(requestRefresh).finally(() => {
    refreshFlight = undefined;
  });
  return refreshFlight;
}

export function resetRefreshForTests() {
  refreshFlight = undefined;
}
