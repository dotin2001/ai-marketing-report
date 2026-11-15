import assert from "node:assert/strict";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { main } from "../cli.mjs";
import { validateConfiguration } from "../config.mjs";
import { CodexError } from "../errors.mjs";
import { runPostgresPreflight } from "../postgres-preflight.mjs";
import { atomicWriteJson, ensureRuntimeLayout } from "../runtime.mjs";
import {
  createLinkRecord,
  createTraceability,
  serializeTraceabilityMarker,
} from "../traceability.mjs";

function sink() {
  return { value: "", write(chunk) { this.value += chunk; } };
}

async function cliFixture({ kind, done = false, scenario = "passing" }) {
  const repositoryRoot = await mkdtemp(path.join(os.tmpdir(), `ai-local-cli-${kind}-`));
  const postgres = kind === "postgresql";
  const issueNumber = postgres ? 83 : 29;
  const changeId = postgres ? "later-postgres-change" : "independent-node-change";
  const branch = postgres ? "feature/postgres-later" : "feature/node-independent";
  const runtimePaths = await ensureRuntimeLayout(path.join(repositoryRoot, ".ai-local"));
  const traceability = createTraceability({
    repository: "fixture-owner/fixture-repo",
    repositoryId: "R_fixture",
    projectOwner: "fixture-owner",
    projectNumber: 11,
    projectId: "P_fixture",
    projectItemId: `ITEM_${issueNumber}`,
    issueId: `ISSUE_${issueNumber}`,
    issueNumber,
    branch,
    baseCommit: (postgres ? "b" : "a").repeat(40),
    changeId,
  });
  const changeRoot = path.join(repositoryRoot, "openspec", "changes", changeId);
  const specRoot = path.join(changeRoot, "specs", "fixture-capability");
  await mkdir(specRoot, { recursive: true });
  await writeFile(path.join(changeRoot, "proposal.md"), `# Proposal\n${serializeTraceabilityMarker(traceability)}\n`);
  await writeFile(path.join(changeRoot, "design.md"), "# Design\nFixture design.\n");
  await writeFile(path.join(specRoot, "spec.md"), [
    "### Requirement: Fixture behavior",
    "The fixture SHALL pass through the real synchronization runner.",
    "",
    "#### Scenario: Current invocation",
    "- **WHEN** this fixture runs",
    "- **THEN** only its current identities and checks apply",
    "",
  ].join("\n"));
  await writeFile(path.join(changeRoot, "tasks.md"), "- [x] Implement and verify the fixture behavior.\n");
  await writeFile(path.join(repositoryRoot, "package.json"), JSON.stringify({
    name: `fixture-${kind}`,
    type: "module",
    scripts: postgres
      ? { "database:check": "node --test fixture-db.test.mjs" }
      : { check: "node --check fixture.mjs" },
  }));
  await atomicWriteJson(
    path.join(runtimePaths.links, `${changeId}.json`),
    createLinkRecord(traceability, { createdAt: "2026-11-15T00:00:00.000Z" }),
  );

  const configurationValue = {
    github: {
      repository: "fixture-owner/fixture-repo",
      projectOwner: "fixture-owner",
      projectNumber: 11,
      statusField: "Delivery",
      todoOption: "Queued",
      doneOption: "Complete",
    },
    runtimeDirectory: ".ai-local",
    verification: {
      autoDiscover: false,
      approvedPostgresHosts: ["localhost"],
      executionProfiles: {},
      commands: [{
        command: "node",
        args: postgres ? ["--test", "fixture-db.test.mjs"] : ["--check", "fixture.mjs"],
        timeoutMs: 5_000,
        executionProfile: postgres ? "postgresql" : "neutral",
      }],
    },
  };
  const config = Object.freeze({
    ...validateConfiguration(configurationValue, repositoryRoot),
    configPath: path.join(repositoryRoot, "ai-local.config.json"),
  });
  const project = {
    id: traceability.projectId,
    ownerLogin: traceability.projectOwner,
    number: traceability.projectNumber,
    statusField: { id: "FIELD", name: "Delivery" },
    todoOption: { id: "QUEUED", name: "Queued" },
    doneOption: { id: "COMPLETE", name: "Complete" },
    unrelatedItems: [{ id: "UNRELATED", status: "In progress" }],
  };
  const item = {
    projectId: traceability.projectId,
    projectItemId: traceability.projectItemId,
    issueId: traceability.issueId,
    issueNumber,
    repository: traceability.repository,
    repositoryId: traceability.repositoryId,
    status: done ? "Complete" : "Queued",
    statusOptionId: done ? "COMPLETE" : "QUEUED",
  };
  const issue = {
    id: traceability.issueId,
    number: issueNumber,
    title: `${kind} fixture`,
    body: "## Acceptance Criteria\n- The current fixture passes its own required checks.",
    url: `https://example.test/issues/${issueNumber}`,
    updatedAt: "2026-11-15T00:00:00.000Z",
    repository: { id: traceability.repositoryId, nameWithOwner: traceability.repository },
    comments: [],
  };
  const state = {
    mutations: 0,
    confirmations: 0,
    issueCloses: 0,
    preflights: 0,
    projectReads: 0,
    itemReads: 0,
    issueReads: 0,
    fingerprintReads: 0,
    postgresPreflights: 0,
    commandEnvironments: [],
    records: [],
  };
  const environment = postgres ? {
    APP_ENV: "local",
    TEST_DATABASE_URL: "postgresql+psycopg://test_role:test_password@localhost:5432/fixture_test",
    MIGRATION_DATABASE_URL: "postgresql+psycopg://migration_role:migration_password@localhost:5432/fixture_test",
    DATABASE_URL: "postgresql+psycopg://app:app_password@localhost:5432/application",
  } : { APP_ENV: "local" };

  const dependencies = {
    repositoryRoot,
    environment,
    output: sink(),
    errorOutput: sink(),
    prompt: { ask: async () => "", close() {} },
    loadConfiguration: async () => config,
    runPreflight: async () => {
      state.preflights += 1;
      return {
        repository: traceability.repository,
        branch,
        head: "c".repeat(40),
        toolVersions: { node: "22.23.2", openspec: "1.12.0" },
      };
    },
    githubClient: {},
    resolveProject: async () => {
      state.projectReads += 1;
      return structuredClone(project);
    },
    fetchProjectItem: async () => {
      state.itemReads += 1;
      return structuredClone(item);
    },
    fetchIssueContext: async () => {
      state.issueReads += 1;
      return structuredClone(issue);
    },
    buildFingerprints: async () => {
      state.fingerprintReads += 1;
      return {
        identity: `${changeId}-identity`,
        worktree: `${changeId}-worktree`,
        specifications: `${changeId}-specifications`,
        issueRequirements: `${changeId}-issue`,
        requiredChecks: `${changeId}-checks`,
      };
    },
    findReusableEvidence: async () => ({ kind: "fresh" }),
    runCommand: async (command, args, options) => {
      state.commandEnvironments.push({ command, args: [...args], environment: { ...options.env } });
      const isApplicationCheck = command === "node";
      return {
        exitCode: scenario === "assertion" && isApplicationCheck ? 1 : 0,
        timedOut: false,
        durationMs: 2,
        stdout: scenario === "assertion" && isApplicationCheck ? "" : "ok",
        stderr: scenario === "assertion" && isApplicationCheck ? "assertion failed" : "",
      };
    },
    preflightPostgres: async (options) => {
      state.postgresPreflights += 1;
      if (scenario === "permission") {
        return { passed: false, code: "postgres_permission_denied", message: "TEST_DATABASE_URL: permission denied." };
      }
      if (scenario === "unreachable") {
        return { passed: false, code: "postgres_unreachable", message: "TEST_DATABASE_URL: service unreachable." };
      }
      return runPostgresPreflight({
        ...options,
        approvedHosts: ["localhost"],
        probeDatabase: async () => ({ passed: true }),
      });
    },
    runCodexVerification: async ({ manifest, checkSummary }) => {
      if (scenario === "progress-only") {
        throw new CodexError("semantic_final_result_missing", "Semantic verifier completed without a terminal result.");
      }
      const entries = scenario === "missing-manifest" ? manifest.entries.slice(0, -2) : manifest.entries;
      return {
        schemaVersion: 2,
        messageType: "final",
        overallVerdict: "passed",
        results: entries.map(({ id }) => ({
          id,
          verdict: "passed",
          evidence: [`${changeId} fixture evidence`],
          commandEvidenceIds: checkSummary.results.map(({ checkId }) => checkId),
          rationale: "Verified by the current fixture.",
        })),
      };
    },
    persistEvidence: async (_paths, record) => {
      state.records.push(record);
      return path.join(repositoryRoot, ".ai-local", "evidence", `${record.attemptId}.json`);
    },
    synchronizeProjectStatus: async () => {
      state.mutations += 1;
      state.confirmations += 1;
      return { kind: "synchronized", confirmedStatus: "Complete" };
    },
    attemptId: `attempt-${kind}-${scenario}-${done ? "done" : "todo"}`,
  };
  return { changeId, config, dependencies, environment, issue, project, state };
}

test("non-PostgreSQL real-CLI fixture passes without database variables and mutates one item once", async () => {
  const fixture = await cliFixture({ kind: "neutral" });
  const unrelatedBefore = structuredClone(fixture.project.unrelatedItems);
  const result = await main(["--sync-task", "--change", fixture.changeId], fixture.dependencies);

  assert.equal(result.kind, "synchronized");
  assert.equal(fixture.state.postgresPreflights, 0);
  assert.equal(fixture.state.mutations, 1);
  assert.equal(fixture.state.confirmations, 1);
  assert.equal(fixture.state.issueCloses, 0);
  assert.deepEqual(fixture.project.unrelatedItems, unrelatedBefore);
});

test("PostgreSQL real-CLI fixture isolates caller-local environment and reuses one preflight", async () => {
  const fixture = await cliFixture({ kind: "postgresql" });
  const result = await main(["--sync-task", "--change", fixture.changeId], fixture.dependencies);

  assert.equal(result.kind, "synchronized");
  assert.equal(fixture.state.postgresPreflights, 1);
  const databaseCheck = fixture.state.commandEnvironments.find((entry) => entry.command === "node");
  assert.equal(databaseCheck.environment.APP_ENV, "test");
  assert.equal(databaseCheck.environment.AI_LOCAL_DISABLE_DOTENV, "1");
  assert.equal(fixture.environment.APP_ENV, "local");
  assert.equal(fixture.state.mutations, 1);
});

for (const scenario of ["permission", "unreachable", "assertion", "progress-only", "missing-manifest"]) {
  test(`PostgreSQL CLI regression ${scenario} performs zero Project mutations`, async () => {
    const fixture = await cliFixture({ kind: "postgresql", scenario });
    const result = await main(["--sync-task", "--change", fixture.changeId], fixture.dependencies);

    assert.equal(result.kind, "error");
    assert.equal(fixture.state.mutations, 0);
    assert.equal(fixture.state.issueCloses, 0);
    if (["permission", "unreachable"].includes(scenario)) {
      assert.equal(fixture.state.records.at(-1).verification.state, "blocked");
    }
    if (scenario === "assertion") {
      const command = fixture.state.records.at(-1).verification.commands.find((entry) => entry.command === "node");
      assert.equal(command.state, "failed");
      assert.equal(command.reasonCode, "test_assertion_failed");
    }
  });
}

for (const [scenario, environmentOverride] of [
  ["missing URL", { TEST_DATABASE_URL: undefined }],
  ["embedded newline", { TEST_DATABASE_URL: "postgresql+psycopg://role:password@localhost:5432/fixture_test\n" }],
  ["unsafe target", { TEST_DATABASE_URL: "postgresql+psycopg://role:password@localhost:5432/production" }],
]) {
  test(`PostgreSQL CLI rejects ${scenario} before mutation`, async () => {
    const fixture = await cliFixture({ kind: "postgresql" });
    Object.assign(fixture.dependencies.environment, environmentOverride);
    const result = await main(["--sync-task", "--change", fixture.changeId], fixture.dependencies);
    assert.equal(result.kind, "error");
    assert.equal(fixture.state.mutations, 0);
    assert.equal(fixture.state.records.at(-1).verification.state, "blocked");
  });
}

test("already-Complete rerun is idempotent but refreshes all live guards", async () => {
  const fixture = await cliFixture({ kind: "neutral", done: true });
  const result = await main(["--sync-task", "--change", fixture.changeId], fixture.dependencies);

  assert.equal(result.kind, "already_done");
  assert.equal(fixture.state.mutations, 0);
  assert.equal(fixture.state.preflights, 2);
  assert.equal(fixture.state.projectReads, 2);
  assert.equal(fixture.state.itemReads, 2);
  assert.equal(fixture.state.issueReads, 2);
  assert.equal(fixture.state.fingerprintReads, 3);
  assert.equal(fixture.issue.closed, undefined);
});
