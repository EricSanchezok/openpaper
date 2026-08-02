# API and Server-State Development

## Contract pipeline

The frontend consumes a deterministic public contract:

```text
FastAPI app.openapi()
  -> filter /api/v1 routes
  -> server/openapi/public-v1.json
  -> openapi-typescript
  -> src/lib/api/generated/schema.d.ts
  -> openapi-fetch transport
  -> feature query options and mutations
```

`server/openapi/v1-contract.json` remains a route/method architecture audit. It
does not replace the full public schema used by the frontend.

## Coordinated backend change

When a public request or response changes:

1. Update the FastAPI route and Pydantic schema.
2. From `server/`, run:

   ```bash
   uv run python -m app.scripts.export_public_openapi
   uv run pytest tests/test_public_openapi_snapshot.py
   ```

3. From `web/`, run:

   ```bash
   pnpm api:generate
   pnpm api:check
   pnpm typecheck
   ```

4. Update feature adapters, MSW fixtures, stories, and tests in the same change.
5. Review the OpenAPI JSON diff for accidental internal routes or broad schema
   changes.

The snapshot and generated type file are committed. A frontend build never
requires a running backend.

## Transport boundary

`src/lib/api/client.ts` is the single low-level browser transport. It owns:

- API base URL.
- `credentials: "include"`.
- Optional access-token injection.
- Unauthorized callback.
- Standardized `ApiError` conversion.
- Correlation/request ID extraction.
- Native abort-signal support through `openapi-fetch`.

Do not create feature-specific Axios/fetch clients, retry interceptors, or auth
refresh loops. Add cross-cutting transport behavior once at this boundary and
test it independently.

## Feature API layer

Feature code wraps typed transport calls in query options or mutations. It may
map wire data to a deliberate display model, but must not redefine backend DTOs.

Recommended conventions:

```text
features/<feature>/api/
├── keys.ts       # hierarchical Query key factory
├── queries.ts    # queryOptions and response adapters
├── mutations.ts  # mutation options and explicit invalidation
└── fixtures.ts   # deterministic story/test data when feature-owned
```

Query keys begin with the feature domain and include every input that changes
the response. Paginated and filtered views use stable serializable parameters.
Mutation success invalidates or updates the narrowest affected keys.

Pass TanStack Query's abort signal to the generated request. Do not implement a
second cache in Context or local state.

## Errors and feedback

- Transport failures become `ApiError` with status, optional code, request ID,
  and original details.
- A feature translates stable error codes into domain copy and recovery actions.
- Unknown and 5xx errors use a safe generic message while retaining request ID
  for support and observability.
- 401 invokes the shared unauthorized path; individual components do not invent
  login redirects.
- Network state is represented with the shared Async Feedback patterns, while
  domain wording and actions remain feature-owned.
- Retrying is visible. Mutations are not retried automatically unless the
  operation is proven idempotent.

## Compatibility policy

The replacement frontend follows the current public v1 schema while the backend
is being improved. Do not add a frontend compatibility layer for legacy DTOs.
When a coordinated breaking change is intentional, update the schema snapshot,
generated types, affected feature code, mocks, and tests together.
