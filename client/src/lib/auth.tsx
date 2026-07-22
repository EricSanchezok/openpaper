"use client";

import { ShieldX } from "lucide-react";
import {
    createContext,
    ReactNode,
    useCallback,
    useContext,
    useEffect,
    useMemo,
    useState,
} from "react";

import { fetchFromApi } from "./api";
import {
    clearSession,
    establishSession,
    hasRefreshToken,
    refreshAccessToken,
    subscribeToSessionChanges,
    TokenResponse,
} from "./auth-session";

export type AccountStatus = "pending_verification" | "active" | "disabled" | "locked";

export interface BasicUser {
    id?: number | string;
    display_name: string | null;
}

export interface User extends BasicUser {
    id: number;
    email: string;
    status: AccountStatus;
    email_verified: boolean;
    locale: string | null;
    is_admin: boolean;
    is_active: boolean;
    is_blocked: boolean;
}

interface AuthContextType {
    user: User | null;
    loading: boolean;
    error: string | null;
    login: (email: string, password: string) => Promise<User>;
    register: (email: string, password: string, displayName: string) => Promise<string>;
    verifyEmail: (token: string) => Promise<string>;
    resendVerification: (email: string) => Promise<string>;
    forgotPassword: (email: string) => Promise<string>;
    resetPassword: (token: string, newPassword: string) => Promise<string>;
    updateProfile: (displayName: string) => Promise<User>;
    refreshUser: () => Promise<User>;
    logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
    const [user, setUser] = useState<User | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const loadUser = useCallback(async (): Promise<User> => {
        const currentUser = (await fetchFromApi("/api/me")) as User;
        setUser(currentUser);
        setError(null);
        return currentUser;
    }, []);

    useEffect(() => {
        let active = true;
        const restore = async () => {
            if (!hasRefreshToken()) {
                if (active) {
                    setUser(null);
                    setLoading(false);
                }
                return;
            }
            try {
                await refreshAccessToken();
                const currentUser = await loadUser();
                if (!active) return;
                setUser(currentUser);
            } catch (restoreError) {
                if (!active) return;
                clearSession(false);
                setUser(null);
                setError(restoreError instanceof Error ? restoreError.message : null);
            } finally {
                if (active) setLoading(false);
            }
        };

        void restore();
        const unsubscribe = subscribeToSessionChanges(() => {
            if (!hasRefreshToken()) {
                setUser(null);
                setLoading(false);
                return;
            }
            setLoading(true);
            void refreshAccessToken()
                .then(loadUser)
                .catch(() => {
                    clearSession(false);
                    setUser(null);
                })
                .finally(() => setLoading(false));
        });
        return () => {
            active = false;
            unsubscribe();
        };
    }, [loadUser]);

    const login = useCallback(async (email: string, password: string): Promise<User> => {
        setLoading(true);
        setError(null);
        try {
            const tokens = (await fetchFromApi("/api/auth/login", {
                method: "POST",
                body: JSON.stringify({ email, password }),
            })) as TokenResponse;
            establishSession(tokens);
            return await loadUser();
        } catch (loginError) {
            const message = loginError instanceof Error ? loginError.message : "Unable to sign in";
            setError(message);
            throw loginError;
        } finally {
            setLoading(false);
        }
    }, [loadUser]);

    const register = useCallback(
        async (email: string, password: string, displayName: string): Promise<string> => {
            const response = await fetchFromApi("/api/auth/register", {
                method: "POST",
                body: JSON.stringify({ email, password, display_name: displayName }),
            });
            return response.message as string;
        },
        [],
    );

    const messageAction = useCallback(async (endpoint: string, body: object): Promise<string> => {
        const response = await fetchFromApi(endpoint, {
            method: "POST",
            body: JSON.stringify(body),
        });
        return response.message as string;
    }, []);

    const updateProfile = useCallback(async (displayName: string): Promise<User> => {
        await fetchFromApi("/api/user/profile", {
            method: "PUT",
            body: JSON.stringify({ display_name: displayName }),
        });
        return loadUser();
    }, [loadUser]);

    const logout = useCallback(async () => {
        setLoading(true);
        try {
            await fetchFromApi("/api/auth/logout", { method: "POST" });
        } catch {
            // Local logout remains authoritative if the API is unavailable.
        } finally {
            clearSession();
            setUser(null);
            setError(null);
            setLoading(false);
        }
    }, []);

    const value = useMemo<AuthContextType>(() => ({
        user,
        loading,
        error,
        login,
        register,
        verifyEmail: (token) => messageAction("/api/auth/verify-email", { token }),
        resendVerification: (email) => messageAction("/api/auth/resend-verification", { email }),
        forgotPassword: (email) => messageAction("/api/auth/forgot-password", { email }),
        resetPassword: (token, newPassword) =>
            messageAction("/api/auth/reset-password", { token, new_password: newPassword }),
        updateProfile,
        refreshUser: loadUser,
        logout,
    }), [
        user,
        loading,
        error,
        login,
        register,
        messageAction,
        updateProfile,
        loadUser,
        logout,
    ]);

    if (!loading && !user && error === "OpenPaper access is suspended") {
        return (
            <AuthContext.Provider value={value}>
                <div className="flex h-screen items-center justify-center p-4">
                    <div className="w-full max-w-lg space-y-4 text-center">
                        <div className="mx-auto w-fit rounded-full bg-red-100 p-4 dark:bg-red-900/30">
                            <ShieldX className="h-8 w-8 text-red-600 dark:text-red-400" />
                        </div>
                        <h1 className="text-2xl font-bold">Account suspended</h1>
                        <p className="text-muted-foreground">
                            OpenPaper access for this account is suspended. Contact support if you
                            believe this is an error.
                        </p>
                        <button className="rounded-md border px-4 py-2" onClick={() => void logout()}>
                            Sign out
                        </button>
                    </div>
                </div>
            </AuthContext.Provider>
        );
    }

    return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextType {
    const context = useContext(AuthContext);
    if (!context) throw new Error("useAuth must be used within an AuthProvider");
    return context;
}
