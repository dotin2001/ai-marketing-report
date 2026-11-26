## 1. Renderer Inputs and Assets

- [x] 1.1 Add a typed immutable version envelope and snapshot validation in `backend/app/pdf/`; verify unit fixtures accept saved schema 1/schema 2 and reject wrong report, template, hash, malformed snapshot, and unsupported schema/template without reading mutable report state.
- [x] 1.2 Add pinned Playwright and PDF inspection dependencies, a locally packaged licensed Vietnamese-capable font, and browser installation/configuration guidance; verify the backend lock resolves, the browser starts in the target runtime, and the packaged font is available offline.
- [x] 1.3 Document renderer timeout, browser executable setup, and the existing generated-PDF size ceiling in `backend/.env.example` and local development docs; verify the example settings load with valid values and reject invalid bounds.

## 2. Saved-Content Composition

- [x] 2.1 Build an allowlisted report view model from the validated snapshot and immutable version metadata; verify fixed fixtures preserve report/period/version data, objectives, metric exact values and unavailable reasons, narrative order/classification, limitations, and user-claim labels without inventing absent sections.
- [x] 2.2 Implement one autoescaped `report-v1` HTML/CSS template and print layout; verify schema 1, schema 2, and text-only HTML fixture assertions cover metadata, KPIs, insights, recommendations, limitations, claims, and omission of unavailable sections.
- [x] 2.3 Render saved `bar`, `line`, and `table` chart declarations from referenced snapshot metric values; verify tests cover comparable values, incompatible units/scopes, unavailable metrics, exact-value labels, and no chart for legacy/text-only snapshots.
- [x] 2.4 Escape all saved labels and narrative, block remote assets and page script execution, and load only local styles/fonts; verify hostile HTML, script-like strings, and remote URLs remain inert text with zero network requests and no sensitive payload in logs.

## 3. Playwright PDF and Verification

- [x] 3.1 Add a bounded Playwright HTML-to-PDF adapter with A4 print settings, font readiness, timeout, resource cleanup, and typed sanitized failures; verify success yields valid PDF bytes while launch/timeout failures yield no artifact or customer-bearing error.
- [x] 3.2 Validate PDF signature, parseability/page count, and `GENERATED_PDF_MAX_BYTES` before return; verify truncated, empty, and oversized outputs fail as `artifact_validation_failed`.
- [x] 3.3 Add fixed-version PDF tests for Vietnamese diacritics and long multipage content, including many metrics, long labels, narrative paragraphs, and charts; verify text extraction and rasterized page review show readable glyphs, ordered sections, stable margins, no clipping/overlap, and no blank overflow pages.
- [x] 3.4 Run focused PDF unit/rendering tests, then `npm run backend:check` and the relevant isolated PostgreSQL version/export suite if the renderer touches version persistence; report any environment-limited checks and require `openspec validate gh-19-build-the-html-report-template-and-pdf-renderer --strict --json` to be valid with no issues.

Verification: the focused PDF suite passed with real local Chrome, including Vietnamese extraction, 2-page and 10-page visual/raster review, and zero network requests. The backend non-PostgreSQL suite passed with the two browser tests skipped when Playwright Chromium was not installed; those tests passed separately using the configured Chrome executable. `npm run backend:check` passed format and lint, then stopped on 69 pre-existing mypy errors in eight unrelated test files. Targeted renderer mypy passed; backend import, lockfile check, and strict OpenSpec validation passed. The renderer does not change version persistence, so the PostgreSQL version/export suite was not applicable.
