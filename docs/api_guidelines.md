# Command Center API Guidelines

These conventions keep UI integrations, automation scripts, and operator tools aligned as the control surface continues to evolve. Apply them to new endpoints and retrofit existing handlers as time allows.

## Resource Naming & URI Shapes
- Prefer plural nouns for collections (e.g. `/strategies`, `/orders`) and nested resources for scoped data (`/strategies/{id}/positions`).
- Keep HTTP verbs aligned with semantics:
  - `GET` for retrieval, returning JSON documents.
  - `POST` for create/trigger operations that generate side effects.
  - `PUT` / `PATCH` for idempotent updates (favour `PATCH` for partial mutations).
  - `DELETE` for removals; if soft deletes are required, expose `PATCH ... { "status": "disabled" }`.
- Avoid mixing control verbs into resource paths (e.g. move `/ops/kill-switch` under `/controls/kill-switch` or expose `/controls` collection with action enum). When verbs are unavoidable, suffix with `/actions/{action}` to keep naming consistent.

## Versioning & Deprecation
- Introduce a path-based version namespace (`/api/v1`) for stable contracts. Reserve `/api/internal` for experimental endpoints.
- Advertise supported versions through the `X-API-Versions` response header and accept an optional `X-API-Version` request header for forward compatibility.
- Mark deprecated operations in OpenAPI with `deprecated: true` and emit the `Sunset` header indicating the retirement date. Publish removals in `docs/CHANGELOG.md` at least 30 days in advance.

## Error Model
- Standardise all error payloads on:
  ```json
  {
    "error": {
      "code": "string.machine_code",
      "message": "Human readable summary",
      "details": {...optional context...},
      "requestId": "trace-id"
    }
  }
  ```
- Mask internal exceptions; translate FastAPI/HTTPException detail strings into structured codes (e.g. `auth.invalid_token`, `idempotency.missing_header`).
- Include `requestId` pulled from trace context or `X-Request-ID`. Ensure every handler logs the code and requestId for auditability.

## Idempotent Mutations
- Require the `Idempotency-Key` header for all POST/PUT/PATCH/DELETE handlers that mutate system state. Leverage `IdempotentGuard` or equivalent helpers.
- For legacy endpoints that cannot easily become idempotent (e.g. streaming cancels), document the behaviour in OpenAPI and add replay-safe wrappers before exposing externally.
- Validate key freshness (e.g. reject replays older than 24h) once Redis/DB-backed stores replace the current in-memory cache.

## Pagination, Filtering & Sorting
- Adopt cursor-based pagination for large collections. Standard query parameters:
  - `cursor` (opaque string returned from previous page).
  - `limit` (default 50, max 500).
  - `sort` (comma-separated fields, prefix `-` for desc).
- Expose filtering via `filter[<field>]=value` syntax to allow multiple filters. Document allowed fields per endpoint.
- Include paging metadata in responses:
  ```json
  {
    "data": [...],
    "page": {
      "nextCursor": "opaque",
      "prevCursor": null,
      "limit": 50,
      "totalHint": null
    }
  }
  ```
- For endpoints that remain unpaginated (e.g. strategy cards or fixed-cardinality aggregates under `/aggregate/*`), enforce hard caps and note the reasoning in OpenAPI descriptions.

## Consistent Metadata
- Return `createdAt`, `updatedAt`, and `id` fields consistently on resources that represent persisted entities (strategies, jobs, alerts).
- Include `audit` objects on control responses summarising actor, idempotency key, and result references.

## Change Management Checklist
1. Update `docs/command_center_openapi.yaml` alongside any FastAPI change, ensuring schemas mirror runtime responses.
2. Expand automated tests in `tests/ui/test_command_center_api.py` (or new suites) to cover version negotiation, pagination cursors, and error shapes.
3. Record breaking changes in `docs/CHANGELOG.md` with migration guidance for operators.
