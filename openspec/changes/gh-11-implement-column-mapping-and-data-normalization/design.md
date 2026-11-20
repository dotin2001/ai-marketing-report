## Context

See `proposal.md` and `specs/confirmed-column-mapping-and-normalized-data/spec.md`. Source intake preserves verified CSV bytes. Import review already stores ordinal-based mapping revisions, a `normalize-v1` policy and optional date format, full-record validation issues, and source/period identity. Its validation endpoint is currently `/import-configuration/validate`; the active API contract names `/validate` and `/confirm`. `confirm_import_validation` and `commit_confirmed_dataset` exist as database helpers, but no domain/API operation ties them to the reviewed bytes. `validate_csv` currently returns issues without canonical rows, so confirmation must not assume a warning-free validation itself proves what rows will be committed.

## Goals / Non-Goals

**Goals:**

- Make the confirmation transaction bind one exact reviewed revision to normalized canonical rows and a deterministic identity.
- Reuse the current database and storage boundaries while making replay, stale input, and ownership behavior explicit.
- Avoid a second, divergent implementation of normalization between validation and confirmation.

**Non-Goals:**

- KPI calculation, analysis, frontend screens, or structured extraction from pasted text.
- A new normalization policy, locale inference, currency conversion, or auto-confirmation.

## Decisions

### 1. Produce normalized rows and issues from one pure processing result

Refactor the existing full-file processing path to return ordered issues and normalized row candidates together. Keep `normalize-v1`, supported date formats, ISO currency set, exact `Decimal` parsing, ordinal mappings, and one-based record indexes. Validation persists the issues as it does today. Confirmation reprocesses the verified immutable bytes with the captured revision and compares the resulting issue signature and row count to the stored validation before committing. It rejects any mismatch or blocking issue. This avoids a separately maintained confirm-time parser and prevents a changed policy implementation from silently committing different rows under an old validation. An alternative of building rows from the preview is unsound because the preview is sampled and truncated.

### 2. Derive a stable canonical identity from complete semantic input

Encode source identity and checksum, configuration identity and revision, normalization-policy version and explicit date format, inclusive report period and period revision, and ordered normalized rows in a documented deterministic representation; hash the representation. Preserve exact decimal values as decimal strings rather than floats. Include the mapped canonical field set and source record indexes; the confirmed revision supplies the source ordinals. If the same semantic input is retried, it has the same identity. Do not treat a validation ID or timestamp alone as the dataset identity because either omits the canonical values.

### 3. Confirm and commit in one owner-scoped transaction

The domain service authorizes the report and current CSV source before retrieving verified bytes. It captures the source checksum, configuration revision, policy, period, validation ID, and warning IDs, then processes outside a long transaction. In a final transaction, it resolves the scoped idempotency record and locks resources in a consistent report-then-configuration order, rechecks all captured input, exact warning acknowledgement, persisted issue signature, and row count, then calls the existing confirmation and dataset helpers and finalizes idempotency. Adjust helper lock order and checks where needed so no stale or partial state can commit. Database uniqueness remains the backstop for duplicate validation, confirmation, and canonical identities. An equivalent replay reads the already committed result before freshness checks and returns its original IDs; a conflicting request fingerprint returns `409 idempotency_conflict`. The alternative of separate confirmation and dataset transactions could leave a confirmed import without its canonical data.

### 4. Keep the API within the declared import contract

Add `POST /api/v1/reports/{report_id}/sources/{source_id}/confirm` with a strict request containing validation identity, expected configuration revision, and warning IDs, plus required `Idempotency-Key`. Return the confirmed configuration and current canonical dataset identity in a safe `data` envelope, and `Idempotency-Replayed: true` on replay. Use existing stable error codes: owner-safe `404 resource_not_found`, `409 revision_conflict` or `stale_input` for changed inputs, `409 warning_acknowledgement_required`, `409 idempotency_conflict`, and `422 validation_failed` for blocking data. Keep issue details free of original cell values and storage keys. Maintain the existing validation route for compatibility; the documented `/validate` alias can be added only if its contract tests require it, without changing review semantics. Pasted text stays outside canonical CSV confirmation and follows its separate review gate later.

## Risks / Trade-offs

- **[Source or report changes while normalization runs]** → Recheck source checksum, revision, policy, period, and validation under locks in the final transaction; reject stale work.
- **[Validation and confirmation processing drift]** → Use the same processing result type and compare its deterministic issue signature to the persisted validation before writing current state.
- **[Large CSVs require a second full parse at confirmation]** → Respect existing byte and record limits; parse outside the transaction, then perform only bounded database writes under the final lock.
- **[Concurrent confirmations or reverse lock order cause conflicts]** → Use a consistent lock order and existing uniqueness constraints; test concurrent/replayed commands against PostgreSQL.
- **[Existing canonical row schema does not store each source ordinal]** → Keep the immutable confirmed mapping revision as the field-level ordinal provenance and store one-based record indexes on rows; verify the API can navigate this linkage without adding redundant mutable copies.

## Migration Plan

Use the current confirmed-import, warning-acknowledgement, canonical-dataset, canonical-row, and idempotency tables if they support the atomic path. Introduce an Alembic migration only for a demonstrated constraint or provenance gap, with upgrade verification and a safe downgrade where lossless. Existing unconfirmed validations remain reviewable; validations lacking exact source or period identity remain ineligible for confirmation. Rollback of application wiring leaves already committed immutable datasets intact and historical.
