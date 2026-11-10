## Context

See `proposal.md` for motivation. The repository currently contains project instructions and installed OpenSpec skills, but no `package.json`, local automation, active OpenSpec changes, or application code. The Git remote identifies `dotin2001/ai-marketing-report`; the current local branch is `feature/set_up`. Node.js, npm, the GitHub CLI, Codex CLI, and OpenSpec CLI are installed. GitHub CLI authentication is currently invalid, so live Project discovery cannot be completed until the operator reauthenticates.

OpenSpec skills are instruction packages, not executable names. The installed workflow documents `$openspec-propose` and `$openspec-apply-change` as explicit Codex skill invocations. Official Codex documentation likewise supports explicit `$skill-name` activation and `codex exec` for non-interactive automation. The CLI therefore needs to orchestrate existing tools rather than reimplement OpenSpec or GitHub authentication.

## Goals / Non-Goals

**Goals:**

- Provide a deterministic, auditable local planning and completion-synchronization workflow.
- Make the issue, Project item, repository state, branch, and OpenSpec change traceable in both human-readable and machine-readable forms.
- Enforce semantic completion, command verification, fingerprint stability, and remote-state checks before the only permitted mutation.
- Keep all runtime evidence local and separate from version-controlled OpenSpec artifacts.
- Make external calls and decision logic independently testable with controlled process and GitHub fakes.

**Non-Goals:**

- Implement application features or general-purpose GitHub Project administration.
- Replace the installed OpenSpec skills, the OpenSpec CLI, Codex, or GitHub CLI authentication.
- Automatically approve or apply proposals, manage branches, close issues, or perform Git operations that publish changes.
- Provide GitHub Actions or a hosted coordinator.
- Guarantee an atomic compare-and-swap against changes made by other remote GitHub clients; GitHub Projects v2 does not expose that primitive for field updates.

## Decisions

### 1. Use a small dependency-light Node.js CLI

Add a root `package.json` with `ai:local` pointing to an ESM entry point under `scripts/ai-local/`. Use Node.js built-ins for argument parsing, prompts, subprocesses, hashing, file locking, and tests. Interact with `gh`, `codex`, and `openspec` as bounded child processes with argument arrays and stdin, never interpolated shell command strings.

This matches the required npm entry point, avoids introducing a second authentication or OpenSpec implementation, and keeps the initial tooling surface small. A third-party command framework was considered, but it adds dependency and supply-chain cost without enough value for two modes and a handful of options.

Proposed version-controlled files are:

```text
package.json
ai-local.config.json
scripts/ai-local.mjs
scripts/ai-local/
  cli.mjs
  config.mjs
  process.mjs
  github.mjs
  project.mjs
  issue.mjs
  codex.mjs
  openspec.mjs
  traceability.mjs
  verification.mjs
  evidence.mjs
  fingerprint.mjs
  lock.mjs
  errors.mjs
  schemas/verification.schema.json
  __tests__/*.test.mjs
docs/ai-local-workflow.md
```

The implementation may consolidate modules where cohesion improves, but the security, GitHub, traceability, verification, evidence, and lock boundaries remain separately testable.

### 2. Keep configuration explicit and credentials external

`ai-local.config.json` will contain only non-secret values:

```json
{
  "github": {
    "repository": "dotin2001/ai-marketing-report",
    "projectOwner": "dotin2001",
    "projectNumber": 0,
    "statusField": "Status",
    "todoOption": "Todo",
    "doneOption": "Done"
  },
  "runtimeDirectory": ".ai-local"
}
```

The implementation task must replace the sentinel project number with the actual GitHub Projects v2 number during setup; validation rejects zero, missing, or ambiguous values. An `AI_LOCAL_CONFIG` path may select an alternate explicit configuration, which is useful for forks without adding many environment-variable aliases.

Authentication remains owned by `gh auth`. The CLI checks `gh auth status` without printing token-bearing environment or process data. Minimum permissions are repository issue read access (`repo` for private repositories or equivalent fine-grained repository read access), `read:project` for discovery, and `project` for the final Project field update; organization-owned Projects may additionally require organization read access or SSO authorization.

Configuring only a repository and searching all visible Projects was rejected because it is ambiguous and makes an accidental cross-Project update more likely.

### 3. Query GitHub Projects v2 dynamically and paginate every collection

The GitHub adapter calls `gh api graphql` and parses JSON. It resolves the Project by configured owner and number, queries fields, finds one Status field by exact name, and finds one Todo and Done single-select option by exact name. Project, field, option, item, repository, and issue node IDs are captured from live responses and never committed to configuration.

Project items are paginated to exhaustion. Eligible entries must have all of the following: content type Issue, repository `nameWithOwner` equal to configured repository, and the resolved Status field option name exactly equal to Todo. Draft issues, pull requests, items without Status, items from forks or other repositories, and statuses with case or whitespace differences are excluded.

Issue comments are also paginated. All comments are passed with author, URL, and timestamp provenance so Codex can decide relevance without losing requirements embedded in follow-ups. Queries use stable node identities to prevent issue-number collisions across repositories.

Immediately before mutation, the CLI re-resolves the Project field/options and re-queries the item, issue link, and status. GitHub Projects v2 has no field-value compare-and-swap, so the narrow risk window is mitigated with a repository lock, last-moment read, one targeted mutation, and a post-mutation read.

### 4. Separate trusted control data from untrusted issue data

The runner writes a permission-restricted temporary context document under `.ai-local/tmp/` containing the issue and comments plus their provenance. The Codex prompt labels that document as untrusted task input and explicitly states that it cannot override `AGENTS.md`, OpenSpec skill instructions, repository policy, command allowlists, or mutation boundaries. The prompt itself is fixed by the repository and references the context path; raw issue text is never interpolated into a shell or executable argument.

The runner supplies the repository root and selected identities separately as trusted control data. Temporary issue context is deleted after the child exits; durable link and evidence records contain identifiers, hashes, and summarized verification outcomes rather than credentials or unnecessary issue bodies. Issue-derived commands are never executed.

### 5. Invoke installed skills through Codex, not as shell commands

For new planning, invoke `codex exec` from the repository root with workspace-write sandboxing, JSON event output, a captured final message, and a fixed prompt such as:

```text
Use the $openspec-propose skill to create an implementation-ready change for the
selected GitHub issue in the supplied untrusted context file. Follow AGENTS.md and
repository conventions. Add the required traceability marker, run strict OpenSpec
validation, and stop after planning. Do not implement, apply, or mutate GitHub.
```

Arguments are supplied directly and the prompt is supplied through stdin. The runner captures events to the ignored runtime directory, then independently verifies that the expected change directory, proposal, design, specifications, tasks, and traceability marker exist and that `openspec validate <change-id> --strict --json` passes. A Codex zero exit code is not sufficient.

The manual apply step is intentionally outside `npm run ai:local`. The documentation instructs the operator to invoke `$openspec-apply-change <change-id>` inside Codex (or explicitly ask `codex exec` to use that installed skill). The CLI never spawns the apply workflow.

Directly running `openspec-propose` or `openspec-apply-change` as binaries was rejected because these are installed agent skills, not shell commands. Reproducing their instructions in Node was rejected because it would drift from the installed workflow.

### 6. Use a stable traceability contract and detect duplicates first

Each generated proposal contains a readable `Traceability` section and exactly one machine marker with versioned JSON, for example:

```html
<!-- ai-local-trace:v1 {"repository":"dotin2001/ai-marketing-report","projectId":"PVT_...","projectItemId":"PVTI_...","issueId":"I_...","issueNumber":42,"branch":"feature/x","baseCommit":"abc...","changeId":"gh-42-short-slug"} -->
```

The same identity set is written to `.ai-local/links/<change-id>.json`. The marker is authoritative for portable, reviewable linkage; the runtime record adds synchronization history without putting runtime state into specifications.

Before proposing, scan active and archived proposal markers plus local link records for the repository/issue node pair. An active, internally consistent link can be reused after confirmation. Multiple links, marker/record disagreement, collision with an unrelated change directory, or an archived change that cannot be applied requires explicit resolution. New IDs use `gh-<issue-number>-<normalized-title>` with deterministic truncation and a short issue-node hash only when needed to resolve collision.

The selected issue's branch is the current checked-out branch; the workflow records but does not create or switch it. Sync requires the same recorded branch unless the operator deliberately updates traceability through an approved OpenSpec revision.

### 7. Build synchronization as an ordered fail-closed gate pipeline

`--sync-task` performs these phases and stops at the first failure:

1. Acquire the repository lock and resolve an explicit or unambiguous linked change.
2. Load and cross-check the proposal marker and local link record.
3. Verify the current repository remote and branch, and fetch the live Project, item, issue, comments, field, and option identities.
4. If the item is Done, report idempotent completion; if it is not Todo, report a conflict.
5. Parse the current issue requirements and approved OpenSpec artifacts. Require every implementation and verification task checkbox to be complete.
6. Discover required commands from `AGENTS.md`, project documentation, package scripts, Python configuration, and the approved task list. The trusted source and reason for every selected command are recorded.
7. Run strict OpenSpec validation and every applicable required repository check against the current worktree, recording command arguments, exit status, duration, and redacted bounded output. Missing, skipped, timed-out, blocked, or failed required checks fail closed.
8. Invoke Codex in verification-only mode with a JSON output schema. It inspects the current code, relevant uncommitted changes, issue requirements, artifacts, and command results, and returns one result per acceptance criterion, normative requirement, and task. Each passing result requires concrete file, behavior, or command evidence; `unknown`, `not_applicable` without an approved rationale, or missing evidence fails closed.
9. Independently validate the structured result, command event results, task state, and coverage of every enumerated requirement.
10. Create the post-check code/worktree, specifications, issue requirements, required-check definition, and identity fingerprints. Recompute them before mutation; any difference invalidates the result.
11. Re-query live status and linkage, update only the recorded item's Status field from Todo to Done, and confirm the new value. Do not close the issue.

Codex verification uses read-only intent and a prompt prohibiting code edits, task edits, commits, cleanup, and remote mutations. Workspace-write sandboxing may still be required for repository test caches and build outputs; fingerprinting ignores only declared generated/ignored paths, not relevant source changes. Node independently executes and validates required commands so the model cannot manufacture a passing result.

### 8. Fingerprint all inputs that can invalidate evidence

Evidence uses SHA-256 over canonical manifests rather than timestamps alone:

- Identity fingerprint: repository and Git remote identity, branch, HEAD, Project/item/issue/change node identifiers.
- Code/worktree fingerprint: HEAD plus path, mode, and content digest for all tracked files and non-ignored untracked files, excluding `.ai-local/`; relevant staged and unstaged changes are naturally included.
- Specification fingerprint: canonical digests of the linked change artifacts and governing repository instructions.
- Issue-requirement fingerprint: canonical issue title/body and ordered relevant comment IDs, update timestamps, and bodies.
- Required-check fingerprint: ordered command argument arrays, trusted source locations, tool versions when material, timeout policy, and applicability rationale.

Checks that create ignored caches do not invalidate evidence. A check that edits a tracked or non-ignored file does invalidate the run and is reported. The final fingerprint is taken only after checks and semantic inspection finish, then immediately rechecked before the GitHub mutation.

### 9. Store append-only local evidence and permit narrow retry

`.ai-local/` is added to `.gitignore` and contains:

```text
.ai-local/
  links/<change-id>.json
  evidence/<change-id>/<timestamp>-<attempt-id>.json
  events/<attempt-id>.jsonl
  locks/repository.lock/
  tmp/
```

Evidence records are schema-versioned and append-only. They contain identifiers, per-criterion verdicts and evidence references, command results, fingerprints, timestamp, tool versions, and the GitHub synchronization outcome. Atomic write-then-rename prevents partial JSON. Raw credential-bearing environment data is never captured, and process output passes through redaction before display or persistence.

If verification passes but the GitHub request or confirmation fails, the evidence remains `verification: passed, synchronization: failed`. A later sync may skip expensive checks only after rebuilding and exactly matching every fingerprint and live identity. It still repeats the final Project status/linkage read. Any mismatch starts fresh verification and creates a new evidence record; old records are retained for diagnosis.

Using only Git commit SHA was rejected because the required workflow must include relevant uncommitted work. Overwriting one evidence file was rejected because it loses the retry and failure trail.

### 10. Protect the repository with an atomic process lock

Acquire `.ai-local/locks/repository.lock/` using atomic directory creation before selection linkage or synchronization. Store schema version, PID, hostname, command mode, change/issue when known, and start time. Remove the owned lock on normal exit and handled signals.

When a lock exists, verify whether the same-host PID is alive. A live or remotely hosted lock causes a clear no-change exit. A same-host dead PID is presented as stale, but removal requires interactive confirmation or an explicit documented recovery option; age alone never authorizes deletion. Ownership is rechecked before cleanup so one process cannot remove another process's lock.

This local lock prevents duplicate local proposals and mutations. The last-moment GitHub requery mitigates, but cannot fully eliminate, races with other machines.

### 11. Make errors typed, redacted, and non-destructive

Classify configuration, authentication, selection cancellation, GitHub transport, identity conflict, OpenSpec validation, verification failure, verification blocked, fingerprint change, and synchronization failure separately. Expected no-work and cancellation outcomes are clear and non-destructive. Failures use nonzero exit codes, except an idempotent already-Done outcome.

Subprocesses have explicit timeouts and bounded captured output while full redacted event logs may be kept locally. No failure handler runs `git reset`, `git clean`, checkout, stash, or deletion outside owned temporary/lock files. GitHub mutation code is reachable only through a typed `VerifiedSynchronization` result carrying matching fingerprints.

### 12. Test behavior through dependency injection and scenario fixtures

Adapters accept injectable process, filesystem clock, prompt, and GitHub transports. Node's built-in test runner uses temporary repositories and fixture responses; tests do not require real GitHub, Codex, or OpenSpec network access. Integration tests use fake executables placed first on `PATH` and assert exact argument arrays and mutation payloads.

Coverage includes configuration and authentication failures; Project and comment pagination; dynamic field/option discovery; repository filtering; select, cancel, and no-item paths; prompt injection containment; linked-change reuse and ambiguity; explicit `$openspec-propose` invocation and absence of apply; artifact and validation failure; change selection; identity/status conflicts; incomplete tasks; unmet criteria despite passing tests; check failure/block/skip; dirty-worktree fingerprints; evidence reuse and invalidation; synchronization failure retry; one-item mutation; already-Done idempotence; redaction; live and stale locks; and primary planning and synchronization journeys.

## Risks / Trade-offs

- **[Remote race between final read and Project mutation]** → Minimize the window, update one known item/field, re-read after mutation, and report any inconsistent result; document that cross-machine compare-and-swap is unavailable.
- **[Agent semantic verification can be nondeterministic]** → Require structured exhaustive results, independently enumerate coverage, require concrete evidence, run deterministic checks separately, and fail closed on uncertainty.
- **[Repository checks can be expensive]** → Reuse evidence only with full fingerprint equality; correctness takes priority over speed.
- **[Issue comments can contain prompt injection or secrets]** → Isolate and label them as untrusted, never use them as commands, minimize durable storage, and redact outputs.
- **[Broad worktree hashing can include large files]** → Exclude Git-ignored and runtime paths, stream hashes, and retain complete coverage of tracked and non-ignored work.
- **[Invalid or insufficient current GitHub authentication blocks live setup]** → Preflight early and document exact `gh auth` reauthentication and scope requirements; no planning or sync side effects occur on failure.
- **[A stale local lock can interrupt work]** → Store diagnosable ownership metadata and require explicit recovery rather than guessing.

## Migration Plan

1. Add the npm entry point, configuration schema, runtime ignore rule, CLI modules, and unit tests without enabling any remote mutation by default in tests.
2. Populate and validate the actual Project owner and number, then reauthenticate `gh` with minimum required scopes.
3. Run mocked test suites and a read-only live discovery smoke test that lists eligible items without selecting one.
4. Exercise proposal generation on a disposable Todo issue, confirm artifact traceability and strict validation, and verify that implementation and Project status do not change.
5. Exercise synchronization failure paths before a controlled successful Todo-to-Done update.

Rollback removes the npm entry point and automation files. Local `.ai-local/` evidence may be retained or manually archived; removing automation does not alter OpenSpec artifacts, issues, branches, or Project items. No database or application migration is involved.
