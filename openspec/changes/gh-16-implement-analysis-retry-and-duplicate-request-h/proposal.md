## Why

Analysis jobs already persist attempts and reject some stale work, but retry eligibility is unbounded and duplicate submissions need explicit end-to-end guarantees across HTTP requests, worker delivery, and timeout recovery. This change completes the issue #16 behavior before later report stages depend on reliable analysis outcomes.

## What Changes

- Classify analysis failures with stable safe codes and retryability, including provider timeouts and stalled workers.
- Limit one logical analysis job to three total attempts, including the first attempt; retries remain explicit owner requests against the same current semantic input.
- Make repeated create and retry requests, concurrent clicks, and repeated broker delivery converge on one logical job and the intended attempt without duplicate provider work or results.
- Reject stale retry or completion after a relevant draft or input change, preserving newer content and prior valid analysis.
- Verify the retry, duplicate-request, timeout, ownership, and redaction behavior with deterministic adapter, PostgreSQL, worker, and API tests.

## Capabilities

### New Capabilities

- `analysis-retry-and-duplicate-request-handling`: Bounded retry policy, duplicate-request convergence, timeout recovery, and stale-result protection for analysis jobs.

### Modified Capabilities

None. The existing job and OpenAI capabilities are active change deltas rather than archived main specs; this delta adds the bounded policy while retaining their contracts.

## Impact

The existing `/api/v1/reports/{report_id}/analysis-jobs` create, status, and retry contracts retain their routes and response envelopes. Implementation is expected in `backend/app/domain/analysis_jobs.py`, `backend/app/db/repositories.py`, `backend/app/jobs/analysis_worker.py`, and the OpenAI adapter/configuration only where timeout classification or limits require it. PostgreSQL job, attempt, and idempotency records remain the authority; a migration is required only if a needed database constraint or column changes. The issue's acceptance intent is preserved: classify retryable errors, limit retries, handle timeouts, prevent repeated clicks from creating duplicate jobs, and prevent outdated results from overwriting a changed draft.

<!-- ai-local-trace:v1 {"schemaVersion":1,"repository":"dotin2001/ai-marketing-report","repositoryId":"R_kgDOVnzlyw","projectOwner":"dotin2001","projectId":"PVT_kwHOBRAmH84Bqz2A","projectItemId":"PVTI_lAHOBRAmH84Bqz2AzhLp0Bk","issueId":"I_kwDOVnzly88AAAABiSe6PQ","branch":"feature/backend","baseCommit":"8fd0a30d610be2eb599a4f110c06bd9d13e647ec","changeId":"gh-16-implement-analysis-retry-and-duplicate-request-h","projectNumber":2,"issueNumber":16} -->
