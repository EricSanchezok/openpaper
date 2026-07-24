"use client";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
    Card,
    CardContent,
    CardDescription,
    CardFooter,
    CardHeader,
    CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { fetchFromApi } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { AlertCircle, ArrowLeft, Check, Loader2, Tag } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useEffect, useMemo, useState } from "react";

const REFERRAL_STORAGE_KEY = "op_ref";
const REFERRAL_MANUAL_FLAG_KEY = "op_ref_via_manual";
const REFERRAL_CODE_PATTERN = /^[A-Z0-9]{4,16}$/;

type Mode = "signin" | "register" | "verify" | "forgot" | "reset";

const COPY: Record<Mode, { title: string; description: string }> = {
    signin: {
        title: "Sign in to Scholens",
        description: "Access your papers, projects, and annotations.",
    },
    register: {
        title: "Create your Scholens account",
        description: "One identity for Scholens and the SanchezCloud ecosystem.",
    },
    verify: {
        title: "Verify your email",
        description: "Confirm the email address for your Scholens account.",
    },
    forgot: {
        title: "Reset your password",
        description: "We will email you a secure password reset link.",
    },
    reset: {
        title: "Choose a new password",
        description: "Enter a new password to finish securing your account.",
    },
};

function safeReturnTo(value: string | null): string {
    return value?.startsWith("/") && !value.startsWith("//") ? value : "/";
}

async function attributeStoredReferral(): Promise<void> {
    const code = localStorage.getItem(REFERRAL_STORAGE_KEY);
    if (!code) return;
    const viaLink = localStorage.getItem(REFERRAL_MANUAL_FLAG_KEY) !== "true";
    try {
        await fetchFromApi("/api/referral/attribute", {
            method: "POST",
            body: JSON.stringify({ code, via_link: viaLink }),
        });
    } catch {
        // Referral failure must not block account access.
    } finally {
        localStorage.removeItem(REFERRAL_STORAGE_KEY);
        localStorage.removeItem(REFERRAL_MANUAL_FLAG_KEY);
    }
}

function LoginContent() {
    const auth = useAuth();
    const router = useRouter();
    const searchParams = useSearchParams();
    const returnTo = safeReturnTo(searchParams.get("returnTo"));
    const actionToken = searchParams.get("token") ?? "";
    const requestedMode = searchParams.get("mode");
    const initialMode: Mode = actionToken && (requestedMode === "verify" || requestedMode === "reset")
        ? requestedMode
        : "signin";

    const [mode, setMode] = useState<Mode>(initialMode);
    const [email, setEmail] = useState("");
    const [displayName, setDisplayName] = useState("");
    const [password, setPassword] = useState("");
    const [confirmPassword, setConfirmPassword] = useState("");
    const [token, setToken] = useState(actionToken);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);
    const [newAccount, setNewAccount] = useState(false);
    const [referralCode, setReferralCode] = useState("");
    const [referralOpen, setReferralOpen] = useState(false);
    const [referralApplied, setReferralApplied] = useState(false);

    useEffect(() => {
        const storedCode = localStorage.getItem(REFERRAL_STORAGE_KEY);
        if (!storedCode) return;
        setReferralCode(storedCode);
        setReferralApplied(true);
        setReferralOpen(true);
    }, []);

    useEffect(() => {
        if (actionToken) window.history.replaceState({}, "", "/login");
    }, [actionToken]);

    useEffect(() => {
        if (auth.user && !auth.loading) router.replace(returnTo);
    }, [auth.user, auth.loading, returnTo, router]);

    const passwordMismatch = useMemo(
        () => (mode === "register" || mode === "reset")
            && Boolean(confirmPassword)
            && password !== confirmPassword,
        [confirmPassword, mode, password],
    );

    const changeMode = (nextMode: Mode) => {
        setMode(nextMode);
        setError(null);
        setNotice(null);
        setToken("");
        setConfirmPassword("");
    };

    const applyReferralCode = () => {
        const normalized = referralCode.trim().toUpperCase();
        if (!REFERRAL_CODE_PATTERN.test(normalized)) {
            setError("That referral code does not look right.");
            return;
        }
        localStorage.setItem(REFERRAL_STORAGE_KEY, normalized);
        localStorage.setItem(REFERRAL_MANUAL_FLAG_KEY, "true");
        setReferralCode(normalized);
        setReferralApplied(true);
        setError(null);
    };

    const submit = async (event: FormEvent) => {
        event.preventDefault();
        setBusy(true);
        setError(null);
        setNotice(null);
        try {
            if (mode === "signin") {
                await auth.login(email, password);
                await attributeStoredReferral();
                router.replace(returnTo);
            } else if (mode === "register") {
                if (password.length < 12) throw new Error("Password must be at least 12 characters.");
                if (passwordMismatch) throw new Error("Passwords do not match.");
                const message = await auth.register(email, password, displayName.trim());
                setNewAccount(true);
                setNotice(message);
                setMode("verify");
            } else if (mode === "verify") {
                const message = await auth.verifyEmail(token.trim());
                setNotice(message);
                if (password) {
                    await auth.login(email, password);
                    await attributeStoredReferral();
                    router.replace(newAccount ? "/onboarding" : returnTo);
                } else {
                    setMode("signin");
                }
            } else if (mode === "forgot") {
                setNotice(await auth.forgotPassword(email));
            } else {
                if (password.length < 12) throw new Error("Password must be at least 12 characters.");
                if (passwordMismatch) throw new Error("Passwords do not match.");
                setNotice(await auth.resetPassword(token.trim(), password));
                setMode("signin");
                setPassword("");
                setConfirmPassword("");
            }
        } catch (submitError) {
            setError(submitError instanceof Error ? submitError.message : "Authentication failed.");
        } finally {
            setBusy(false);
        }
    };

    if (auth.loading) {
        return <div className="flex h-full items-center justify-center"><Loader2 className="h-10 w-10 animate-spin" /></div>;
    }

    return (
        <div className="flex h-full items-center justify-center p-4">
            <Card className="relative w-full max-w-md">
                <CardHeader className="text-center">
                    {mode !== "signin" && (
                        <Button
                            variant="ghost"
                            size="icon"
                            className="absolute left-5 top-6"
                            onClick={() => changeMode("signin")}
                        >
                            <ArrowLeft className="h-5 w-5" />
                        </Button>
                    )}
                    <CardTitle className="text-2xl">{COPY[mode].title}</CardTitle>
                    <CardDescription>{COPY[mode].description}</CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                    {(error || auth.error) && (
                        <Alert variant="destructive">
                            <AlertCircle className="h-4 w-4" />
                            <AlertDescription>{error || auth.error}</AlertDescription>
                        </Alert>
                    )}
                    {notice && (
                        <Alert>
                            <Check className="h-4 w-4" />
                            <AlertDescription>{notice}</AlertDescription>
                        </Alert>
                    )}

                    {(mode !== "verify" || token) && <form onSubmit={submit} className="space-y-3">
                        {(mode === "signin" || mode === "register" || mode === "forgot") && (
                            <Input
                                type="email"
                                autoComplete="email"
                                placeholder="you@example.com"
                                value={email}
                                onChange={(event) => setEmail(event.target.value)}
                                required
                            />
                        )}
                        {mode === "register" && (
                            <Input
                                autoComplete="name"
                                placeholder="Display name"
                                value={displayName}
                                onChange={(event) => setDisplayName(event.target.value)}
                                required
                            />
                        )}
                        {(mode === "signin" || mode === "register" || mode === "reset") && (
                            <Input
                                type="password"
                                autoComplete={mode === "signin" ? "current-password" : "new-password"}
                                placeholder="Password"
                                value={password}
                                onChange={(event) => setPassword(event.target.value)}
                                minLength={mode === "signin" ? undefined : 12}
                                required
                            />
                        )}
                        {(mode === "register" || mode === "reset") && (
                            <Input
                                type="password"
                                autoComplete="new-password"
                                placeholder="Confirm password"
                                value={confirmPassword}
                                onChange={(event) => setConfirmPassword(event.target.value)}
                                aria-invalid={passwordMismatch}
                                required
                            />
                        )}
                        <Button className="w-full" type="submit" disabled={busy || passwordMismatch}>
                            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : {
                                signin: "Sign in",
                                register: "Create account",
                                verify: "Verify email",
                                forgot: "Send reset link",
                                reset: "Reset password",
                            }[mode]}
                        </Button>
                    </form>}

                    {mode === "verify" && (
                        <Button
                            variant="ghost"
                            className="w-full"
                            disabled={busy || !email}
                            onClick={() => void auth.resendVerification(email).then(setNotice).catch((reason: unknown) => {
                                setError(reason instanceof Error ? reason.message : "Could not resend email.");
                            })}
                        >
                            Resend verification email
                        </Button>
                    )}
                    {mode === "signin" && (
                        <div className="flex justify-between text-sm">
                            <button className="text-primary hover:underline" onClick={() => changeMode("register")}>Create account</button>
                            <button className="text-primary hover:underline" onClick={() => changeMode("forgot")}>Forgot password?</button>
                        </div>
                    )}

                    {(mode === "signin" || mode === "register") && (
                        <div className="rounded-md border p-3">
                            <button
                                className="flex w-full items-center gap-2 text-sm font-medium"
                                onClick={() => setReferralOpen((open) => !open)}
                                type="button"
                            >
                                <Tag className="h-4 w-4" />
                                Have a referral code?
                                {referralApplied && <Check className="ml-auto h-4 w-4 text-green-600" />}
                            </button>
                            {referralOpen && (
                                <div className="mt-3 flex gap-2">
                                    <Input value={referralCode} onChange={(event) => setReferralCode(event.target.value)} placeholder="Referral code" />
                                    <Button type="button" variant="secondary" onClick={applyReferralCode}>Apply</Button>
                                </div>
                            )}
                        </div>
                    )}
                </CardContent>
                <CardFooter className="justify-center text-xs text-muted-foreground">
                    Review our <Link href="/privacy" className="ml-1 underline">Privacy Policy</Link>.
                </CardFooter>
            </Card>
        </div>
    );
}

export default function LoginPage() {
    return <Suspense fallback={<div className="flex h-full items-center justify-center"><Loader2 className="h-10 w-10 animate-spin" /></div>}><LoginContent /></Suspense>;
}
