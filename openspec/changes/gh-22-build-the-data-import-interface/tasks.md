## 1. API and configuration boundary

- [x] 1.1 Extend the typed report detail parser with `current_source_id` and add typed source detail and preview requests in `frontend/lib/`; verify deterministic API tests cover null/current source IDs, safe envelopes, preview fields, and malformed responses.
- [x] 1.2 Share safe API error normalization across JSON and multipart requests, including authentication, `404`, intake codes, network failure, and retryability; verify tests reject unsafe or malformed error payloads without echoing source content.
- [x] 1.3 Add a same-origin multipart CSV transport with `Idempotency-Key`, single `file` form part, upload-byte callbacks, indeterminate fallback, and distinct transfer-complete/server-processing outcomes; verify transport tests cover measured and absent progress, 201 replay, failure, and no manually set multipart boundary.
- [x] 1.4 Add validated public frontend CSV and text byte limits, UTF-8 byte counting, and example environment documentation paired with backend settings; verify boundary tests and check that documented defaults match `project.md` and backend configuration.

## 2. Import page and navigation

- [x] 2.1 Link report cards to `/reports/[reportId]/import` and build the route's report-loading shell; verify component tests cover navigation, report identity, initial loading, `401`, owner-safe `404`, and recoverable load failure.
- [x] 2.2 Add accessible CSV selection and pasted-content controls with visible limits, empty/size/type checks, byte count, and unchanged text submission; verify tests cover selected-file retention, Unicode byte counts, and blocked local submissions.
- [x] 2.3 Add explicit CSV uploading, indeterminate progress, server processing, pasted submission, success, failure, and retry states with focus and status announcements; verify interaction tests cover repeated-click suppression, measured progress, response loss, and reduced-motion behavior.
- [x] 2.4 Keep one idempotency key for an unchanged failed or uncertain command, rotate it on a new file selection or edited text, and retain input through safe server errors; verify component tests cover replay, changed input, conflict, and correction paths.

## 3. Accepted source review

- [x] 3.1 Load a report's current source on entry and the newly accepted source after attachment, then fetch its bounded preview; verify tests cover current-source recovery, successful attachment, and a preview failure that does not resend the source.
- [x] 3.2 Render safe source metadata, CSV column ordinals and row indexes, truncation and record counts, or a pasted excerpt as inert unvalidated text; verify tests cover duplicate headers, header-only CSV, markup/formula-like content, and explicit unconfirmed status.
- [x] 3.3 Add keyboard, focus, responsive, and narrow-screen checks for both import modes and error/retry states; verify an accessibility-focused component or browser test exercises labeled controls and status announcements.

## 4. Stage verification

- [x] 4.1 Run focused frontend API, transport, and import-page tests, then `npm --prefix frontend run lint`, `npm --prefix frontend run typecheck`, `npm --prefix frontend test`, and `npm --prefix frontend run build`; record every result or unavailable gate.
- [x] 4.2 Run an authenticated browser journey for CSV upload and pasted content, one intake rejection and retry, progress, current-source revisit, and bounded preview; verify the same-origin request path, responsive layout, keyboard focus, and `401` behavior, or record the specific integration blocker.
- [x] 4.3 Run `openspec validate gh-22-build-the-data-import-interface --strict --json`, require zero issues, check exactly one versioned traceability marker in `proposal.md`, and review the diff for planning scope before handoff.
