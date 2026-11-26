## 1. Public Contracts and Persistence

- [x] 1.1 Add strict PDF create, retry, summary, detail, attempt, file, and page Pydantic schemas using the established template, input-identity, pagination, and error contracts; verify schema tests reject unknown fields and private storage references.
- [x] 1.2 Add bounded owner/report/version-scoped export keyset queries and verify PostgreSQL tests cover ordering, page boundaries, and cursor scope. The approved one-export-per-version/template invariant limits each list to one row, so a same-version insertion between pages is impossible with the sole supported template.
- [x] 1.3 Harden export creation, claim, finish, failure, and retry repository transitions for immutable bindings and repeated calls; verify PostgreSQL tests cover uniqueness, attempt ordinals, legal states, concurrent claims, and no duplicate version or asset.

## 2. Version-Scoped API and Domain Service

- [x] 2.1 Add an export domain service that authorizes the report and version first, validates the saved template/input identity, and applies scoped create/retry idempotency with transactional state changes; verify service tests cover equivalent and conflicting keys, concurrent clicks, stale retry, and owner-safe absence.
- [x] 2.2 Implement owner-scoped create, list, detail, and retry routes under `/api/v1/reports/{report_id}/versions/{version_id}/pdf-exports`, then wire dependencies and safe response projection; verify API contract and OpenAPI tests for `202`, `200`, `400`, `401`, `404`, `409`, and `422`, replay header, four states, and sensitive-field exclusion.
- [x] 2.3 Keep version summaries and the existing download route aligned with export state; verify API tests show latest export status, authorized completed download, `409 export_not_ready`, and identical missing/foreign `404` behavior.

## 3. Worker, Storage, and Recovery

- [x] 3.1 Add a PDF Celery attempt that claims the persisted ordinal, copies only the selected saved version, renders with the existing PDF adapter, and validates the version/template/input binding before completion; verify deterministic worker tests cover later draft edits and duplicate delivery.
- [x] 3.2 Make generated-PDF uploads attempt scoped while retaining one immutable asset binding on success; verify fake-storage and PostgreSQL tests cover upload/checksum metadata, failed-write compensation, uncertain commit reconciliation, changed bytes on retry, and no downloadable orphan.
- [x] 3.3 Persist sanitized render, snapshot, artifact, timeout, and storage failures without modifying the version; verify worker tests cover each failure code, retryability, no raw exception or customer content, and successful retry against the same version.
- [x] 3.4 Add post-commit publish, bounded queued-attempt reconciliation, and stale-running timeout handling; verify broker failure/recovery and late-completion tests leave PostgreSQL authoritative and produce no conflicting attempt or asset.
- [x] 3.5 Add and document finite PDF task and stale-running settings plus browser/storage worker setup in backend configuration examples and local docs; verify settings tests accept valid bounds and reject inconsistent timeouts.

## 4. Stage Verification

- [x] 4.1 Run focused PDF route, domain, worker, renderer-adapter, storage contract, and isolated PostgreSQL integration tests; verify exact-version content, version preservation on failure, same-export retry, authorization, and idempotency acceptance cases all pass.
- [x] 4.2 Run the backend stage checks and relevant PostgreSQL version/export suite, verify migration upgrade if a schema migration was introduced, and report any environment-limited checks; require `openspec validate gh-20-implement-version-linked-pdf-export-jobs --strict --json` to return valid with no issues.
