## Purpose

Produce a readable, reproducible report PDF from an immutable saved version while preserving metric provenance and safely presenting untrusted text.

## ADDED Requirements

### Requirement: Report composition uses one immutable version
The system SHALL compose HTML and PDF content only from a validated saved report-version snapshot and its immutable version metadata. It SHALL use the template version bound to that version, support saved schema 1 and schema 2 snapshots, and reject unsupported or inconsistent snapshot/template bindings with an explicit safe failure. A later draft, current dataset, or changed analysis SHALL NOT affect the report.

#### Scenario: Historical version is rendered after later edits
- **WHEN** a saved version is rendered after the active draft, source, metrics, or analysis changes
- **THEN** its PDF content reflects only the selected version's saved metadata, snapshot, and template version

#### Scenario: Snapshot binding is invalid
- **WHEN** the saved snapshot is malformed, its identity or template binding is inconsistent, or its schema/template version is unsupported
- **THEN** rendering fails with a safe invalid-snapshot outcome and produces no PDF artifact

### Requirement: Template presents the saved report faithfully
The single report layout SHALL include the saved report name, reporting period, version identity, objectives, available and unavailable KPIs with scope/unit/currency or explicit unavailable reason, chart declarations when present, narrative insights and recommendations, limitations, and source claims with their classification. It SHALL distinguish observations, hypotheses, and unvalidated user claims; omit absent sections without inventing figures or interpretation; and derive chart values solely from metrics already present in the snapshot.

#### Scenario: Structured version has complete report content
- **WHEN** a structured saved version contains metrics, charts, narrative items, recommendations, limitations, and claims
- **THEN** the report displays each applicable section in saved order and labels unavailable metrics and content provenance distinctly

#### Scenario: Text-only or legacy version is rendered
- **WHEN** a confirmed text-only version or schema 1 version has no structured metrics or chart declarations
- **THEN** the report renders its saved metadata and text content without fabricated KPIs, charts, or schema 2 bindings

#### Scenario: Chart references an unavailable metric
- **WHEN** a saved chart includes an unavailable metric or a value unsuitable for a plotted scale
- **THEN** the chart retains a labeled tabular or unavailable representation and does not substitute zero, infinity, or invented values

### Requirement: PDF remains legible across languages and page lengths
The system SHALL render the report as a printable PDF with embedded or packaged Vietnamese-capable fonts, legible diacritics, stable page size and margins, and content-aware page breaks. Long narrative text, long labels, many metrics, and multiple chart blocks SHALL remain within printable page bounds without clipping, overlap, or blank overflow pages. Render failure, timeout, or an oversized/invalid PDF SHALL produce an explicit safe failure rather than a downloadable artifact.

#### Scenario: Vietnamese content is exported
- **WHEN** saved report text includes Vietnamese diacritics in headings, labels, and long paragraphs
- **THEN** the resulting PDF displays the full text with legible glyphs and searchable/extractable text

#### Scenario: Report spans multiple pages
- **WHEN** saved content exceeds one page
- **THEN** sections continue in reading order, headings and chart labels remain associated with their content, and no text or chart is clipped at a page boundary

### Requirement: Rendering treats saved text as untrusted data
The system SHALL escape user and AI text before HTML composition, SHALL prohibit executable markup and external network resources during rendering, and SHALL use only packaged fonts, styles, and validated chart data. Renderer errors and logs SHALL not disclose source content, credentials, object keys, signed URLs, or internal provider details.

#### Scenario: Saved narrative contains markup or a remote URL
- **WHEN** a saved narrative or chart label contains HTML, script-like text, or a remote resource reference
- **THEN** it appears as inert text, no external resource is fetched, and no script executes

#### Scenario: Browser rendering fails
- **WHEN** browser launch, font loading, PDF generation, or artifact validation fails
- **THEN** the caller receives a stable sanitized failure and no sensitive saved text is logged
