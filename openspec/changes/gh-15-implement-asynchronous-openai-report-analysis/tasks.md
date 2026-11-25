## 1. Provider Configuration and Prompt Contract

- [x] 1.1 Pin the OpenAI Python SDK in `backend/pyproject.toml` and `backend/uv.lock`; verify locked installation and that the pinned async Responses Structured Outputs helper accepts the chosen wire Pydantic schema against official SDK guidance.
- [x] 1.2 Add validated backend settings for `OPENAI_API_KEY`, `OPENAI_MODEL`, and `OPENAI_TIMEOUT_SECONDS`, including timeout below the analysis task limit; verify `backend/tests/test_config.py` covers missing, blank, and unsafe timeout values without exposing the key.
- [x] 1.3 Add a versioned AI prompt and deterministic projection of `PreparedContext` containing only confirmed metrics, limitations, period, and objectives as delimited untrusted data; verify unit fixtures cover ordering, bounds, mixed currencies, injection text, and exclusion of owner/job IDs, raw source, and secrets.

## 2. Structured Provider Adapter

- [x] 2.1 Define a strict provider wire Pydantic schema for the five sections and convert it to existing `StructuredOutput`; verify `backend/tests/unit/ai/test_openai_adapter.py` covers valid output, required sections, missing or extra fields, unavailable reasons, and conversion failures.
- [x] 2.2 Implement the async Responses adapter using `OPENAI_MODEL`, the versioned prompt, one bounded request, and trusted model/prompt/request provenance; verify fake-client tests inspect request shape, configured model, timeout, actual returned model, response ID/digest provenance, and no raw payload persistence.
- [x] 2.3 Map timeout, transient transport/rate-limit/server errors, refusal, incomplete response, schema failure, and unexpected SDK errors to the existing sanitized failure codes and retryability policy; verify deterministic fake-client tests for every class and redaction of API/log output.

## 3. Worker Integration and Persistence

- [x] 3.1 Wire the production Celery task to the adapter through the existing `AnalysisRunner`, keep dependency construction and client cleanup bounded, and preserve the injectable test runner; verify a PostgreSQL-backed worker test moves a valid job through `queued`, `running`, and `succeeded` with one result.
- [x] 3.2 Reuse domain grounding and transactional freshness checks before success; verify worker/PostgreSQL tests reject invented figures, foreign metric references, changed dataset/objectives/period/draft revisions, and late responses without changing the current draft or existing valid result.
- [x] 3.3 Verify retry and delivery safety with PostgreSQL tests for unchanged-input retry, conflicting or repeated idempotency keys, duplicate/old-ordinal Celery delivery, failed attempt persistence, and one result per logical job.
- [x] 3.4 Verify the owner-scoped analysis-job API returns only validated result and safe provenance on success and sanitized failure codes on failure; extend `backend/tests/contract/api/test_analysis_jobs.py` for foreign-owner isolation and forbidden prompt, source, provider, credential, and stack-trace strings.

## 4. Documentation and Stage Verification

- [x] 4.1 Document the prompt version, model/timeout configuration, request content boundary, failure-code mapping, retry behavior, and opt-in live-provider procedure in backend docs and `.env.example`; verify the documented names and bounds match settings and tests.
- [x] 4.2 Run `cd backend && python -m pytest tests/unit/ai tests/unit/jobs/test_analysis_worker.py tests/integration/db/test_analysis_jobs.py tests/contract/api/test_analysis_jobs.py tests/test_config.py`, then `cd backend && python -m ruff check .`, `cd backend && python -m mypy app`, and `cd backend && python -m pytest tests`; record each result or why a gate could not run. Keep live OpenAI tests opt-in.
