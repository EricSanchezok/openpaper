# Scholens authentication

Scholens embeds the shared
[`sanchezcloud-identity`](https://github.com/EricSanchezok/sanchezcloud-identity) Python SDK. It
does not maintain a second user table or login session. Cross-product onboarding, database-role,
upgrade, and troubleshooting rules are canonical in the
[Identity engineering handbook](https://github.com/EricSanchezok/sanchezcloud-identity/blob/main/docs/README.md).

## Identity boundary

- Canonical identities live in `auth.users` and use `BIGINT` IDs.
- Scholens-owned settings live in `scholens.user_profiles` and reference `auth.users.id`.
- Every Scholens user-owned table references `auth.users.id` directly.
- Access and refresh tokens are scoped to the `scholens` client through their
  JWT audience and refresh-token `client_id`.
- Zotero OAuth only connects a library to an authenticated user; it is not a
  login provider.

## HTTP API

The sanchezcloud-identity routers are mounted by the bootstrap composition root:

- `/api/v1/auth/*`: register, verify email, login, refresh, logout, password reset
- `/api/v1/me/profile`: shared identity profile operations
- `/api/v1/me`: shared identity enriched with Scholens profile state

Protected endpoints require `Authorization: Bearer <access-token>`. Scholens
keeps access tokens in browser memory. Refresh tokens are rotated in the
host-only `scholens_refresh` cookie with `HttpOnly`, `SameSite=Strict`, and
`Secure` enabled in production; JavaScript never receives them.

## Required configuration

Identity host settings use the `AUTH_` prefix. Production must provide at least:

```dotenv
AUTH_DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DATABASE
AUTH_JWT_SECRET=replace-with-a-long-random-secret
AUTH_PUBLIC_WEB_URL=https://scholens.example.com
AUTH_ALIYUN_DM_ACCESS_KEY_ID=...
AUTH_ALIYUN_DM_ACCESS_KEY_SECRET=...
AUTH_ALIYUN_DM_ACCOUNT_NAME=...
AUTH_ALIYUN_DM_FROM_ALIAS=Scholens
```

The token audience is fixed to `scholens` in application code and is not an
environment override.

`AUTH_DATABASE_URL` defaults to `DATABASE_URL`, so the synchronous Scholens
ORM and the asynchronous sanchezcloud-identity pool can share one RDS database.

Run sanchezcloud-identity migrations independently before Scholens migrations. Scholens
only checks the installed auth schema version and never carries or executes
sanchezcloud-identity migration files.
