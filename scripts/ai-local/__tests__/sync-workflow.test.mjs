import assert from "node:assert/strict";
import test from "node:test";

import { main } from "../cli.mjs";
import { GitHubError, LockError, VerificationError } from "../errors.mjs";
import { parseIssueAcceptanceCriteria } from "../verification.mjs";
import { discoverVerificationChecks, executeRequiredChecks } from "../verification.mjs";
import path from "node:path";

const changeId = "change-7";
const traceability = {
  schemaVersion: 1,
  repository: "owner/repo", repositoryId: "R", projectOwner: "owner", projectNumber: 2,
  projectId: "P", projectItemId: "PI", issueId: "I", issueNumber: 7,
  branch: "feature/work", baseCommit: "a".repeat(40), changeId,
};
const config = {
  repositoryRoot: "/repo", runtimePath: "/repo/.ai-local",
  github: {
    repository: "owner/repo", projectOwner: "owner", projectNumber: 2,
    statusField: "Status", todoOption: "Todo", inProgressOption: "In Progress", doneOption: "Done",
  },
};
const project = {
  id: "P", ownerLogin: "owner", number: 2,
  statusField: { id: "F", name: "Status" }, todoOption: { id: "TODO", name: "Todo" },
  inProgressOption: { id: "PROGRESS", name: "In Progress" },
  doneOption: { id: "DONE", name: "Done" },
};
const item = {
  projectId: "P", projectItemId: "PI", issueId: "I", issueNumber: 7,
  repository: "owner/repo", repositoryId: "R", status: "Todo", statusOptionId: "TODO",
};
const issue = {
  id: "I", number: 7, title: "Task", body: "## Acceptance Criteria\n- Works",
  url: "https://example.test/7", updatedAt: "2026-11-10T00:00:00Z",
  repository: { id: "R", nameWithOwner: "owner/repo" }, comments: [],
};
const manifest = {
  artifactPaths: [],
  criteria: [{ id: "criterion", kind: "issue_criterion", text: "Works" }],
  requirements: [],
  tasks: [{ id: "task", kind: "task", text: "Implement", complete: true }],
  entries: [
    { id: "criterion", kind: "issue_criterion", text: "Works" },
    { id: "task", kind: "task", text: "Implement", complete: true },
  ],
};
const checks = [{
  id: "strict", command: "openspec", args: ["validate", changeId, "--strict", "--json"],
  required: true, timeoutMs: 1000, source: "tasks.md", rationale: "required",
}];
const passedCheck = {
  checkId: "strict", command: "openspec", args: checks[0].args,
  required: true, state: "passed", exitCode: 0, durationMs: 1, stdout: "ok", stderr: "", reason: null,
};
const semantic = {
  schemaVersion: 2, messageType: "final", overallVerdict: "passed", passed: true,
  results: manifest.entries.map(({ id }) => ({
    id, verdict: "passed", evidence: ["verified"], commandEvidenceIds: ["strict"],
  })),
};
const fingerprints = {
  identity: "identity", worktree: "worktree", specifications: "specifications",
  issueRequirements: "issue", requiredChecks: "checks",
};

function sink() {
  return { value: "", write(chunk) { this.value += chunk; } };
}

function harness(overrides = {}) {
  const records = [];
  const state = { mutations: 0, checks: 0, releases: 0, liveReads: 0 };
  const output = sink();
  const errorOutput = sink();
  const dependencies = {
    repositoryRoot: "/repo",
    output,
    errorOutput,
    prompt: { ask: async () => "", close() {} },
    loadConfiguration: async () => config,
    ensureRuntimeLayout: async () => ({ root: "/repo/.ai-local", evidence: "/repo/.ai-local/evidence" }),
    acquireRepositoryLock: async () => ({ release: async () => { state.releases += 1; } }),
    runPreflight: async () => ({
      repository: "owner/repo", branch: "feature/work", head: "b".repeat(40), toolVersions: { node: "22" },
    }),
    githubClient: {},
    resolveProject: async () => project,
    discoverSynchronizationCandidates: async () => [{ changeId, traceability, archived: false }],
    resolveSynchronizationCandidate: async ({ candidates }) => ({ kind: "selected", candidate: candidates[0] }),
    fetchProjectItem: async () => { state.liveReads += 1; return structuredClone(item); },
    fetchIssueContext: async () => structuredClone(issue),
    buildVerificationManifest: async () => manifest,
    discoverVerificationChecks: async () => checks,
    buildFingerprints: async () => ({ ...fingerprints }),
    findReusableEvidence: async () => ({ kind: "fresh" }),
    executeRequiredChecks: async () => {
      state.checks += 1;
      return { passed: true, results: [passedCheck], failedRequired: [] };
    },
    runCodexVerification: async () => semantic,
    persistEvidence: async (_paths, record) => { records.push(record); return `/evidence/${record.attemptId}.json`; },
    synchronizeProjectStatus: async () => {
      state.mutations += 1;
      return { kind: "synchronized", confirmedStatus: "Done" };
    },
    attemptId: "attempt-1",
    ...overrides,
  };
  return { dependencies, records, state, output, errorOutput };
}

test("successful CLI journey changes only the selected Todo item to Done", async () => {
  const value = harness();
  const result = await main(["--sync-task", "--change", changeId], value.dependencies);
  assert.equal(result.kind, "synchronized");
  assert.equal(value.state.mutations, 1);
  assert.equal(value.records.at(-1).synchronization.state, "succeeded");
  assert.match(value.output.value, /Issue remains open/);
  assert.equal(value.state.releases, 1);
});

test("verified In Progress item moves to Done through the same completion gates", async () => {
  const value = harness({
    fetchProjectItem: async () => ({ ...item, status: "In Progress", statusOptionId: "PROGRESS" }),
  });
  const result = await main(["--sync-task", "--change", changeId], value.dependencies);
  assert.equal(result.kind, "synchronized");
  assert.equal(value.state.checks, 1);
  assert.equal(value.state.mutations, 1);
  assert.equal(value.records.at(-1).synchronization.state, "succeeded");
});

function basicHarness(overrides = {}) {
  const policy = { id: "basic-local-v1", requiredCommands: ["git diff --check", "npm run frontend:test", "npm run backend:test"], semanticReview: "optional" };
  const basicChecks = [
    checks[0],
    { id: "git", command: "git", args: ["diff", "--check"], required: true, applicable: true },
    { id: "backend", command: "npm", args: ["run", "backend:test"], required: true, applicable: true },
    { id: "live", command: "npm", args: ["run", "database:check"], required: false, applicable: false },
  ];
  const results = [
    passedCheck,
    { checkId: "git", command: "git", args: ["diff", "--check"], required: true, state: "passed" },
    { checkId: "backend", command: "npm", args: ["run", "backend:test"], required: true, state: "passed" },
    { checkId: "live", command: "npm", args: ["run", "database:check"], required: false, state: "skipped" },
  ];
  const value = harness({
    loadConfiguration: async () => ({ ...config, verification: { syncTask: policy, approvedPostgresHosts: ["localhost"] } }),
    discoverVerificationChecks: async () => basicChecks,
    executeRequiredChecks: async () => ({ passed: true, results, failedRequired: [] }),
    runCodexVerification: async () => assert.fail("optional semantic review should not run by default"),
    ...overrides,
  });
  return { ...value, basicChecks, results };
}

test("basic policy allows Done with skipped or failed optional checks and no semantic result", async () => {
  for (const optionalState of ["skipped", "failed"]) {
    const value = basicHarness();
    value.dependencies.executeRequiredChecks = async () => ({
      passed: true, results: value.results.map((entry) => entry.checkId === "live" ? { ...entry, state: optionalState } : entry),
      failedRequired: [],
    });
    const result = await main(["--sync-task", "--change", changeId], value.dependencies);
    assert.equal(result.kind, "synchronized");
    assert.equal(value.state.mutations, 1);
    assert.equal(value.records.at(-1).verification.criteria.length, 0);
    assert.equal(value.records.at(-1).verification.policyId, "basic-local-v1");
    assert.equal(value.records.at(-1).verification.semanticState, "skipped");
    assert.match(value.output.value, new RegExp(`Optional check npm run database:check: ${optionalState}`));
  }
});

test("failed optional AI review is reported without blocking a passing basic gate", async () => {
  const value = basicHarness({
    environment: { AI_LOCAL_RUN_OPTIONAL_SEMANTIC: "1" },
    runCodexVerification: async () => ({ passed: false, results: [] }),
  });
  const result = await main(["--sync-task", "--change", changeId], value.dependencies);
  assert.equal(result.kind, "synchronized");
  assert.equal(value.state.mutations, 1);
  assert.equal(value.records.at(-1).verification.semanticState, "failed");
  assert.match(value.output.value, /Optional AI semantic review: failed/);
});

test("issue 6 acceptance command uses service-free basic checks and mocked Project status", async () => {
  const acceptanceChange = "gh-6-implement-object-storage-integration";
  const repositoryRoot = path.resolve(import.meta.dirname, "../../..");
  const policy = { id: "basic-local-v1", requiredCommands: ["git diff --check", "npm run frontend:test", "npm run backend:test"], semanticReview: "optional" };
  const observed = [];
  const value = harness({
    repositoryRoot,
    loadConfiguration: async () => ({ ...config, repositoryRoot, verification: { syncTask: policy, approvedPostgresHosts: ["localhost"] } }),
    discoverSynchronizationCandidates: async () => [{ changeId: acceptanceChange, traceability: { ...traceability, changeId: acceptanceChange, issueNumber: 6 }, archived: false }],
    fetchProjectItem: async () => ({ ...item, issueNumber: 6 }),
    fetchIssueContext: async () => ({ ...issue, number: 6 }),
    buildVerificationManifest: async () => ({ ...manifest, artifactPaths: [path.join(repositoryRoot, "openspec", "changes", acceptanceChange, "tasks.md")] }),
    discoverVerificationChecks,
    executeRequiredChecks,
    preflightPostgres: async () => assert.fail("service-free backend:test must not probe PostgreSQL"),
    runCommand: async (command, args, options) => {
      observed.push({ command: [command, ...args].join(" "), env: options.env });
      return { exitCode: 0, timedOut: false, stdout: "", stderr: "" };
    },
    runCodexVerification: async () => assert.fail("semantic review is optional"),
  });
  const result = await main(["--sync-task", "--change", acceptanceChange], value.dependencies);
  assert.equal(result.kind, "synchronized");
  assert.equal(value.state.mutations, 1); // The harness's status writer is a mock; no live GitHub call is possible.
  assert.deepEqual(observed.map((entry) => entry.command), [
    `openspec validate ${acceptanceChange} --strict --json`, "git diff --check", "npm run backend:test",
  ]);
  const backend = observed.find((entry) => entry.command === "npm run backend:test");
  assert.equal(backend.env.APP_ENV, "test");
  assert.equal(backend.env.AI_LOCAL_DISABLE_DOTENV, "1");
  assert.equal(backend.env.TEST_DATABASE_URL, undefined);
  assert.equal(backend.env.MIGRATION_DATABASE_URL, undefined);
  assert.match(value.output.value, /Optional check npm run storage:test:live: skipped/);
});

test("every nonpassing basic check blocks Done and names the command", async () => {
  for (const state of ["failed", "blocked", "skipped", "missing"]) {
    const value = basicHarness();
    value.dependencies.executeRequiredChecks = async () => {
      const results = value.results.filter((entry) => state !== "missing" || entry.checkId !== "backend")
        .map((entry) => entry.checkId === "backend" ? { ...entry, state } : entry);
      return { passed: state === "missing", results, failedRequired: state === "missing" ? [] : [results.find((entry) => entry.checkId === "backend")] };
    };
    const result = await main(["--sync-task", "--change", changeId], value.dependencies);
    assert.equal(result.code, state === "missing" ? "verification_check_missing" : "verification_failed");
    assert.match(value.errorOutput.value, /npm run backend:test/);
    assert.equal(value.state.mutations, 0);
  }
});

test("failed completion check leaves In Progress untouched", async () => {
  const value = harness({
    fetchProjectItem: async () => ({ ...item, status: "In Progress", statusOptionId: "PROGRESS" }),
    executeRequiredChecks: async () => ({ passed: false, results: [], failedRequired: [{ state: "failed" }] }),
  });
  const result = await main(["--sync-task", "--change", changeId], value.dependencies);
  assert.equal(result.code, "verification_failed");
  assert.equal(value.state.mutations, 0);
});

test("natural-language request reaches semantic verification and an unmet fallback cannot mutate", async () => {
  const naturalIssue = {
    ...issue,
    body: "Implement the customer request without requiring a Markdown acceptance section.",
  };
  let verifiedManifest;
  const value = harness({
    fetchIssueContext: async () => structuredClone(naturalIssue),
    buildVerificationManifest: async ({ issue: currentIssue }) => {
      const criteria = parseIssueAcceptanceCriteria(currentIssue);
      return {
        ...manifest,
        criteria,
        entries: [...criteria, ...manifest.tasks],
      };
    },
    runCodexVerification: async ({ manifest: currentManifest }) => {
      verifiedManifest = currentManifest;
      return {
        schemaVersion: 2,
        messageType: "final",
        overallVerdict: "failed",
        passed: false,
        results: currentManifest.entries.map(({ id }, index) => ({
          id,
          verdict: index === 0 ? "failed" : "passed",
          evidence: [index === 0 ? "request is not implemented" : "verified"],
          commandEvidenceIds: ["strict"],
        })),
      };
    },
  });

  const result = await main(["--sync-task", "--change", changeId], value.dependencies);
  assert.equal(result.code, "verification_failed");
  assert.deepEqual(
    verifiedManifest.criteria.map(({ id, text }) => ({ id, text })),
    [{ id: "issue:request", text: naturalIssue.body }],
  );
  assert.equal(value.state.mutations, 0);
});

for (const scenario of [
  {
    name: "incomplete tasks",
    overrides: { buildVerificationManifest: async () => { throw new VerificationError("incomplete_tasks", "unchecked"); } },
    code: "incomplete_tasks",
  },
  {
    name: "failed checks",
    overrides: { executeRequiredChecks: async () => ({ passed: false, results: [{ ...passedCheck, state: "failed" }], failedRequired: [{ state: "failed" }] }) },
    code: "verification_failed",
  },
  {
    name: "blocked infrastructure",
    overrides: { executeRequiredChecks: async () => ({ passed: false, results: [{ ...passedCheck, state: "blocked" }], failedRequired: [{ state: "blocked" }] }) },
    code: "verification_failed",
  },
  {
    name: "unmet acceptance criterion",
    overrides: { runCodexVerification: async () => ({ ...semantic, overallVerdict: "failed", passed: false, results: semantic.results.map((entry, index) => index ? entry : { ...entry, verdict: "failed" }) }) },
    code: "verification_failed",
  },
]) {
  test(`${scenario.name} stops before mutation`, async () => {
    const value = harness(scenario.overrides);
    const result = await main(["--sync-task", "--change", changeId], value.dependencies);
    assert.equal(result.code, scenario.code);
    assert.equal(value.state.mutations, 0);
  });
}

test("identity conflict discovered on the final live read stops mutation", async () => {
  let reads = 0;
  const value = harness({
    fetchProjectItem: async () => {
      reads += 1;
      return { ...item, issueId: reads === 1 ? "I" : "OTHER" };
    },
  });
  const result = await main(["--sync-task", "--change", changeId], value.dependencies);
  assert.equal(result.code, "identity_conflict");
  assert.equal(value.state.mutations, 0);
  assert.equal(value.records.at(-1).verification.state, "passed");
  assert.equal(value.records.at(-1).synchronization.state, "failed");
});

test("fingerprint race after verification stops mutation", async () => {
  let builds = 0;
  const value = harness({
    buildFingerprints: async () => {
      builds += 1;
      return { ...fingerprints, worktree: builds === 3 ? "changed" : "worktree" };
    },
  });
  const result = await main(["--sync-task", "--change", changeId], value.dependencies);
  assert.equal(result.code, "fingerprint_changed");
  assert.equal(value.state.mutations, 0);
});

test("remote failure preserves passing evidence and safe retry reuses it with fresh live reads", async () => {
  let run = 0;
  let checksRun = 0;
  let liveReads = 0;
  let failedRecord;
  const overrides = {
    attemptId: "attempt-retry",
    fetchProjectItem: async () => { liveReads += 1; return structuredClone(item); },
    executeRequiredChecks: async () => {
      checksRun += 1;
      return { passed: true, results: [passedCheck], failedRequired: [] };
    },
    findReusableEvidence: async () => run === 0 || !failedRecord
      ? { kind: "fresh" }
      : { kind: "reuse", record: failedRecord },
    persistEvidence: async (_paths, record) => { if (record.synchronization.state === "failed") failedRecord = record; },
    synchronizeProjectStatus: async () => {
      if (run === 0) throw new GitHubError("github_transport_failed", "remote failed");
      return { kind: "synchronized", confirmedStatus: "Done" };
    },
  };
  const first = harness(overrides);
  let result = await main(["--sync-task", "--change", changeId], first.dependencies);
  assert.equal(result.code, "github_transport_failed");
  assert.equal(failedRecord.verification.state, "passed");
  assert.equal(failedRecord.synchronization.state, "failed");
  run = 1;
  const second = harness({ ...overrides, attemptId: "attempt-retry-2" });
  result = await main(["--sync-task", "--change", changeId], second.dependencies);
  assert.equal(result.kind, "synchronized");
  assert.equal(checksRun, 1);
  assert.equal(liveReads, 4, "both attempts perform initial and final live reads");
});

test("concurrent invocation fails before verification or mutation", async () => {
  const value = harness({
    acquireRepositoryLock: async () => { throw new LockError("lock_held", "another workflow owns the lock"); },
  });
  const result = await main(["--sync-task"], value.dependencies);
  assert.equal(result.code, "lock_held");
  assert.equal(value.state.checks, 0);
  assert.equal(value.state.mutations, 0);
});
