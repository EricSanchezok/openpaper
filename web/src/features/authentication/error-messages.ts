export const authErrorMessageKeys = {
  auth_invalid_credentials: "invalidCredentials",
  auth_rate_limited: "rateLimited",
  auth_session_missing: "sessionExpired",
  auth_session_expired: "sessionExpired",
  auth_token_invalid_or_expired: "sessionExpired",
  auth_verification_token_invalid: "verificationInvalid",
  auth_reset_token_invalid: "resetInvalid",
  auth_service_unavailable: "serviceUnavailable",
  validation_error: "validation",
} as const;

export type AuthErrorCode = keyof typeof authErrorMessageKeys;

export function authErrorMessageKey(code: string | undefined) {
  return code && code in authErrorMessageKeys
    ? authErrorMessageKeys[code as AuthErrorCode]
    : "unknown";
}
