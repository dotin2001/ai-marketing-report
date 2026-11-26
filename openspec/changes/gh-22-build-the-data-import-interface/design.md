## Context

See `proposal.md` for motivation and `specs/data-import-interface/spec.md` for observable behavior. The frontend already has `/` report cards, `/reports/new`, a same-origin `/api/v1` rewrite, `frontend/lib/reports-api.ts` for safe JSON errors, and Vitest component tests. Report cards currently have no detail link, and the frontend report parser does not retain the backend's `current_source_id`. The backend already accepts one multipart CSV `file` or exact pasted `content`, requires `Idempotency-Key`, and exposes owner-authorized source detail and bounded preview. Default intake limits are 10 MiB for CSV, 1 MiB for pasted UTF-8 content, and 100,000 CSV records; backend limits are configurable. The backend's default principal dependency returns `401` until an authenticated integration or test override is configured.

## Goals / Non-Goals

**Goals:**

- Add a focused source-entry route that composes the existing API contracts and keeps report ownership enforced by the backend.
- Make byte progress, server acceptance, and preview retrieval separate states, with stable retry identity and preserved input.
- Extend the existing typed API boundary without duplicating error parsing or exposing untrusted content unsafely.

**Non-Goals:**

- Implement mapping, normalization, validation, warning acknowledgement, confirmation, metrics, analysis, or a new backend authentication provider.
- Parse pasted table cells on the client or treat preview rows as a canonical dataset.

## Decisions

### Route and current-source recovery

Add `/reports/[reportId]/import` with an App Router page shell and a small Client Component for interaction. Link each report card to this route. Extend the typed report detail response to retain `current_source_id`; load the report first, then load its current source detail and preview when present. After an accepted attachment, update from the returned source and fetch its preview. Re-fetch report detail when recovering from an uncertain response if needed, but do not infer that a changed `current_source_id` proves this particular command succeeded; only a successful attachment or idempotent replay does. A generic report detail page would mix in later workflow stages before their UI exists.

### Centralized API and upload transport

Keep JSON report and pasted-text requests on the existing same-origin `fetch` boundary. Add typed source detail/preview parsers and a shared safe error normalizer in `frontend/lib/`. Use `XMLHttpRequest` only for multipart CSV submission because its `upload` progress event exposes bytes sent; `fetch` does not provide portable browser upload progress. Point it at the same-origin `/api/v1` path, send browser credentials and `Idempotency-Key`, parse the same `{ data }` or safe `{ error }` envelopes, and never set the multipart `Content-Type` manually. The upload event's 100% means transfer completion, not server acceptance; switch to a processing state until the 201 response arrives. If `lengthComputable` is false, show indeterminate progress. Avoid a second all-XHR API stack by sharing parsers and error mapping with the existing boundary.

### Limits and selected-input handling

Add validated public frontend configuration for the displayed CSV and text byte caps, defaulting to the backend's documented 10 MiB and 1 MiB. Deployment documentation must require them to match the backend's effective `SOURCE_CSV_MAX_BYTES` and `SOURCE_TEXT_MAX_BYTES`; the backend remains authoritative and its `413` response wins if configuration drifts. Do not promise a live record-count limit check from a file selection because the backend parses records and can be configured independently. Show the default/known record cap as explanatory text only if deployment configuration supplies a matching value. Count pasted text with UTF-8 encoding, not JavaScript string length. Preserve the `File` object in component state across failures; a new selection event defines a new command even if name and size match. For text, any change in the submitted content rotates the command identity. Do not read file contents into the page solely to calculate a fingerprint.

### Retry and concurrent action model

Generate a UUID idempotency key when a selected file or pasted content becomes a submission command. Keep that key and exact selected input for retries after network uncertainty, retryable service errors, and replay. Disable concurrent submissions and ignore duplicate submit events while one is active. A server `idempotency_conflict` is a correction state, not a reason to silently mint a new key for the same attempted command. If the owner intentionally chooses a different file, edits the text, or switches to a newly entered command, generate a new key. Keep successful attachment distinct from preview failure so retrying preview never resends source content. The server already owns duplicate protection through its database uniqueness and idempotency logic; no browser-only lock is relied on for correctness.

### Preview and untrusted data

Render source metadata using `display_filename` and other safe fields; do not show `original_filename_untrusted` as a trusted label. Render CSV columns as header plus ordinal, rows as indexed strings, and pasted excerpts inside normal React text nodes or preformatted text. Show the API's `truncated`, `total_records`, `validation_status`, and `confirmed` values as bounded preview context. Avoid `dangerouslySetInnerHTML`, client formula evaluation, CSV export, and client arithmetic. An explicit "unvalidated source" label and a later-stage mapping link or notice keep intake separate from confirmation. A bare link into an unimplemented mapping route would be misleading, so the page should explain that mapping and confirmation follow in a later step until that route exists.

### UI and verification

Use the established Tailwind styles and existing accessibility patterns. Provide explicit states for report loading, current-source loading, selected/invalid input, uploading, server processing, source accepted, preview loading, preview failed, intake failed, and authentication required. Give errors an alert region, progress an accessible value or status, and move focus to a failure summary when submission fails. Keep both paths usable at narrow widths and under reduced motion. Deterministic transport fakes cover upload progress and response-loss replay; a browser journey with an authenticated test backend verifies real multipart behavior and the same-origin rewrite.

## Risks / Trade-offs

- [Frontend limit configuration can drift from backend settings] → Validate positive frontend values, document paired deployment values, and display the authoritative backend `413` or type error if server policy differs.
- [Upload progress reaches 100% before the backend accepts the source] → Keep a separate processing state and display success only after a valid 201 response.
- [A network failure may follow a committed attachment] → Preserve the exact command and idempotency key for retry; accept `Idempotency-Replayed: true` as the original success.
- [Preview may fail after attachment succeeds] → Keep the source acceptance visible and retry only the preview GET.
- [Current backend authentication is integration dependent] → Show `401` distinctly and require an authenticated test backend for the browser journey; do not add fake owner credentials.

## Migration Plan

Add the import route, report-card link, typed source client, frontend limit configuration, and tests. Document matching frontend/backend limits and the authenticated backend prerequisite. No database migration or backend deployment is needed. Rolling back the frontend route leaves previously attached immutable sources intact.
