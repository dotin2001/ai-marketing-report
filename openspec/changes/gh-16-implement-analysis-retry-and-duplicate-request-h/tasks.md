## 1. Retry Policy and Persistence

- [x] 1.1 Add a named three-total-attempt policy and enforce it inside the locked analysis retry transition; verify PostgreSQL tests reject a fourth attempt and concurrent retry requests create at most one next ordinal.
- [x] 1.2 Make logical job failure retryability account for the remaining attempt budget while retaining each attempt's historical failure metadata; verify detail/list contract tests show non-retryable after exhaustion.
- [x] 1.3 Map exhausted and non-retryable retry requests to `409 job_not_retryable`, while retaining safe stale-input, ordinal, key-conflict, and foreign-owner responses; verify API contract tests assert codes, envelopes, and no side effects.

## 2. Duplicate Request Handling

- [x] 2.1 Resolve equivalent create-key replay before current-input validation and preserve scoped fingerprint conflict checks; verify service tests replay an original job after a draft change without creating a job or attempt.
- [x] 2.2 Make fresh keys for the same current semantic input converge through the existing database uniqueness constraint; verify concurrent PostgreSQL tests produce one logical job, one initial attempt, and no duplicate result.
- [x] 2.3 Ensure equivalent retry replay and publish recovery target only the intended persisted ordinal; verify service and worker tests cover repeated clicks, failed publish reconciliation, and duplicate Celery delivery with one provider invocation per attempt.

## 3. Failure and Freshness Boundaries

- [x] 3.1 Align provider, worker, and stale-running recovery classification for timeout, transient unavailability, incomplete output, refusal, invalid output, and stale input; verify deterministic adapter and worker tests assert safe codes and retryability.
- [x] 3.2 Preserve current analysis and draft content when input changes before or during execution, and make completion versus timeout recovery single-winner transitions; verify PostgreSQL race tests in both orders and worker tests assert no stale attachment, duplicate result, or lost prior valid result.
- [x] 3.3 Check error responses and captured logs for provider payloads, prompts, source data, credentials, and internal keys; verify redaction assertions in API, adapter, and worker tests.

## 4. Stage Verification

- [x] 4.1 Run focused tests with `cd backend && python -m pytest tests/unit/ai/test_openai_adapter.py tests/unit/jobs/test_analysis_worker.py tests/integration/db/test_analysis_job_service.py tests/integration/db/test_analysis_jobs.py tests/contract/api/test_analysis_jobs.py`; verify all pass against PostgreSQL and document any unavailable test service.
- [x] 4.2 Run the backend stage suite with `cd backend && python -m pytest`; verify it passes, and record any checks not run plus the reason in the implementation handoff.
- [x] 4.3 Run `openspec validate gh-16-implement-analysis-retry-and-duplicate-request-h --strict --json` after implementation and verify the change remains valid; update documented commands or environment examples if implementation introduces or changes either.
