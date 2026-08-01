# SanchezCloud data ownership

Scholens shares one PostgreSQL database named `sanchezcloud` with the other
SanchezCloud products. Schema ownership, not database separation, defines the
service boundary:

| Repository | Owns | Must not own |
| --- | --- | --- |
| `sanchezcloud-identity` | `auth.users`, `auth.refresh_tokens`, `auth.schema_migrations`; shared identity, credentials, global account security, product-scoped sessions | subscriptions, quotas, usage, product roles or product blocks |
| `scholight` | `scholight.*`; search product state, quota, usage, keys and history; its arXiv/Zilliz search pipeline | auth migrations or Scholens data |
| `scholens` | `scholens.*`; documents, projects, product profile/admin/block state, subscriptions and product usage | auth migrations or Scholight data |

`public` contains no application tables. Product rows may reference
`auth.users(id)`, but products do not write another product schema.

Each schema has a distinct owner role (`auth_migrator`,
`scholight_migrator`, or `scholens_migrator`). Runtime roles receive only the
DML needed by their product. Migrators do not receive database-level `CREATE`,
cannot perform DDL in another schema, and keep independent migration ledgers.

Scholens validates the installed `auth.schema_migrations` version before
running its single clean baseline. It never bundles or executes sanchezcloud-identity
migrations.

## Adding another product

For a product named `example`:

1. Assign a stable `client_id="example"`, an independent JWT secret, and an
   `example_refresh` HttpOnly cookie.
2. Pre-provision `example`, `example_migrator`, and `example_app`; grant no
   database-level `CREATE`.
3. Keep all product profiles, roles, blocks, plans, quota and usage in
   `example.*`, linked to `auth.users(id)`.
4. Give the product an independent migration ledger and require a compatible
   auth ledger before migration.
5. Use sanchezcloud-identity's `UserManager` session API and never query
   `auth.refresh_tokens` directly.
6. Test from an empty PostgreSQL database that ownership, cross-schema denial,
   runtime DML, and an empty `public` schema all hold.

Scholens does not use or administer Scholight's Zilliz collections.
