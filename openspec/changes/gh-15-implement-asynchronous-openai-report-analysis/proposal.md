## Why

Analysis jobs can be queued and prepared from confirmed metrics, but the production worker still returns `provider_unavailable` instead of producing a report narrative. Issue #15 completes this stage by calling OpenAI asynchronously, validating the response, and saving an analysis run with reproducible provenance.

## What Changes

- Add a backend-only OpenAI Responses API adapter using Structured Outputs and the existing Pydantic five-section contract. Keep model selection in `OPENAI_MODEL` and version the trusted prompt.
- Send only the job's bounded, revision-bound prepared context. Treat objectives and any future source excerpts as untrusted data, and prohibit model-generated arithmetic or unsupported figures.
- Connect the production analysis worker to the adapter. Persist a result and mark the logical job successful only after schema, metric-grounding, semantic-input, and ownership checks pass.
- Record the actual model identifier, prompt version, request provenance, and dataset/numeric-source identity with the analysis result. Map provider timeout, refusal, incomplete response, invalid output, and other provider failures to the existing sanitized job codes and retry flow.
- Add deterministic fake-provider, worker, and PostgreSQL-backed verification. Live provider checks remain opt-in.

## Capabilities

### New Capabilities

- `asynchronous-openai-report-analysis`: Production provider execution, validated completion, provenance, and safe failure handling for persisted analysis jobs.

### Modified Capabilities

None. The existing job orchestration and prepared-input contracts already define the public job states, response shape, ownership, freshness, and retry boundaries.

## Impact

- Backend AI adapter and prompt module, worker runner wiring, settings and example environment, dependency lockfile, backend documentation, and focused tests. Database changes are not expected because analysis results already store model, prompt, request, and semantic/numeric provenance; any discovered schema gap must use Alembic.
- No new public endpoint or request shape, frontend work, PDF behavior, or version creation is included.

## Acceptance Criteria

- A valid owner-authorized job executes through the worker against the configured OpenAI model and persists one validated five-section analysis result with the actual model, prompt version, request provenance, and job-captured dataset/numeric-source identity.
- Invalid, refused, incomplete, stale, or ungrounded output never marks a job successful or attaches a current result. Existing valid results and newer draft content remain untouched.
- Provider errors and timeouts become persisted, sanitized failures with the existing safe codes and appropriate retryability. Repeated delivery and unchanged-input retry cannot create duplicate results or conflicting attempts.
- The provider request contains only bounded confirmed metrics, explicit limitations, period, and objectives; customer content is delimited as untrusted data. Credentials, raw prompts, provider payloads, and internal identities are not exposed to clients or ordinary logs.

## Verification

- Deterministic adapter tests cover request boundaries, model/prompt selection, valid structured parsing, all provider failure classes, numeric grounding, and redaction. Worker and PostgreSQL tests cover queue-to-success, failure, retry, duplicate delivery, stale input, ownership, and stored provenance.
- At implementation handoff run the focused AI/worker/analysis-job suites, then `cd backend && python -m ruff check .`, `cd backend && python -m mypy app`, and `cd backend && python -m pytest tests`; report any unavailable gate. Live OpenAI checks require explicit opt-in and are not a default gate.
- Planning gate: `openspec validate gh-15-implement-asynchronous-openai-report-analysis --strict --json` must return valid with no issues, and this proposal must contain exactly one versioned traceability marker.

## Traceability

<!-- ai-local-trace:v1 {"schemaVersion":1,"repository":"dotin2001/ai-marketing-report","repositoryId":"R_kgDOVnzlyw","projectOwner":"dotin2001","projectId":"PVT_kwHOBRAmH84Bqz2A","projectItemId":"PVTI_lAHOBRAmH84Bqz2AzhLpz00","issueId":"I_kwDOVnzly88AAAABiSeraw","branch":"feature/backend","baseCommit":"3bf1f2647c728fada76db75452eae01e99afb260","changeId":"gh-15-implement-asynchronous-openai-report-analysis","projectNumber":2,"issueNumber":15} -->
