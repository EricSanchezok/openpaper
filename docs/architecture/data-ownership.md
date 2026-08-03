# SanchezCloud identity and Scholens data ownership

The canonical cross-product identity rules live in the
[SanchezCloud Identity engineering handbook](https://github.com/EricSanchezok/sanchezcloud-identity/blob/main/docs/README.md).
This document defines the Scholens-specific database and deployment contract.

## Storage ownership

| Owner | Responsibilities | PostgreSQL ownership | Explicitly excluded |
| --- | --- | --- | --- |
| `sanchezcloud-identity` | Email identity, passwords, verification, global account status, lockout, public Account ID, shared avatar references, connected clients, security events, audience tokens, and refresh families | `auth.users`, `auth.refresh_tokens`, `auth.user_clients`, `auth.user_avatars`, `auth.security_events`, `auth.schema_migrations` | Product roles, blocks, subscriptions, quotas, usage, documents, projects |
| Scholens | Documents, projects, collaboration, product profile/admin/block state, subscriptions, connectors, and usage | `scholens.*` including `scholens.schema_migrations` | Identity migrations, Scholight state, and Scholight Zilliz collections |

Both schemas share the `sanchezcloud` database but have independent owners and migration
ledgers. `public` contains no application tables. Scholens rows may reference the internal
`auth.users.id`; they must not use a public Account ID as a relational key or write another
product schema.

## Identity integration

- `client_id=scholens`, the JWT secret, audience, and `scholens_refresh` cookie are stable and
  unique to Scholens.
- Access tokens stay in browser memory. Production refresh cookies are host-only, `Secure`,
  `HttpOnly`, and `SameSite=Strict`.
- Identity managers own password, token, and refresh-session behavior. Scholens must not query
  or mutate `auth.refresh_tokens` directly.
- Product profiles, roles, administrators, blocks, subscriptions, quota, and usage remain in
  `scholens.*`.

## Database roles and migration order

- `auth_migrator` owns only `auth` and is used by the protected Identity workflow.
- `scholens_migrator` owns only `scholens`, reads the Identity schema ledger, and may reference
  `auth.users` during product migrations.
- `scholens_app` owns nothing. It receives minimum Identity core DML, the existing append-only
  security-event capability, and Scholens runtime DML. It cannot write migration ledgers, execute
  DDL, alter another schema, or update/delete operation-journal entries.

`deploy/production/bootstrap-db.sql` is the reviewed grant contract. It does not create login
roles or persist credentials. The required order is:

1. infrastructure creates roles and runs the bootstrap to create owned schemas;
2. the protected Identity workflow migrates `auth.*` as `auth_migrator`;
3. the database owner reapplies grants;
4. Scholens validates the Identity version and migrates `scholens.*` as `scholens_migrator`;
5. the database owner reapplies runtime grants;
6. CI audits `scholens_app` with the Identity `product-runtime` profile and separately verifies
   Scholens DML, append-only journal behavior, and cross-schema denials.

A Scholens deployment never bundles or executes Identity migrations. Candidate Identity failures
remain advisory until Scholens is declared production-ready in the consumer registry.
