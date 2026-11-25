# Analysis preparation contract

The analysis worker builds `analysis-context-v1` after claiming a persisted job. The
context is selected with the job's owner and report IDs, current confirmed dataset,
metric result set, active draft, captured draft and objectives revisions, inclusive
period, and recomputed semantic input identity. A stale input fails as `stale_result`.
No source text, pasted claim, or unconfirmed row is included. Objectives are user
text and must be treated as untrusted data by a future prompt adapter.

## Context limits

| Bound | Limit |
| --- | ---: |
| `objectives` | 20 |
| `objectives[].content` | 1,000 Unicode characters |
| `metrics` | 200 |
| Canonical UTF-8 JSON of the prepared context | 65,536 bytes |

The builder checks one extra objective or metric to detect overflow. Any exceeded
limit fails the job with sanitized, non-retryable `provider_unavailable`; it never
silently drops a KPI. These bounds are constants in `app/ai/context.py` and belong
to `analysis-context-v1`. No provider request is made in this stage.

`PreparedContext` carries `version`, `owner_id`, `report_id`, `job_id`,
`source_id`, `source_checksum_sha256`, `confirmation_id`, `dataset_id`,
`canonical_data_identity`, `result_set_id`,
`numeric_source_identity`, `semantic_input_identity`, `draft_id`,
`draft_revision`, `objectives_revision`, `period`, `represented_currencies`,
`objectives`, and `metrics`. The period has inclusive `start` and `end` dates.
Objectives are ordered by `ordinal`. Metrics are ordered by scope, group identity,
currency, name, and ID. Each metric preserves its ID, name, availability, exact
decimal `value` or `unavailable_reason`, unit, supporting field, scope, group,
campaign, period, currency, represented currencies, ordered exact input totals,
calculation version, result set ID, and numeric source identity. Decimal values
and totals are strings. Currency partitions remain separate.

## Provider-independent result

The runner returns `RunnerOutput` with trusted adapter metadata
`model_identifier`, `prompt_version`, `request_provenance`, and a `response`.
`StructuredOutput` requires all five arrays: `summary`, `findings`, `anomalies`,
`recommendations`, and `data_gaps`. `summary` has at least one item; the other
arrays may be empty. Each section permits at most 20 items with contiguous
one-based `ordinal` values. Every item has `classification` (`observation` or
`hypothesis`), nonblank `content` of at most 2,000 characters, `metric_ids`,
`numeric_assertions`, and `unavailable_reasons`. Extra fields are rejected.

Free-form content cannot contain numeric literals, percentage signs, or currency
symbols. A numeric assertion names a referenced available metric and exactly
matches its serialized `value`, `unit`, `scope`, `period`, and `currency`. A
`data_gaps` item can cite an unavailable metric with its recorded reason and no
numeric assertion. All referenced metric IDs must belong to the prepared set.
The worker adds semantic and numeric source identities after validation, then
stores items and metric links in the same transaction as the result. Invalid
output fails as non-retryable `invalid_structured_output`; no raw response,
context, prompt, or source content appears in job failure details.
