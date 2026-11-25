# Analysis worker and recovery

Run from `backend/` after `uv sync --locked` and configuration through `backend/.env`:

```sh
.venv/bin/celery -A app.jobs.worker_entry:celery_app worker --loglevel=INFO --queues=analysis
.venv/bin/python -m app.jobs.reconcile
```

Run the reconciler periodically (for example, once per minute). Each pass scans at most 100 queued attempts and 100 stale running attempts. PostgreSQL is the status authority; the reconciler republishes queued attempt identifiers. Duplicate deliveries are harmless because a worker must claim the exact attempt ordinal transactionally. Broker publish failure leaves a committed job queued for the next pass.

Set `REDIS_URL` and `REDIS_PASSWORD` for the broker, `DATABASE_URL` for job state, `REPORT_CURSOR_SIGNING_KEY` for paginated reads, `ANALYSIS_PUBLISH_TIMEOUT_SECONDS` for bounded broker publication, `ANALYSIS_TASK_TIME_LIMIT_SECONDS` for Celery execution, and `ANALYSIS_STALE_RUNNING_SECONDS` above the task time limit. See `.env.example` for local values. The current worker has no AI executor and records `provider_unavailable` as a retryable failure. Once a validated executor is installed, it can return a result through the same worker boundary.

If a worker exits after claiming a job, the attempt remains `running` until the stale running timeout. The reconciler then records a retryable `provider_timeout` failure. An owner can retry the same logical job with a new idempotency key and the observed attempt count; a late completion cannot change the failed attempt. If Redis is unavailable, restore it and run the reconciler again. Never reset job rows or infer status from Redis.
