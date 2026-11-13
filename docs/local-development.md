# Local development

This guide starts the foundation only: PostgreSQL, Redis, SeaweedFS, the FastAPI health service, and the Next.js setup page. It does not create product tables, queues, reports, or cloud resources.

## Supported toolchain

- Node.js 22.23.2 and npm 10.9.8 (`.nvmrc` and both npm manifests)
- Python 3.12.2 (`.python-version`)
- uv 0.13.7 (`backend/pyproject.toml`)
- Docker Engine 20.10.8 or newer and Docker Compose v2.0.0-rc.1 or newer

Application dependencies are locked in `frontend/package-lock.json` and `backend/uv.lock`. Container images are pinned in `infra/compose.yaml`: PostgreSQL 17.6 Alpine 3.22, Redis 8.2.1 Alpine 3.22, and SeaweedFS 4.53 by manifest digest. Do not substitute floating `latest` tags.

The frontend and backend run on the host. Docker runs only PostgreSQL, Redis, SeaweedFS, and the one-shot bucket initializer.

## First-time setup

From the repository root, create the ignored local environment files:

```sh
cp infra/.env.example infra/.env
cp backend/.env.example backend/.env
cp frontend/.env.local.example frontend/.env.local
```

Replace every `CHANGE_ME` value in `infra/.env` and `backend/.env`. Use local-only credentials, and use the same database, Redis, and S3 values in both files. The local URLs in `backend/.env` must embed the selected passwords where applicable.

The infrastructure process consumes `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_PORT`, `REDIS_PASSWORD`, `REDIS_PORT`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_BUCKET`, `S3_REGION`, `S3_API_PORT`, and `S3_CONSOLE_PORT`.

The backend consumes `APP_ENV`, `APP_HOST`, `APP_PORT`, `HEALTH_CHECK_TIMEOUT_SECONDS`, `LOG_LEVEL`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `DATABASE_URL`, `REDIS_PASSWORD`, `REDIS_URL`, `S3_ENDPOINT_URL`, `S3_REGION`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_BUCKET`, and `S3_USE_SSL`. For local development, `DATABASE_URL` uses `postgresql+psycopg://`, `REDIS_URL` uses `redis://`, `S3_ENDPOINT_URL` is the loopback SeaweedFS S3 URL, and `S3_USE_SSL=false`.

Migration commands read the server-only `MIGRATION_DATABASE_URL`. PostgreSQL integration tests read the server-only `TEST_DATABASE_URL`; it must name a separate database ending in `_test`, use an approved local or CI host, differ from `DATABASE_URL`, and be used only with `APP_ENV=test`. Neither variable is loaded by the web-process `Settings` model or exposed to the frontend.

The frontend consumes only `NEXT_PUBLIC_API_BASE_URL`. Never put a password, access key, database URL, Redis URL, or provider key in a `NEXT_PUBLIC_` variable.

Install locked dependencies:

```sh
npm run frontend:install
uv --directory backend sync --locked --all-groups
```

## Start the foundation

Start in this order from separate terminals where indicated:

1. Validate and start local dependencies.

   ```sh
   npm run infra:validate
   npm run infra:up
   ```

2. Start FastAPI on the host.

   ```sh
   uv --directory backend run uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
   ```

3. Start Next.js on the host in another terminal.

   ```sh
   npm --prefix frontend run dev
   ```

Default local endpoints are:

- Frontend foundation page: <http://127.0.0.1:3000>
- Backend liveness: <http://127.0.0.1:8000/health/live>
- Backend readiness: <http://127.0.0.1:8000/health/ready>
- PostgreSQL: `127.0.0.1:5432`
- Redis: `127.0.0.1:6379`
- SeaweedFS S3 API: `http://127.0.0.1:9000`
- SeaweedFS master UI: <http://127.0.0.1:9001>

Changing a host-port value in `infra/.env` also requires updating the matching backend URL or manual browser URL. A healthy liveness response is `{"status":"ok"}`. Healthy readiness returns `status: "ready"` with `postgresql`, `redis`, and `object_storage` marked ready.

## Database migrations and isolated tests

Alembic is the only product-schema writer. Application startup never calls `create_all`, runs a migration, or changes schema state. Do not manually create, alter, or drop product tables in a shared development, CI, staging, or production database. Review schema changes through a new Alembic revision and verify them against an isolated database.

Set `MIGRATION_DATABASE_URL` to the database being migrated. For ordinary local development it may identify the same local database as `DATABASE_URL`; use a separate migration-role credential where one is configured. These commands do not print the URL:

```sh
uv --directory backend run alembic upgrade head
uv --directory backend run alembic current
uv --directory backend run alembic upgrade head --sql
```

The last command emits offline SQL for review and does not open a database connection. The initial revision's `downgrade base` is intentionally guarded and succeeds only when every reporting product table is empty:

```sh
uv --directory backend run alembic downgrade base
```

If any reporting row exists, the downgrade aborts transactionally and leaves both schema and data at the current revision. Never bypass that guard. Once data exists, rollback requires a separately reviewed forward migration.

PostgreSQL integration tests require a disposable database named with the `_test` suffix. Create it once using your local PostgreSQL administration workflow, grant the test role full control of that database only, then set:

```sh
export APP_ENV=test
export TEST_DATABASE_URL='postgresql+psycopg://TEST_ROLE:TEST_PASSWORD@127.0.0.1:5432/marketing_reports_test'
export MIGRATION_DATABASE_URL="$TEST_DATABASE_URL"
```

`TEST_DATABASE_URL` must differ from `DATABASE_URL`. The test guard also rejects a non-test environment, a database without the `_test` suffix, and an unapproved remote host before any destructive migration or cleanup runs. Keep real values in ignored local environment files or the CI secret store; never commit or paste them into logs.

From a clean checkout, after locked dependency installation and `npm run infra:up`, initialize the disposable schema and run the database checks:

```sh
uv --directory backend run alembic upgrade head
npm run database:test:unit
npm run database:test:integration
npm run database:migrations:verify
npm run database:check
```

The database integration suites require PostgreSQL only. They do not contact Redis, object storage, OpenAI, or a PDF renderer.

## Verification

Frontend, environment-contract, and repository workflow checks do not need external accounts:

```sh
npm test
npm run check
npm run environment:test
npm run environment:check
npm run infra:validate
npm run frontend:check
```

`npm run backend:check` includes the PostgreSQL integration suite and therefore requires the isolated test configuration above and a running local PostgreSQL service. It still requires no Redis, object-storage, OpenAI, or PDF service.

The stack check starts and stops the fixed `mkt-rp-assistant` Compose project, verifies the private bucket and persistence over two start cycles, and preserves named volumes:

```sh
npm run foundation:stack
```

The full live check starts the same dependency stack and backend, verifies healthy endpoints, stops each dependency in turn to test safe readiness failure and recovery, and performs ordinary shutdown:

```sh
npm run foundation:live
```

Both live checks require `infra/.env` and use only local credentials and services. The full verifier derives an isolated backend configuration in memory from that file; ordinary host startup still uses `backend/.env`.

## Ordinary shutdown

Stop the frontend and backend with `Ctrl-C`, then stop containers without removing data:

```sh
npm run infra:down
```

The next `npm run infra:up` reuses the project-scoped volumes.

## Troubleshooting

- A setting-specific startup error means a required key is missing, malformed, or still contains `CHANGE_ME`. Compare the local file with its committed example; do not paste secret values into issue reports.
- A port allocation error means another local process owns the selected loopback port. Change the relevant host port in `infra/.env` and its corresponding backend URL.
- If Docker uses a non-default context, select it before running npm commands, for example `docker context use desktop-linux`, or prefix the command with `DOCKER_CONTEXT=desktop-linux`.
- If readiness names `postgresql`, `redis`, or `object_storage` as unavailable, inspect only that service with `docker compose -p mkt-rp-assistant --env-file infra/.env -f infra/compose.yaml ps` and `docker compose -p mkt-rp-assistant --env-file infra/.env -f infra/compose.yaml logs SERVICE_NAME`. Logs may contain local operational data; do not publish them without review.
- `infra:down` on early Compose v2 releases may require exporting the infra settings into the command environment. The automated live verifiers handle this compatibility case without printing values.

## Updating dependencies

Update one workspace or image deliberately, review release notes, regenerate only its lockfile, and rerun its scoped checks plus `npm run foundation:check`. Keep direct dependency versions and images explicit. For SeaweedFS, update both service image references to the same reviewed tag and multi-architecture manifest digest, then rerun both live checks.

## Destructive local reset

**Data loss:** the command below deletes all local PostgreSQL, Redis, and SeaweedFS data for this project. It removes only the `mkt-rp-assistant` containers and network plus these named volumes:

- `mkt-rp-assistant-postgres-data`
- `mkt-rp-assistant-redis-data`
- `mkt-rp-assistant-object-storage-data`

After confirming that those are the intended resources, run this explicit command from the repository root:

```sh
docker compose -p mkt-rp-assistant --env-file infra/.env -f infra/compose.yaml down --volumes --remove-orphans
```

This reset does not remove source files, host dependency caches, unrelated Docker resources, or any cloud data.
