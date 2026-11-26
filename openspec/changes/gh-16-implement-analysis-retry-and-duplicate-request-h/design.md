## Context

See `proposal.md` and `specs/analysis-retry-and-duplicate-request-handling/spec.md`. Stage #13 already supplies PostgreSQL logical jobs, unique `(report_id, semantic_input_identity)`, attempt ordinals, scoped idempotency, a retry API, Celery claim and queue reconciliation, and stale-running recovery. Stage #15 supplies the bounded OpenAI request and most safe failure mapping. Current `retry_analysis_job` has no attempt ceiling, public job failure retryability mirrors only the last failure, and creation checks current input before resolving a replay. Existing worker completion rechecks captured input, but this stage must prove all races and preserve current draft references.

## Goals / Non-Goals

**Goals:** Enforce one retry policy at the transactional boundary; make public eligibility match that policy; preserve idempotent command results and semantic-input uniqueness under concurrent requests; and verify timeout and stale-result transitions end to end.

**Non-Goals:** Automatic retry scheduling, a new endpoint or job state, a frontend retry control, a new provider mode, or changes to PDF jobs. A new semantic input remains a distinct analysis operation through the existing create endpoint.

## Decisions

1. **Keep retries explicit and cap the existing ordinal at three.** Use one named backend policy constant for three total attempts. Check the ceiling inside the locked retry transaction alongside state, failure retryability, ordinal, and captured input checks. Compute public job `failure.retryable` from the stored failure and remaining budget without rewriting historical attempt failure fields. A fourth attempt must not be insertable even under two concurrent retry requests. The alternative of automatic retries could obscure attempt history and amplify provider calls; it is outside this issue.
2. **Resolve idempotent replay before revalidating current input.** The same scoped key and canonical command fingerprint refer to the prior logical result, even if the draft later changed. For a fresh key, validate the current input and use the existing unique job identity to return a job already created for that semantic input. Both paths return the current persisted job detail; only a new queued attempt can be published. A replay does not bypass owner authorization or a conflicting-key check. The alternative of checking current input first incorrectly turns a valid replay into a stale-input conflict.
3. **Use the existing database transitions as the concurrency arbiter.** Keep create uniqueness in PostgreSQL, retry under the row lock with the ordinal guard, and worker claim/finish/fail as compare-and-set transitions. Do not use process-local locks. Publish failure leaves a committed queued attempt for reconciliation. A duplicate publish may reach workers, but only the winner of the claim invokes OpenAI. An idempotent retry replay must not republish a later ordinal accidentally; recovery owns any missing delivery.
4. **Classify failure at the adapter and worker boundary.** Keep stable existing codes and safe messages. Provider timeout and stalled-running recovery map to `provider_timeout`; transient transport, rate limit, and server errors map to retryable `provider_unavailable`; refusal, schema or numeric-grounding failure, and stale input are terminal. Incomplete provider output is retryable only when no complete parsed response exists. Cap exhaustion changes logical job eligibility, not the recorded reason an individual attempt failed. Preserve `OPENAI_TIMEOUT_SECONDS < ANALYSIS_TASK_TIME_LIMIT_SECONDS < ANALYSIS_STALE_RUNNING_SECONDS`; document any changed settings in `.env.example` and project documentation.
5. **Recheck semantic freshness at attachment and guard the draft.** The worker captures the job ordinal and input identity, validates the output, then rechecks the complete input inside its completion transaction. A stale response is recorded as a safe failed attempt and cannot update `Report.current_analysis_result_id` or mutable draft narrative. Timeout recovery and completion compete through the same running-state and ordinal predicates, so the loser cannot create a result or overwrite the winner. Retain existing valid result references on failure.
6. **Keep API errors stable.** Map cap or a non-retryable failure to `409 job_not_retryable`; keep stale revision, stale input, or ordinal conflicts in the existing safe conflict family, idempotency fingerprint conflicts as `409 idempotency_conflict`, and foreign resources as owner-safe `404`. Do not return provider payloads or internal identities in errors.

## Risks / Trade-offs

- [Three attempts can be insufficient for a prolonged outage] → A changed semantic input creates a new operation; expose exhausted jobs clearly and keep the limit fixed for this MVP stage.
- [A replay after input change could be mistaken for a fresh request] → Resolve it only for the exact scoped key and fingerprint, and never queue another attempt from replay.
- [Worker completion can race timeout recovery] → Keep result insertion and terminal transition in one transaction and test both winning orders against PostgreSQL.
- [Provider SDK errors can contain customer data] → Persist and log only fixed safe codes and messages; assert redaction in adapter, worker, and API tests.

## Migration Plan

1. Add the policy and service/repository behavior, then focused tests. Existing attempt rows and idempotency records remain valid; jobs already at or above the cap become non-retryable without rewriting history.
2. No schema migration is expected because the present job, attempt, unique index, and idempotency tables carry the required state. If implementation needs a schema change, add an Alembic migration with upgrade verification and a safe downgrade where possible.
3. Deploy API and workers together so public eligibility and retry enforcement agree. Rolling back to the previous code would remove the cap, so keep the new policy in place until any rollback plan preserves it.
