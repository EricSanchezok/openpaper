# OpenPaper authentication

OpenPaper uses the shared [`cloud-auth`](https://github.com/EricSanchezok/cloud-auth)
service library. It does not maintain a second user table or login session.

## Identity boundary

- Canonical identities live in `auth.users` and use `BIGINT` IDs.
- OpenPaper-owned settings live in `user_profiles` and reference
  `openpaper.user_profiles` and reference `auth.users.id`.
- Every OpenPaper user-owned table references `auth.users.id` directly.
- Access and refresh tokens are scoped to the `openpaper` client through their
  JWT audience and refresh-token `client_id`.
- Zotero OAuth only connects a library to an authenticated user; it is not a
  login provider.

## HTTP API

The cloud-auth routers are mounted directly by `app.main`:

- `/api/auth/*`: register, verify email, login, refresh, logout, password reset
- `/api/user/*`: shared identity profile operations
- `/api/me`: shared identity enriched with OpenPaper profile state

Protected endpoints require `Authorization: Bearer <access-token>`. OpenPaper
keeps access tokens in browser memory. Refresh tokens are rotated in the
host-only `openpaper_refresh` cookie with `HttpOnly`, `SameSite=Strict`, and
`Secure` enabled in production; JavaScript never receives them.

## Required configuration

Cloud-auth settings use the `AUTH_` prefix. Production must provide at least:

```dotenv
AUTH_DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DATABASE
AUTH_JWT_SECRET=replace-with-a-long-random-secret
AUTH_PUBLIC_WEB_URL=https://openpaper.example.com
AUTH_ALIYUN_DM_ACCESS_KEY_ID=...
AUTH_ALIYUN_DM_ACCESS_KEY_SECRET=...
AUTH_ALIYUN_DM_ACCOUNT_NAME=...
AUTH_ALIYUN_DM_FROM_ALIAS=OpenPaper
```

The token audience is fixed to `openpaper` in application code and is not an
environment override.

`AUTH_DATABASE_URL` defaults to `DATABASE_URL`, so the synchronous OpenPaper
ORM and the asynchronous cloud-auth pool can share one RDS database.

Run cloud-auth migrations independently before OpenPaper migrations. OpenPaper
only checks the installed auth schema version and never carries or executes
cloud-auth migration files.
