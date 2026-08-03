"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowLeft } from "iconoir-react";
import type { Route } from "next";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/display";
import {
  Field,
  FieldControl,
  FieldLabel,
  FieldMessage,
} from "@/components/ui/field";
import { Input, PasswordInput } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { Icon } from "@/design-system/icons/icon";
import { ApiError, publicApiClient } from "@/lib/api";
import {
  AuthenticationHeader,
  AuthenticationPanel,
  AuthenticationResult,
  AuthenticationShell,
} from "./authentication-components";
import {
  type AuthenticationMode,
  authenticationHref,
} from "./authentication-mode";
import { useAuthSession } from "./auth-session";
import { authErrorMessageKey } from "./error-messages";
import { createAuthSchemas } from "./schemas";

const pendingVerificationEmailKey = "scholens.pending-verification-email";
const verificationFlights = new Map<string, Promise<void>>();

function appRoute(value: string | undefined): Route {
  return (value ?? "/") as Route;
}

function stripActionToken() {
  const url = new URL(window.location.href);
  url.searchParams.delete("token");
  window.history.replaceState(window.history.state, "", url);
}

async function verifyEmailOnce(token: string) {
  const existing = verificationFlights.get(token);
  if (existing) return existing;
  const request = publicApiClient
    .POST("/api/v1/auth/verify-email", { body: { token } })
    .then(() => undefined);
  verificationFlights.set(token, request);
  return request;
}

export function resetVerificationFlightsForTests() {
  verificationFlights.clear();
}

function useAuthenticationSchemas() {
  const t = useTranslations("Authentication.validation");
  return React.useMemo(
    () =>
      createAuthSchemas({
        email: t("email"),
        passwordRequired: t("passwordRequired"),
        passwordMinimum: t("passwordMinimum"),
        passwordMismatch: t("passwordMismatch"),
        tokenRequired: t("tokenRequired"),
      }),
    [t],
  );
}

function AuthenticationProblem({ error }: { error: unknown }) {
  const t = useTranslations("Authentication.errors");
  const apiError = error instanceof ApiError ? error : undefined;
  const key = authErrorMessageKey(apiError?.code);
  const message =
    apiError?.code === "auth_rate_limited" && apiError.retryAfterSeconds != null
      ? t("rateLimitedSeconds", { seconds: apiError.retryAfterSeconds })
      : t(key);
  return (
    <Alert tone="danger">
      <AlertDescription>{message}</AlertDescription>
      {apiError?.correlationId ? (
        <p className="font-mono text-xs opacity-80">
          {t("correlation", { id: apiError.correlationId })}
        </p>
      ) : null}
    </Alert>
  );
}

function SessionUnavailable() {
  const session = useAuthSession();
  const t = useTranslations("Authentication.service");
  if (session.status !== "unavailable") return null;
  return (
    <Alert tone="danger">
      <AlertTitle>{t("title")}</AlertTitle>
      <AlertDescription>{t("description")}</AlertDescription>
      <Button
        className="mt-2 w-full sm:w-auto"
        onClick={() => void session.retryBootstrap()}
        variant="secondary"
      >
        {t("retry")}
      </Button>
    </Alert>
  );
}

function BackToSignIn({ returnTo }: { returnTo?: string }) {
  const t = useTranslations("Authentication.navigation");
  return (
    <Link
      className="text-secondary hover:text-foreground inline-flex min-h-11 items-center gap-2 text-sm font-medium"
      href={authenticationHref({ mode: "sign-in", returnTo })}
    >
      <Icon glyph={ArrowLeft} size={20} tone="secondary" />
      {t("backToSignIn")}
    </Link>
  );
}

function AuthenticationSkeleton() {
  const t = useTranslations("Authentication.session");
  return (
    <AuthenticationShell stateLabel={t("bootstrapping")}>
      <AuthenticationPanel>
        <div
          aria-label={t("bootstrapping")}
          className="grid gap-3"
          role="status"
        >
          <Skeleton className="h-9 w-52" />
          <Skeleton className="h-5 w-full" />
        </div>
        <div className="grid gap-4">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-11 w-full" />
        </div>
      </AuthenticationPanel>
    </AuthenticationShell>
  );
}

function SignInForm({ returnTo }: { returnTo?: string }) {
  const t = useTranslations("Authentication");
  const schemas = useAuthenticationSchemas();
  const session = useAuthSession();
  const router = useRouter();
  const [problem, setProblem] = React.useState<unknown>();
  const form = useForm<z.input<typeof schemas.signIn>>({
    resolver: zodResolver(schemas.signIn),
    defaultValues: { email: "", password: "" },
  });
  const submit = form.handleSubmit(async (values) => {
    setProblem(undefined);
    try {
      await session.signIn(values);
      router.replace(appRoute(returnTo));
    } catch (error) {
      setProblem(error);
    }
  });

  return (
    <AuthenticationPanel>
      <AuthenticationHeader
        description={t("signIn.description")}
        title={t("signIn.title")}
      />
      <SessionUnavailable />
      {problem ? <AuthenticationProblem error={problem} /> : null}
      <form className="grid gap-4" noValidate onSubmit={submit}>
        <Field invalid={Boolean(form.formState.errors.email)}>
          <FieldLabel>{t("fields.email")}</FieldLabel>
          <FieldControl>
            <Input
              autoComplete="email"
              inputMode="email"
              placeholder={t("fields.emailPlaceholder")}
              {...form.register("email")}
            />
          </FieldControl>
          <FieldMessage>{form.formState.errors.email?.message}</FieldMessage>
        </Field>
        <Field invalid={Boolean(form.formState.errors.password)}>
          <FieldLabel>{t("fields.password")}</FieldLabel>
          <FieldControl>
            <PasswordInput
              autoComplete="current-password"
              hidePasswordLabel={t("a11y.hidePassword")}
              placeholder={t("fields.passwordPlaceholder")}
              showPasswordLabel={t("a11y.showPassword")}
              {...form.register("password")}
            />
          </FieldControl>
          <FieldMessage>{form.formState.errors.password?.message}</FieldMessage>
        </Field>
        <Button
          className="w-full"
          loading={form.formState.isSubmitting}
          type="submit"
        >
          {form.formState.isSubmitting
            ? t("signIn.submitting")
            : t("signIn.submit")}
        </Button>
      </form>
      <nav className="flex items-center justify-between gap-4 text-sm">
        <Link
          className="hover:text-foreground text-secondary min-h-11 py-3"
          href={authenticationHref({ mode: "register", returnTo })}
        >
          {t("navigation.createAccount")}
        </Link>
        <Link
          className="hover:text-foreground text-secondary min-h-11 py-3 text-right"
          href={authenticationHref({ mode: "forgot", returnTo })}
        >
          {t("navigation.forgotPassword")}
        </Link>
      </nav>
    </AuthenticationPanel>
  );
}

function RegisterFlow({ returnTo }: { returnTo?: string }) {
  const t = useTranslations("Authentication");
  const schemas = useAuthenticationSchemas();
  const toast = useToast();
  const [email, setEmail] = React.useState<string | null>(null);
  const [problem, setProblem] = React.useState<unknown>();
  const [resending, setResending] = React.useState(false);
  React.useEffect(() => {
    let active = true;
    queueMicrotask(() => {
      if (active) {
        setEmail(window.sessionStorage.getItem(pendingVerificationEmailKey));
      }
    });
    return () => {
      active = false;
    };
  }, []);
  const form = useForm<
    z.input<typeof schemas.register>,
    unknown,
    z.output<typeof schemas.register>
  >({
    resolver: zodResolver(schemas.register),
    defaultValues: {
      displayName: "",
      email: "",
      password: "",
      confirmPassword: "",
    },
  });
  const submit = form.handleSubmit(async (values) => {
    setProblem(undefined);
    try {
      await publicApiClient.POST("/api/v1/auth/register", { body: values });
      window.sessionStorage.setItem(pendingVerificationEmailKey, values.email);
      setEmail(values.email);
    } catch (error) {
      setProblem(error);
    }
  });
  const resend = async () => {
    if (!email || resending) return;
    setResending(true);
    setProblem(undefined);
    try {
      await publicApiClient.POST("/api/v1/auth/resend-verification", {
        body: { email },
      });
      toast.notify({ title: t("checkInbox.resent") });
    } catch (error) {
      setProblem(error);
    } finally {
      setResending(false);
    }
  };

  if (email) {
    return (
      <AuthenticationPanel>
        <BackToSignIn returnTo={returnTo} />
        <AuthenticationHeader
          description={t("checkInbox.registerDescription", { email })}
          title={t("checkInbox.title")}
        />
        {problem ? <AuthenticationProblem error={problem} /> : null}
        <AuthenticationResult
          description={t("checkInbox.verificationNote")}
          title={t("checkInbox.title")}
          tone="mail"
        >
          <Button
            className="w-full"
            loading={resending}
            onClick={() => void resend()}
            variant="secondary"
          >
            {resending ? t("checkInbox.resending") : t("checkInbox.resend")}
          </Button>
        </AuthenticationResult>
      </AuthenticationPanel>
    );
  }

  return (
    <AuthenticationPanel>
      <AuthenticationHeader
        description={t("register.description")}
        title={t("register.title")}
      />
      <SessionUnavailable />
      {problem ? <AuthenticationProblem error={problem} /> : null}
      <form className="grid gap-4" noValidate onSubmit={submit}>
        <Field invalid={Boolean(form.formState.errors.displayName)}>
          <FieldLabel>{t("fields.displayName")}</FieldLabel>
          <FieldControl>
            <Input
              autoComplete="name"
              placeholder={t("fields.displayNamePlaceholder")}
              {...form.register("displayName")}
            />
          </FieldControl>
          <FieldMessage>
            {form.formState.errors.displayName?.message}
          </FieldMessage>
        </Field>
        <Field invalid={Boolean(form.formState.errors.email)}>
          <FieldLabel>{t("fields.email")}</FieldLabel>
          <FieldControl>
            <Input
              autoComplete="email"
              inputMode="email"
              placeholder={t("fields.emailPlaceholder")}
              {...form.register("email")}
            />
          </FieldControl>
          <FieldMessage>{form.formState.errors.email?.message}</FieldMessage>
        </Field>
        <Field invalid={Boolean(form.formState.errors.password)}>
          <FieldLabel>{t("fields.password")}</FieldLabel>
          <FieldControl>
            <PasswordInput
              autoComplete="new-password"
              hidePasswordLabel={t("a11y.hidePassword")}
              placeholder={t("fields.passwordMinimum")}
              showPasswordLabel={t("a11y.showPassword")}
              {...form.register("password")}
            />
          </FieldControl>
          <FieldMessage>{form.formState.errors.password?.message}</FieldMessage>
        </Field>
        <Field invalid={Boolean(form.formState.errors.confirmPassword)}>
          <FieldLabel>{t("fields.confirmPassword")}</FieldLabel>
          <FieldControl>
            <PasswordInput
              autoComplete="new-password"
              hidePasswordLabel={t("a11y.hidePassword")}
              placeholder={t("fields.confirmPassword")}
              showPasswordLabel={t("a11y.showPassword")}
              {...form.register("confirmPassword")}
            />
          </FieldControl>
          <FieldMessage>
            {form.formState.errors.confirmPassword?.message}
          </FieldMessage>
        </Field>
        <Button
          className="w-full"
          loading={form.formState.isSubmitting}
          type="submit"
        >
          {form.formState.isSubmitting
            ? t("register.submitting")
            : t("register.submit")}
        </Button>
      </form>
      <Link
        className="text-secondary hover:text-foreground min-h-11 py-3 text-center text-sm"
        href={authenticationHref({ mode: "sign-in", returnTo })}
      >
        {t("navigation.alreadyHaveAccount")}
      </Link>
    </AuthenticationPanel>
  );
}

function ForgotFlow({ returnTo }: { returnTo?: string }) {
  const t = useTranslations("Authentication");
  const schemas = useAuthenticationSchemas();
  const [sentTo, setSentTo] = React.useState<string>();
  const [problem, setProblem] = React.useState<unknown>();
  const form = useForm<z.input<typeof schemas.forgotPassword>>({
    resolver: zodResolver(schemas.forgotPassword),
    defaultValues: { email: "" },
  });
  const submit = form.handleSubmit(async (values) => {
    setProblem(undefined);
    try {
      await publicApiClient.POST("/api/v1/auth/forgot-password", {
        body: values,
      });
      setSentTo(values.email);
    } catch (error) {
      setProblem(error);
    }
  });
  if (sentTo) {
    return (
      <AuthenticationPanel>
        <BackToSignIn returnTo={returnTo} />
        <AuthenticationHeader
          description={t("checkInbox.forgotDescription", { email: sentTo })}
          title={t("checkInbox.title")}
        />
        <AuthenticationResult
          description={t("checkInbox.resetNote")}
          title={t("checkInbox.title")}
          tone="mail"
        >
          <Button asChild className="w-full" variant="secondary">
            <Link href={authenticationHref({ mode: "sign-in", returnTo })}>
              {t("navigation.backToSignIn")}
            </Link>
          </Button>
        </AuthenticationResult>
      </AuthenticationPanel>
    );
  }
  return (
    <AuthenticationPanel>
      <BackToSignIn returnTo={returnTo} />
      <AuthenticationHeader
        description={t("forgot.description")}
        title={t("forgot.title")}
      />
      <SessionUnavailable />
      {problem ? <AuthenticationProblem error={problem} /> : null}
      <form className="grid gap-4" noValidate onSubmit={submit}>
        <Field invalid={Boolean(form.formState.errors.email)}>
          <FieldLabel>{t("fields.email")}</FieldLabel>
          <FieldControl>
            <Input
              autoComplete="email"
              inputMode="email"
              placeholder={t("fields.emailPlaceholder")}
              {...form.register("email")}
            />
          </FieldControl>
          <FieldMessage>{form.formState.errors.email?.message}</FieldMessage>
        </Field>
        <Button
          className="w-full"
          loading={form.formState.isSubmitting}
          type="submit"
        >
          {form.formState.isSubmitting
            ? t("forgot.submitting")
            : t("forgot.submit")}
        </Button>
      </form>
    </AuthenticationPanel>
  );
}

function VerifyFlow({
  token,
  returnTo,
}: {
  token?: string;
  returnTo?: string;
}) {
  const t = useTranslations("Authentication");
  const [state, setState] = React.useState<"loading" | "success" | "invalid">(
    token ? "loading" : "invalid",
  );
  React.useEffect(() => {
    if (!token) return;
    let active = true;
    void verifyEmailOnce(token)
      .then(() => {
        if (!active) return;
        stripActionToken();
        window.sessionStorage.removeItem(pendingVerificationEmailKey);
        setState("success");
      })
      .catch(() => {
        if (active) setState("invalid");
      });
    return () => {
      active = false;
    };
  }, [token]);
  if (state === "loading") {
    return (
      <AuthenticationPanel>
        <AuthenticationHeader
          description={t("verify.loadingDescription")}
          title={t("verify.loadingTitle")}
        />
        <div aria-live="polite" className="grid gap-3">
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-11 w-full" />
        </div>
      </AuthenticationPanel>
    );
  }
  if (state === "success") {
    return (
      <AuthenticationPanel>
        <AuthenticationHeader
          description={t("verify.successDescription")}
          title={t("verify.successTitle")}
        />
        <AuthenticationResult
          description={t("verify.successDescription")}
          title={t("verify.successTitle")}
        >
          <Button asChild className="w-full">
            <Link href={appRoute(returnTo)}>{t("verify.continue")}</Link>
          </Button>
        </AuthenticationResult>
      </AuthenticationPanel>
    );
  }
  return (
    <AuthenticationPanel>
      <AuthenticationHeader
        description={t("verify.invalidDescription")}
        title={t("verify.invalidTitle")}
      />
      <AuthenticationResult
        description={t("errors.verificationInvalid")}
        title={t("verify.invalidTitle")}
        tone="danger"
      >
        <Button asChild className="w-full">
          <Link href={authenticationHref({ mode: "sign-in", returnTo })}>
            {t("navigation.backToSignIn")}
          </Link>
        </Button>
      </AuthenticationResult>
    </AuthenticationPanel>
  );
}

function ResetFlow({ token, returnTo }: { token?: string; returnTo?: string }) {
  const t = useTranslations("Authentication");
  const schemas = useAuthenticationSchemas();
  const [success, setSuccess] = React.useState(false);
  const [problem, setProblem] = React.useState<unknown>();
  const form = useForm<
    z.input<typeof schemas.resetPassword>,
    unknown,
    z.output<typeof schemas.resetPassword>
  >({
    resolver: zodResolver(schemas.resetPassword),
    defaultValues: { token: token ?? "", newPassword: "", confirmPassword: "" },
  });
  const submit = form.handleSubmit(async (values) => {
    setProblem(undefined);
    try {
      await publicApiClient.POST("/api/v1/auth/reset-password", {
        body: values,
      });
      stripActionToken();
      setSuccess(true);
    } catch (error) {
      setProblem(error);
    }
  });
  if (!token) {
    return (
      <AuthenticationPanel>
        <AuthenticationHeader
          description={t("reset.invalidDescription")}
          title={t("reset.invalidTitle")}
        />
        <AuthenticationResult
          description={t("errors.resetInvalid")}
          title={t("reset.invalidTitle")}
          tone="danger"
        >
          <Button asChild className="w-full">
            <Link href={authenticationHref({ mode: "forgot", returnTo })}>
              {t("reset.requestNew")}
            </Link>
          </Button>
        </AuthenticationResult>
      </AuthenticationPanel>
    );
  }
  if (success) {
    return (
      <AuthenticationPanel>
        <AuthenticationHeader
          description={t("reset.successDescription")}
          title={t("reset.successTitle")}
        />
        <AuthenticationResult
          description={t("reset.successDescription")}
          title={t("reset.successTitle")}
        >
          <Button asChild className="w-full">
            <Link href={authenticationHref({ mode: "sign-in", returnTo })}>
              {t("signIn.submit")}
            </Link>
          </Button>
        </AuthenticationResult>
      </AuthenticationPanel>
    );
  }
  return (
    <AuthenticationPanel>
      <BackToSignIn returnTo={returnTo} />
      <AuthenticationHeader
        description={t("reset.description")}
        title={t("reset.title")}
      />
      {problem ? <AuthenticationProblem error={problem} /> : null}
      <form className="grid gap-4" noValidate onSubmit={submit}>
        <input type="hidden" {...form.register("token")} />
        <Field invalid={Boolean(form.formState.errors.newPassword)}>
          <FieldLabel>{t("fields.newPassword")}</FieldLabel>
          <FieldControl>
            <PasswordInput
              autoComplete="new-password"
              hidePasswordLabel={t("a11y.hidePassword")}
              placeholder={t("fields.passwordMinimum")}
              showPasswordLabel={t("a11y.showPassword")}
              {...form.register("newPassword")}
            />
          </FieldControl>
          <FieldMessage>
            {form.formState.errors.newPassword?.message}
          </FieldMessage>
        </Field>
        <Field invalid={Boolean(form.formState.errors.confirmPassword)}>
          <FieldLabel>{t("fields.confirmPassword")}</FieldLabel>
          <FieldControl>
            <PasswordInput
              autoComplete="new-password"
              hidePasswordLabel={t("a11y.hidePassword")}
              placeholder={t("fields.confirmPassword")}
              showPasswordLabel={t("a11y.showPassword")}
              {...form.register("confirmPassword")}
            />
          </FieldControl>
          <FieldMessage>
            {form.formState.errors.confirmPassword?.message}
          </FieldMessage>
        </Field>
        <Button
          className="w-full"
          loading={form.formState.isSubmitting}
          type="submit"
        >
          {form.formState.isSubmitting
            ? t("reset.submitting")
            : t("reset.submit")}
        </Button>
      </form>
    </AuthenticationPanel>
  );
}

export function AuthenticationPage({
  mode,
  returnTo,
  token,
}: {
  mode: AuthenticationMode;
  returnTo?: string;
  token?: string;
}) {
  const session = useAuthSession();
  const router = useRouter();
  const t = useTranslations("Authentication");
  const actionMode = mode === "verify" || mode === "reset";
  React.useEffect(() => {
    if (!actionMode && session.status === "authenticated") {
      router.replace(appRoute(returnTo));
    }
  }, [actionMode, returnTo, router, session.status]);

  if (!actionMode && session.status === "bootstrapping") {
    return <AuthenticationSkeleton />;
  }
  if (!actionMode && session.status === "authenticated") {
    return <AuthenticationSkeleton />;
  }

  const stateLabel =
    mode === "sign-in"
      ? t("signIn.state")
      : mode === "register"
        ? t("register.state")
        : mode === "forgot"
          ? t("forgot.state")
          : mode === "verify"
            ? t("verify.state")
            : t("reset.state");

  return (
    <AuthenticationShell stateLabel={stateLabel}>
      {mode === "sign-in" ? <SignInForm returnTo={returnTo} /> : null}
      {mode === "register" ? <RegisterFlow returnTo={returnTo} /> : null}
      {mode === "forgot" ? <ForgotFlow returnTo={returnTo} /> : null}
      {mode === "verify" ? (
        <VerifyFlow returnTo={returnTo} token={token} />
      ) : null}
      {mode === "reset" ? (
        <ResetFlow returnTo={returnTo} token={token} />
      ) : null}
    </AuthenticationShell>
  );
}
