import { delay, http, HttpResponse } from "msw";

const api = "http://localhost:8000/api/v1";
const error = (code: string, status: number, message = code) =>
  HttpResponse.json(
    {
      code,
      message,
      kind: status >= 500 ? "unavailable" : "unauthenticated",
      retryable: status === 429 || status >= 500,
    },
    { status },
  );

export const actor = {
  id: 7,
  email: "eric@scholens.ai",
  email_verified: true,
  is_active: true,
  is_admin: false,
  is_blocked: false,
  status: "active",
  display_name: "Eric",
  locale: "en",
};

export const authHandlers = {
  success: [
    http.post(`${api}/auth/login`, () =>
      HttpResponse.json({
        access_token: "storybook-access",
        token_type: "bearer",
      }),
    ),
    http.post(`${api}/auth/refresh`, () =>
      HttpResponse.json({
        access_token: "storybook-access",
        token_type: "bearer",
      }),
    ),
    http.get(`${api}/me`, () => HttpResponse.json(actor)),
    http.post(`${api}/auth/logout`, () => HttpResponse.json({ message: "ok" })),
  ],
  invalidCredentials: [
    http.post(`${api}/auth/login`, () =>
      error("auth_invalid_credentials", 401),
    ),
  ],
  rateLimited: [
    http.post(`${api}/auth/login`, () =>
      HttpResponse.json(
        {
          code: "auth_rate_limited",
          message: "rate limited",
          kind: "rate_limited",
          retryable: true,
        },
        { status: 429, headers: { "Retry-After": "60" } },
      ),
    ),
  ],
  verificationExpired: [
    http.post(`${api}/auth/verify-email`, () =>
      error("auth_verification_token_invalid", 400),
    ),
  ],
  resetExpired: [
    http.post(`${api}/auth/reset-password`, () =>
      error("auth_reset_token_invalid", 400),
    ),
  ],
  refreshMissing: [
    http.post(`${api}/auth/refresh`, () => error("auth_session_missing", 401)),
  ],
  refreshExpired: [
    http.post(`${api}/auth/refresh`, () => error("auth_session_expired", 401)),
  ],
  refreshReuse: [
    http.post(`${api}/auth/refresh`, () => error("auth_session_expired", 401)),
  ],
  unavailable: [
    http.post(`${api}/auth/refresh`, () =>
      error("auth_service_unavailable", 503),
    ),
  ],
  offline: [http.post(`${api}/auth/refresh`, () => HttpResponse.error())],
  slow: [
    http.post(`${api}/auth/refresh`, async () => {
      await delay(1_800);
      return HttpResponse.json({
        access_token: "storybook-access",
        token_type: "bearer",
      });
    }),
    http.get(`${api}/me`, () => HttpResponse.json(actor)),
  ],
  bootstrapping: [
    http.post(`${api}/auth/refresh`, async () => {
      await delay(300);
      return HttpResponse.json({
        access_token: "storybook-access",
        token_type: "bearer",
      });
    }),
    http.get(`${api}/me`, () => HttpResponse.json(actor)),
  ],
};
