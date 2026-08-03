"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import type { components } from "@/lib/api/generated/schema";
import {
  ApiError,
  apiClient,
  clearAccessToken,
  publicApiClient,
  refreshAccessToken,
  setAccessToken,
} from "@/lib/api";
import { publishAuthEvent, subscribeToAuthEvents } from "./auth-channel";

export type AuthStatus =
  "bootstrapping" | "authenticated" | "anonymous" | "unavailable";
export type Actor = components["schemas"]["Actor"];
export type SignInInput = components["schemas"]["LoginRequest"];

type AuthSessionValue = {
  status: AuthStatus;
  actor: Actor | null;
  signIn: (input: SignInInput) => Promise<void>;
  signOut: () => Promise<void>;
  retryBootstrap: () => Promise<void>;
};

const AuthSessionContext = createContext<AuthSessionValue | null>(null);
function isAnonymousBootstrapError(error: unknown) {
  return (
    error instanceof ApiError &&
    [
      "auth_session_missing",
      "auth_session_expired",
      "auth_token_invalid_or_expired",
    ].includes(error.code ?? "")
  );
}

async function fetchActor() {
  const { data } = await apiClient.GET("/api/v1/me");
  if (!data) throw new Error("Actor response was empty");
  return data;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<AuthStatus>("bootstrapping");
  const [actor, setActor] = useState<Actor | null>(null);

  const clearSession = useCallback(() => {
    clearAccessToken();
    setActor(null);
    queryClient.clear();
    setStatus("anonymous");
  }, [queryClient]);

  const bootstrap = useCallback(async () => {
    setStatus("bootstrapping");
    try {
      await refreshAccessToken();
      setActor(await fetchActor());
      setStatus("authenticated");
    } catch (error) {
      clearAccessToken();
      setActor(null);
      setStatus(isAnonymousBootstrapError(error) ? "anonymous" : "unavailable");
    }
  }, []);

  useEffect(() => {
    const task = window.setTimeout(() => void bootstrap(), 0);
    return () => window.clearTimeout(task);
  }, [bootstrap]);

  useEffect(() => {
    return subscribeToAuthEvents((event) => {
      if (event === "signed-out") clearSession();
      if (event === "signed-in") void bootstrap();
    });
  }, [bootstrap, clearSession]);

  const signIn = useCallback(async (input: SignInInput) => {
    const { data } = await publicApiClient.POST("/api/v1/auth/login", {
      body: input,
    });
    if (!data) throw new Error("Access token response was empty");
    setAccessToken(data.access_token);
    setActor(await fetchActor());
    setStatus("authenticated");
    publishAuthEvent("signed-in");
  }, []);

  const signOut = useCallback(async () => {
    try {
      await apiClient.POST("/api/v1/auth/logout");
    } finally {
      clearSession();
      publishAuthEvent("signed-out");
    }
  }, [clearSession]);

  const value = useMemo<AuthSessionValue>(
    () => ({
      status,
      actor,
      signIn,
      signOut,
      retryBootstrap: bootstrap,
    }),
    [actor, bootstrap, signIn, signOut, status],
  );

  return (
    <AuthSessionContext.Provider value={value}>
      {children}
    </AuthSessionContext.Provider>
  );
}

export function useAuthSession() {
  const session = useContext(AuthSessionContext);
  if (!session)
    throw new Error("useAuthSession must be used inside AuthProvider");
  return session;
}
