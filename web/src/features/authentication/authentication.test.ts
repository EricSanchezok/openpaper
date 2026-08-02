import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  authenticatedFetch,
  clearAccessToken,
  getAccessToken,
  refreshAccessToken,
  resetRefreshForTests,
  setAccessToken,
} from "@/lib/api";
import { createAuthSchemas } from "./schemas";
import { safeReturnTo } from "./return-to";
import { publishAuthEvent, subscribeToAuthEvents } from "./auth-channel";

const messages = {
  email: "email",
  passwordRequired: "required",
  passwordMinimum: "minimum",
  passwordMismatch: "mismatch",
  tokenRequired: "token",
};

describe("authentication domain foundation", () => {
  beforeEach(() => {
    clearAccessToken();
    resetRefreshForTests();
    vi.restoreAllMocks();
  });

  it("keeps the access token in memory instead of persistent storage", () => {
    const storage = vi.spyOn(Storage.prototype, "setItem");
    setAccessToken("memory-only");
    expect(getAccessToken()).toBe("memory-only");
    expect(storage).not.toHaveBeenCalled();
  });

  it("allows only same-origin relative return paths", () => {
    expect(safeReturnTo("/library?view=recent#paper")).toBe(
      "/library?view=recent#paper",
    );
    expect(safeReturnTo("//evil.example/steal")).toBe("/");
    expect(safeReturnTo("https://evil.example/steal")).toBe("/");
  });

  it("does not send confirm password and enforces the 12-character rule", () => {
    const schemas = createAuthSchemas(messages);
    expect(
      schemas.register.safeParse({
        email: "eric@example.com",
        password: "short",
        confirmPassword: "short",
      }).success,
    ).toBe(false);
    const result = schemas.register.parse({
      displayName: "Eric",
      email: "eric@example.com",
      password: "twelve-chars!",
      confirmPassword: "twelve-chars!",
    });
    expect(result).not.toHaveProperty("confirmPassword");
  });

  it("coalesces concurrent refresh calls", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ access_token: "fresh" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    await Promise.all([refreshAccessToken(), refreshAccessToken()]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("refreshes once and replays a protected request once", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(null, { status: 401 }))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ access_token: "fresh" }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(new Response(null, { status: 204 }));

    const response = await authenticatedFetch(
      "http://localhost:8000/api/v1/projects",
    );
    expect(response.status).toBe(204);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    const retry = fetchMock.mock.calls[2]?.[0];
    expect(retry).toBeInstanceOf(Request);
    expect((retry as Request).headers.get("authorization")).toBe(
      "Bearer fresh",
    );
  });

  it("never recursively refreshes an authentication endpoint", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(null, { status: 401 }));
    const response = await authenticatedFetch(
      "http://localhost:8000/api/v1/auth/login",
      { method: "POST" },
    );
    expect(response.status).toBe(401);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("synchronizes only session events across tabs and never a token", () => {
    const messages: unknown[] = [];
    class MockChannel {
      static channels: MockChannel[] = [];
      onmessage: ((event: MessageEvent) => void) | null = null;
      constructor(public name: string) {
        MockChannel.channels.push(this);
      }
      postMessage(value: unknown) {
        messages.push(value);
        for (const channel of MockChannel.channels) {
          if (channel !== this)
            channel.onmessage?.({ data: value } as MessageEvent);
        }
      }
      close() {}
    }
    vi.stubGlobal("BroadcastChannel", MockChannel);
    const listener = vi.fn();
    const unsubscribe = subscribeToAuthEvents(listener);
    publishAuthEvent("signed-out");
    expect(listener).toHaveBeenCalledWith("signed-out");
    expect(messages).toEqual(["signed-out"]);
    expect(JSON.stringify(messages)).not.toContain("access_token");
    unsubscribe();
    vi.unstubAllGlobals();
  });
});
