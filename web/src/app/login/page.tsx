import {
  AuthenticationPage,
  firstQueryValue,
  parseAuthenticationMode,
  validatedReturnTo,
} from "@/features/authentication";

type LoginSearchParams = Promise<Record<string, string | string[] | undefined>>;

export default async function LoginPage({
  searchParams,
}: {
  searchParams: LoginSearchParams;
}) {
  const query = await searchParams;
  const mode = parseAuthenticationMode(firstQueryValue(query.mode));
  const returnTo = validatedReturnTo(firstQueryValue(query.returnTo));
  const token =
    mode === "verify" || mode === "reset"
      ? firstQueryValue(query.token)
      : undefined;

  return <AuthenticationPage mode={mode} returnTo={returnTo} token={token} />;
}
