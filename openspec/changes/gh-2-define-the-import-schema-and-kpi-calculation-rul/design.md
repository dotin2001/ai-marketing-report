## Context

See `proposal.md` for motivation and `specs/marketing-data-import-and-kpi-calculation/spec.md` for normative behavior. The repository is still in its requirements-foundation stage: `project.md` contains a concise CSV and metric baseline, the completed lifecycle change contains overlapping high-level confirmation and metric scenarios, and there is no backend, processing package, database schema, or frontend to modify yet. This change therefore makes the import/calculation contract precise and aligns the product documentation; later focused database, backend, and data-processing changes will implement it in delivery order.

The contract must be deterministic across pandas parsing, API serialization, PostgreSQL persistence, immutable report snapshots, PDF rendering, and frontend display. Original source data remains immutable and untrusted, confirmation is a user action, arithmetic never belongs to AI, and multiple currencies cannot be combined in the MVP.

## Goals / Non-Goals

**Goals:**

- Give later implementation changes one canonical field, type, unit, validation, issue, and metric-result vocabulary.
- Make mapping and confirmation reproducible through source, configuration, policy, and canonical-data identities.
- Define arithmetic and precision boundaries tightly enough for independent implementations and fixtures to agree.
- Allocate verification cases and exact future commands without creating application code in this requirements change.

**Non-Goals:**

- Implement CSV parsing, persistence, APIs, background work, UI, or test harnesses before their owning delivery stages.
- Support pasted text as structured metric input, XLSX, platform-specific exports, arbitrary delimiters, locale guessing, derived/user-defined fields, or currency conversion.
- Define endpoint payload shapes, database tables, UI copy, upload-size limits, or preview-row limits; their owning changes must conform to this behavioral contract.
- Change report lifecycle, ownership, versioning, AI, or PDF requirements already established by the lifecycle foundation.

## Decisions

### 1. Publish one narrow canonical schema instead of accepting arbitrary marketing tables

The canonical record has seven fields:

| Field | Presence | Canonical type | Unit / semantics |
|---|---|---|---|
| `date` | Required | ISO calendar date | `YYYY-MM-DD`, no time or timezone |
| `campaign_name` | Required | Non-empty Unicode string | Trim surrounding whitespace only |
| `currency` | Required | ISO 4217 alphabetic code | Uppercase, versioned supported-code list |
| `impressions` | Optional column | Non-negative integer | Impression count |
| `clicks` | Optional column | Non-negative integer | Click count |
| `spend` | Optional column | Non-negative exact decimal | Major unit of the row currency |
| `leads` | Optional column | Non-negative integer | Lead count |

All dimensions and at least one measure are required for confirmation. Once a measure is mapped, every row needs a valid value for it; column absence is an unavailable KPI input, while cell absence is invalid data. This avoids treating unknown values as zeros while still accepting partial datasets that can support only some metrics.

Arbitrary JSON records or automatic acceptance of common platform fields were rejected because they would make the initial contract non-deterministic. Requiring all four measures was rejected because it would block valid datasets that can still support a subset of metrics.

### 2. Separate immutable source, editable mapping revision, validation result, and confirmed canonical identity

The later processing flow should use explicit boundaries:

1. Decode and parse the immutable source into source-column ordinals and one-based data-record indexes.
2. Apply an editable one-to-one mapping revision.
3. Normalize values with a versioned policy and produce issues without mutating the source.
4. Hash or otherwise identify the canonical rows together with source checksum, mapping revision, normalization-policy version, and report period.
5. Confirm only the exact error-free revision the user reviewed.
6. Calculate metrics only from that confirmed identity.

Source columns use ordinal plus original header because CSV headers need not be unique. Issue locations use a one-based data-record index rather than a physical line number because quoted multiline fields make line numbers parser-dependent. Canonical-data identity must be derived from canonical values and all behavior-affecting revisions; a random identifier alone is insufficient for reproducibility.

Mutating the source into a cleaned file was rejected because it loses evidence. Treating a mapping suggestion as confirmation was rejected because confirmation must be explicit. A timestamp-only identity was rejected because it does not prove semantic equality.

### 3. Keep normalization conservative and independent of machine locale

The initial CSV profile is comma-delimited UTF-8 with an optional byte-order mark. Date parsing accepts only an explicit configured format or an unambiguous ISO date and stores a calendar date. Counts accept plain base-10 integer values. Spend accepts a plain finite base-10 decimal in major currency units. Locale-dependent separators, currency symbols, percentages, booleans, and non-finite values are errors rather than guesses.

The implementation should use exact decimal parsing for spend and must never pass spend through a binary floating-point representation. It should pin or snapshot the supported ISO 4217 code list and record its version as part of the normalization policy. The schema intentionally permits fractional spend beyond a currency's consumer minor-unit exponent because ad platforms commonly report prorated or micro-unit-derived costs; the value remains denominated in the major unit.

Automatic locale detection was rejected because the same source could normalize differently by host or user setting. Enforcing each currency's cash minor-unit scale was rejected because it would discard legitimate advertising-cost precision.

### 4. Use a stable validation taxonomy with errors as the only confirmation blockers

Each issue carries `code`, `severity`, safe message, canonical field where applicable, source-column ordinal where applicable, and one-based source-record index where applicable. The initial stable codes should cover:

- Mapping: `missing_required_mapping`, `missing_measure_mapping`, `duplicate_mapping`, `unmapped_column`.
- Values: `empty_dataset`, `missing_value`, `invalid_date`, `ambiguous_date`, `blank_campaign_name`, `unsupported_currency`, `invalid_count`, `invalid_spend`, `negative_measure`, `out_of_period`.
- Dataset risks: `duplicate_row`, `mixed_currency`.

Mapping and value defects and out-of-period rows are errors. Unmapped columns, exact duplicate canonical rows, and mixed currencies are warnings because their behavior is deterministic: unmapped columns are excluded, duplicates remain included, and spend metrics are currency-isolated. The confirmation record retains the full summary and warning acknowledgement.

Silently dropping invalid rows was rejected because totals would no longer represent the reviewed source. Treating mixed currency as a global blocking error was rejected because per-currency spend metrics and non-monetary CTR remain valid.

### 5. Aggregate first, divide once, and preserve exact inputs

Metric calculation should sum integer counts and exact decimal spend by scope, then divide once. The calculation context should provide at least 28 significant decimal digits and serialize available quotients with at least 12 significant digits; no intermediate or display rounding enters the persisted result. Exact aggregate numerator and denominator totals are stored with every result, so a future calculation-version change remains auditable.

The default MVP scope is the whole confirmed report-period dataset for CTR and one currency partition of that dataset for CPC, CPM, and CPL. A mixed-currency dataset therefore produces one group of spend metrics per currency plus an unavailable report-wide spend result. A zero numerator with a positive denominator is valid zero; a zero denominator is unavailable.

Fixed two-decimal result rounding was rejected because CTR and low-cost metrics can lose material precision. Row-ratio averaging was rejected because it weights rows equally rather than weighting their underlying events. Relying only on a stored rounded value was rejected because it weakens reproducibility.

### 6. Represent unavailable metrics as typed results, not exceptions or sentinel numbers

Calculation returns a result for every requested supported KPI. Available and unavailable results share identity, scope, period, calculation version, and inputs, but unavailable results have no numeric value and carry one primary reason:

- `missing_input`
- `zero_denominator`
- `invalid_input`
- `incompatible_currency`
- `incomparable_period`

Validation normally prevents `invalid_input` from reaching current calculations, but the reason remains part of the boundary so stale or directly requested unconfirmed revisions fail explicitly. Exceptions remain appropriate for infrastructure faults, not domain-level metric availability.

Returning zero, infinity, `NaN`, or `null` without a reason was rejected because clients cannot distinguish a valid zero from missing or invalid data. Omitting unsupported results entirely was rejected because downstream AI, UI, and versions need explicit data gaps.

### 7. Treat period comparison as a compatibility check before arithmetic

The comparison boundary checks duration and boundary policy, metric and calculation version, mappings and normalization, aggregation scope, and currency scope before calculating change. A failed check returns `incomparable_period` and cannot feed comparative AI language. This keeps comparison decisions deterministic even though the first implementation may expose only single-period results.

Comparing whatever two values are available was rejected because differently scoped or defined metrics can produce persuasive but invalid conclusions.

### 8. Apply this requirements change as documentation alignment, then implement in later focused changes

Applying this change should add a concise canonical-schema table, availability vocabulary, and calculation rules to `project.md`, while the delta spec remains the normative detailed contract and becomes the main capability on archive. It should not create backend or processing scaffolding ahead of the database and backend stages. Later changes must reference this capability and implement their owned persistence, API, processing, and UI slices without redefining the rules.

Duplicating the entire spec in `project.md` was rejected because two normative copies would drift. Starting the Stage 3 processing implementation now was rejected because it would violate the repository's dependency order.

## Risks / Trade-offs

- **[Risk] High-precision decimals may serialize differently across Python, PostgreSQL, and JSON clients** → Define decimal strings and exact input totals at trust boundaries, pin calculation versions, and use cross-layer golden fixtures in the later implementation changes.
- **[Risk] A pinned ISO 4217 list becomes outdated** → Version the list and change it only through a reviewed normalization-policy update; existing confirmed imports keep their original policy version.
- **[Risk] Strict parsing rejects files users consider obvious** → Return precise row/field issues and permit an explicit normalization configuration in a later UI, but never fall back to host-locale guessing.
- **[Risk] Keeping exact duplicate rows can double totals** → Warn with both source-record indexes and require the user to correct and re-upload the immutable source rather than silently changing it.
- **[Risk] Separate per-currency metric series adds result cardinality** → Use explicit currency scope in identities and downstream contracts; this cost is preferable to incorrect combined spend.
- **[Trade-off] Out-of-period rows block confirmation** → The report period and metric period remain identical and reproducible, at the cost of requiring source correction or a report-period change.
- **[Trade-off] Requirements are ready before implementation infrastructure exists** → Keep application tasks in later dependency-ordered changes and verify this change through artifact consistency, scenario coverage, traceability, and strict OpenSpec validation.

## Migration Plan

1. Apply only the product-document alignment tasks in this change; do not add application code or infrastructure.
2. Review every field, issue category, formula, unit, availability reason, currency rule, and scenario against `project.md` and the lifecycle foundation.
3. Run the repository documentation/tooling checks and strict OpenSpec validation named in `tasks.md`.
4. After human approval and completion, archive the change so `marketing-data-import-and-kpi-calculation` becomes a main capability.
5. Reference the archived capability from the later database, backend, processing, and frontend changes and add cross-layer golden fixtures when those layers exist.

There is no runtime deployment or production data migration. Before archive, rollback is revision or removal of this unimplemented change; after archive but before application implementation, rollback requires a reviewed OpenSpec change that modifies the capability rather than silently rewriting the contract.
