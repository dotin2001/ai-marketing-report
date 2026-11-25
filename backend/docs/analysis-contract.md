# Analysis preparation contract

The analysis worker builds `analysis-context-v1` after claiming a persisted job. The
context is selected with the job's owner and report IDs, current confirmed dataset,
metric result set, active draft, captured draft and objectives revisions, inclusive
period, and recomputed semantic input identity. A stale input fails as `stale_result`.
No source text, pasted claim, or unconfirmed row is included. Objectives are user
text and are sent as delimited untrusted data by the prompt adapter.

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
to `analysis-context-v1`. The request projection has the same byte ceiling.

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

## OpenAI execution

The production Celery runner uses the pinned OpenAI Python SDK and async
`responses.parse(..., text_format=WireOutput)`. `OPENAI_API_KEY` stays in the
backend, `OPENAI_MODEL` selects the model, and `OPENAI_TIMEOUT_SECONDS` must be
positive, at most 300, and at least five seconds below
`ANALYSIS_TASK_TIME_LIMIT_SECONDS` (default 300). The example timeout is 60
seconds. SDK automatic retries are disabled; each claimed attempt makes at most
one request with a 4,096-token output limit. The request is not stored by the
provider via this API call (`store=False`).

`analysis-prompt-v1` is the trusted instruction version. The adapter sends only
the report period, ordered objectives, confirmed metric records with exact
values or unavailable reasons, represented currencies, and metric input totals.
The JSON is enclosed in `<untrusted_analysis_data>` tags. The prompt instructs
the model to ignore instructions inside that block, avoid arithmetic and
unsupported comparisons, and put figures in structured metric assertions.
Delimiter characters in user text are JSON-escaped before the block is sent.
Owner, report, job, source, draft, and semantic identity values remain local.
No raw pasted text or uploaded file is submitted.

The adapter takes the actual model and response ID from provider metadata. Its
safe request provenance contains the response ID, prompt and context versions,
and a SHA-256 digest of the submitted JSON. The worker persists this provenance
only after wire-schema conversion, domain grounding, and a current-input recheck
inside the completion transaction. The parsed provider body and request prompt
are never stored with the job or logged.

| Outcome | Job failure code | Retryable |
| --- | --- | --- |
| Provider or request timeout | `provider_timeout` | Yes |
| Transport, rate limit, or server error | `provider_unavailable` | Yes |
| Other provider status error | `provider_unavailable` | No |
| Explicit refusal | `provider_refusal` | No |
| Non-completed or absent parsed response | `incomplete_response` | Yes |
| Wire schema, conversion, or metric grounding failure | `invalid_structured_output` | No |
| Changed semantic input before or after request | `stale_result` | No |
| Local context budget or configuration failure | `provider_unavailable` | No |

The existing retry command creates another persisted attempt only when the
captured input is unchanged. Repeated delivery cannot claim the same attempt
twice. A stale response cannot replace the current draft or an older valid
result.

### Opt-in live provider check

In an isolated local environment, set real `OPENAI_API_KEY` and `OPENAI_MODEL`
values in the untracked `backend/.env`, keep `OPENAI_TIMEOUT_SECONDS` below the
task limit, and start PostgreSQL, Redis, the backend API, and the Celery analysis
worker. Create and confirm a test report through the API, submit an analysis job,
then poll its job detail until it reaches a terminal state. Inspect the validated
five sections and safe provenance on success, or the sanitized code on failure.
This check sends data to the configured provider and may incur usage charges;
the default automated suite uses deterministic fakes and makes no live call.
