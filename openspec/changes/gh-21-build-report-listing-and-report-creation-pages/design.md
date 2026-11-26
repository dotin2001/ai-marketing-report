## Context

See proposal.md for motivation and `specs/report-listing-and-creation-pages/spec.md` for behavior. `frontend/app/page.tsx` is a foundation placeholder; the frontend has Tailwind, shadcn configuration, environment validation, and Vitest but no product API client or authentication UI. The backend already implements the owner-scoped `GET` and `POST /api/v1/reports` routes and safe envelopes. Its principal dependency currently returns `401` unless an authenticated integration overrides it; this frontend change cannot supply a production identity provider.

## Goals / Non-Goals

**Goals:**

- Establish a narrow typed API boundary and request-state pattern reusable by the report pages.
- Make creation retries safe when the first response is uncertain, while keeping validation and navigation understandable.
- Keep the UI useful under an authenticated backend integration and honest when authentication is unavailable.

**Non-Goals:**

- Implement a login provider, bypass backend authorization, or persist credentials in public frontend configuration.
- Build report detail, import, analysis, editor, history, or PDF pages. A report summary remains informational until its dedicated workflow page exists.

## Decisions

### Routes and composition

Use `/` as the report listing and `/reports/new` as creation, with an App Router server-rendered shell and small Client Components for API state, cursor loading, and form interaction. This preserves the existing entry point and leaves report detail routing for its own stage. A separate all-client application shell would add state machinery before another screen needs it.

### API transport and authentication boundary

Use a single `frontend/lib/` report API module for typed request/response envelopes, safe error parsing, URL construction, and idempotency headers. Send browser requests through a same-origin Next rewrite to the configured backend origin using the existing `NEXT_PUBLIC_API_BASE_URL`; forward ordinary browser credentials through that path and let the backend decide authorization. This avoids a cross-origin browser dependency and keeps internal credentials out of client configuration. The rewrite is a transport choice, not an authentication provider: a backend with the current default principal dependency will still return `401`. Avoid fake local owners or hard-coded bearer tokens. Document the authenticated test override/integration as a prerequisite for end-to-end verification.

### Listing data and state

Request the first page on mount and maintain an explicit state for initial load, empty success, loaded data, first-page error, later-page error, invalid cursor, and authentication required. Keep the server's order and opaque cursor; deduplicate by report ID when appending because a refresh or repeated response can overlap. Keep prior cards visible if a later page fails. Restart from the first page after `invalid_cursor`. Display stage labels derived from server stage values, with a safe fallback for an unfamiliar stage rather than inventing lifecycle state. Use stable ISO date formatting that does not shift calendar days through timezone conversion.

### Creation command and idempotency

Keep form values in local component state, add and remove objective inputs within 1–20, and validate against the backend bounds before sending. Keep server `details[].path` as the source of field-level rejection feedback, mapping known `name`, `period`, and `objectives[index]` paths to labeled inputs; send unknown paths to a form-level summary. Generate a browser UUID idempotency key once per normalized semantic command, retain it through uncertain/retryable failures, and replace it when the semantic command changes. Disable concurrent submits. A `409 idempotency_conflict` requires correction/new command rather than automatic replay with a new key.

On `201` or a successful replay, navigate to `/` with the returned report ID as a `created` query value. The listing authorizes that ID again through `GET /api/v1/reports/{report_id}`, shows the returned summary, and reconciles by ID with the refreshed first page. This also makes an older replay visible when it falls outside that page. An invalid, missing, or unauthorized ID supplies no data and does not block normal listing. The URL carries only a report identifier; it never carries report content or credentials. A server action or general client mutation framework would be disproportionate for this single command.

### UI and verification

Use the existing Tailwind setup and shadcn component conventions, adding only components actually consumed by these pages. Explicit status regions, field descriptions, focus movement, keyboard controls, and responsive layout cover the required states. Test API parsing and page interactions with deterministic fakes; verify a browser journey with a test backend that supplies an authenticated principal. Run frontend lint, typecheck, tests, and production build.

## Risks / Trade-offs

- [Backend currently rejects unauthenticated requests] → Show a distinct authentication state; require a real authentication integration or authorized test override before claiming the live browser journey passes.
- [A network failure may occur after creation commits] → Keep the same idempotency key for the same command and never treat an uncertain response as definite failure or success.
- [Cursor expires between requests] → Preserve displayed cards and offer a first-page restart.
- [A creation replay may refer to an older report outside the first page] → Reauthorize the returned ID with the report detail endpoint and reconcile it with refreshed summaries by ID.
- [Proxying a browser request can alter credential behavior] → Verify cookie forwarding and `401` handling in the browser test; do not add credentials to a public environment variable.

## Migration Plan

Replace the foundation page at `/`, add `/reports/new`, introduce the same-origin API rewrite and typed client, and update frontend environment/setup documentation. No data migration is required. Rolling back the frontend restores the foundation page without changing backend reports.
