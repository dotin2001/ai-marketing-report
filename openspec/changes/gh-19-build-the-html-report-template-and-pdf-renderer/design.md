## Context

See `proposal.md` and `specs/versioned-report-pdf-rendering/spec.md`. `backend/app/pdf/` is a placeholder. `ReportVersion` already stores snapshot JSON, schema version, SHA-256 snapshot identity, template version, number, and creation time. `backend/app/db/snapshots.py` validates schema 1 and 2; schema 2 adds ordered charts whose metric IDs must occur in the snapshot. Existing PDF export rows, state transitions, asset storage, and authorized download are separate infrastructure. The backend currently has no Playwright dependency or browser/font package.

## Goals / Non-Goals

**Goals:** Provide a pure snapshot-to-view-model/HTML step and a bounded HTML-to-PDF adapter with one `report-v1` template. Make rendering callable by future PDF job orchestration without opening a database session or creating an export row. Verify readable Vietnamese and multipage layout with fixed version fixtures.

**Non-Goals:** Create/retry/export API endpoints, enqueue Celery work, upload output to object storage, alter version snapshots, perform KPI arithmetic, fetch original source content, or add multiple layouts.

## Decisions

1. **Accept a trusted immutable version envelope.** The domain caller supplies `version_id`, report ID, version number, creation time, `snapshot_identity`, `template_version`, and stored snapshot. The builder parses schema 1 or 2 with the existing validator, recomputes the canonical snapshot identity using the existing repository rule, and checks the envelope against the snapshot's report and template. It rejects unknown template versions. Only saved snapshot fields and immutable version metadata enter the view model. Alternative: call the version API or query the current report from the renderer; rejected because either path can drift from the saved state and complicates worker reuse.
2. **Use an allowlisted view model and escaped template.** Build section data from snapshot fields, preserving ordering and provenance labels. Use an autoescaping server-side HTML template and static CSS; never mark saved text safe. No Markdown or raw HTML is interpreted. Dates and exact decimal strings are formatted for display without replacing the underlying values or computing new metrics. Empty optional sections disappear; unavailable metrics display their stored reason and inputs without a numeric value. Alternative: interpolate snapshot JSON in browser JavaScript; rejected because it increases injection and network surface.
3. **Render charts from saved metric results only.** Resolve each schema 2 chart's metric IDs against included metrics. Use deterministic, static HTML/CSS or sanitized inline SVG for `bar`, `line`, and `table` declarations; avoid a remote chart library and browser-side code. Plot only comparable available values with compatible units/scope; for unavailable or incompatible data show a labeled table. Preserve exact values in accessible text. Schema 1 has no chart declarations. Alternative: load live dataset rows or infer chart series; rejected because the snapshot contains only saved metric results and chart declarations.
4. **Package print assets and constrain the browser.** Add a pinned Playwright Python dependency and document browser installation for local/worker images. Bundle an appropriately licensed Vietnamese-capable font subset or family with the backend and load it from local bytes; use `@font-face`, `font-display: block`, and await `document.fonts.ready` before printing. Set a fixed A4 print profile, margins, background printing, no JavaScript, blocked network requests, and a finite browser/render timeout. CSS uses break controls for small cards, chart blocks, and headings while allowing paragraphs and large sections to flow across pages; long words wrap. Alternative: system font fallback or remote font CSS; rejected because output varies by host and remote loads violate the renderer's input boundary.
5. **Validate the artifact before returning.** The renderer checks nonempty bytes, `%PDF` signature, page parseability, and `GENERATED_PDF_MAX_BYTES`; all failures map to a small typed set (`invalid_snapshot`, `render_failed`, `artifact_validation_failed`) for the future job adapter. Browser/provider exception text and customer-bearing HTML stay out of logs and outward errors. Use the existing generated-PDF byte ceiling and introduce a documented renderer timeout setting; configure any browser executable path explicitly for deployment. Alternative: return bytes without checking them; rejected because a worker could mark an invalid artifact successful.

## Risks / Trade-offs

- [Print engines split a section despite CSS hints] → Keep related small blocks together, permit long paragraphs to split, and inspect rendered multipage fixtures at page boundaries.
- [Unicode glyph fallback differs across environments] → Package and license a Vietnamese font, wait for font readiness, and inspect both extracted text and rasterized pages in a fixed browser image.
- [Chart values have incompatible units, scopes, or availability] → Fall back to a labeled table and retain exact values/reasons; never rescale or synthesize missing data.
- [Very large saved text exhausts renderer resources] → Enforce existing output size plus render timeout and fail safely; tests cover long but valid content and pathological output.
- [Older schema 1 snapshots lack charts and explicit dataset bindings] → Parse by declared schema and render only available fields; do not upgrade historical data implicitly.

## Migration Plan

1. Add the renderer dependency, pinned browser install instructions, local font asset/license, backend configuration, and template code. No database migration or API contract change is expected.
2. Run fixed-snapshot unit and PDF rendering tests, including raster review of Vietnamese and multipage fixtures, then the backend stage checks. Document browser/font setup and any new environment variable in `backend/.env.example` and project documentation.
3. Deploy browser and font assets with the backend worker image before future orchestration enables exports. Rollback removes the renderer package; existing versions, export rows, and stored PDFs remain untouched.
