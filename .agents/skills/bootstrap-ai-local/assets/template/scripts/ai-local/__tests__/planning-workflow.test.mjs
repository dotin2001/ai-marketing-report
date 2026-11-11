import assert from "node:assert/strict";
import { mkdtemp, readFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import { main } from "../cli.mjs";
import { ensureRuntimeLayout } from "../runtime.mjs";
import { runPlanningWorkflow } from "../workflow.mjs";

test("planning journey validates and links a proposal, then stops for review", async () => {
  const repositoryRoot = await mkdtemp(path.join(os.tmpdir(), "ai-local-planning-e2e-"));
  const runtimePath = path.join(repositoryRoot, ".ai-local");
  const calls = [];
  let output = "";
  let capturedPrompt = "";
  const config = {
    repositoryRoot,
    runtimePath,
    github: {
      repository: "owner/repo",
      projectOwner: "owner",
      projectNumber: 2,
      statusField: "Status",
      todoOption: "Todo",
      doneOption: "Done",
    },
  };
  const issue = {
    id: "ISSUE",
    number: 42,
    title: "Safe planning",
    body: "Acceptance criteria",
    url: "https://example.test/issues/42",
    createdAt: "2026-01-01T00:00:00Z",
    updatedAt: "2026-01-02T00:00:00Z",
    repository: { id: "REPO", nameWithOwner: "owner/repo", isFork: false },
    comments: [],
  };

  const result = await runPlanningWorkflow({}, {
    repositoryRoot,
    output: { write: (value) => (output += value) },
    prompt: { ask: async () => "1" },
    loadConfiguration: async () => config,
    ensureRuntimeLayout,
    runPreflight: async () => ({ branch: "feature/test", head: "a".repeat(40) }),
    githubClient: {},
    resolveProject: async () => ({ id: "PROJECT", todoOption: { id: "TODO" } }),
    fetchEligibleItems: async () => [
      { projectItemId: "ITEM", issueId: "ISSUE", issueNumber: 42, title: "Safe", url: issue.url },
    ],
    selectIssue: async (items) => ({ kind: "selected", item: items[0] }),
    fetchIssueContext: async () => issue,
    resolveLinkedChange: async () => ({ kind: "none" }),
    generateChangeId: async () => "gh-42-safe-planning",
    runCodexPlanning: async ({ prompt }) => {
      calls.push("codex");
      capturedPrompt = prompt;
      return { finalOutput: "planned" };
    },
    validateProposalOutput: async ({ changeId, expectedTraceability }) => {
      calls.push("validate");
      return {
        changeId,
        artifactPaths: [path.join(repositoryRoot, "openspec", "changes", changeId, "proposal.md")],
        traceability: expectedTraceability,
        validation: { valid: true },
      };
    },
  });

  assert.equal(result.kind, "proposal_ready");
  assert.deepEqual(calls, ["codex", "validate"]);
  assert.match(capturedPrompt, /\$openspec-propose/);
  assert.doesNotMatch(capturedPrompt, /\$openspec-apply-change/);
  assert.match(output, /manually invoke \$openspec-apply-change gh-42-safe-planning/);
  assert.match(output, /No implementation or GitHub state change/);
  const link = JSON.parse(await readFile(result.recordPath, "utf8"));
  assert.equal(link.traceability.projectItemId, "ITEM");
  assert.equal(link.traceability.issueId, "ISSUE");

  for (const prohibited of ["apply", "mutation", "close", "checkout", "switch", "commit", "push", "merge", "deploy"]) {
    assert.equal(calls.includes(prohibited), false);
  }
});

async function explicitPlanningFixture({ items } = {}) {
  const repositoryRoot = await mkdtemp(path.join(os.tmpdir(), "ai-local-explicit-planning-"));
  const runtimePath = path.join(repositoryRoot, ".ai-local");
  const calls = [];
  let output = "";
  let errorOutput = "";
  let capturedPrompt = "";
  const config = {
    repositoryRoot,
    runtimePath,
    github: {
      repository: "example-owner/example-repo",
      projectOwner: "example-owner",
      projectNumber: 2,
      statusField: "Status",
      todoOption: "Todo",
      doneOption: "Done",
    },
  };
  const item = {
    projectItemId: "ITEM_2",
    issueId: "ISSUE_2",
    issueNumber: 2,
    title: "Explicit planning",
    url: "https://github.com/example-owner/example-repo/issues/2",
    repositoryId: "REPO",
    repository: config.github.repository,
    status: "Todo",
  };
  const issue = {
    id: item.issueId,
    number: item.issueNumber,
    title: item.title,
    body: "## Acceptance Criteria\n- [ ] Explicit issue planning works",
    url: item.url,
    createdAt: "2026-01-01T00:00:00Z",
    updatedAt: "2026-01-02T00:00:00Z",
    repository: { id: "REPO", nameWithOwner: config.github.repository, isFork: false },
    comments: [],
  };
  const dependencies = {
    repositoryRoot,
    output: { write: (value) => (output += value) },
    errorOutput: { write: (value) => (errorOutput += value) },
    prompt: { ask: async () => "yes" },
    loadConfiguration: async () => config,
    ensureRuntimeLayout,
    runPreflight: async () => {
      calls.push("preflight");
      return { branch: "feature/test", head: "a".repeat(40) };
    },
    githubClient: {},
    resolveProject: async () => {
      calls.push("project");
      return { id: "PROJECT", todoOption: { id: "TODO" } };
    },
    fetchEligibleItems: async () => {
      calls.push("items");
      return items ?? [item];
    },
    selectIssue: async () => {
      calls.push("selector");
      throw new Error("Explicit planning must not invoke the numbered selector.");
    },
    fetchIssueContext: async (_github, selectedItem) => {
      calls.push("issue");
      assert.equal(selectedItem.projectItemId, item.projectItemId);
      return issue;
    },
    resolveLinkedChange: async () => {
      calls.push("link-scan");
      return { kind: "none" };
    },
    generateChangeId: async () => "gh-2-explicit-planning",
    runCodexPlanning: async ({ prompt }) => {
      calls.push("codex");
      capturedPrompt = prompt;
      return { finalOutput: "planned" };
    },
    validateProposalOutput: async ({ changeId, expectedTraceability }) => {
      calls.push("validate");
      return {
        changeId,
        artifactPaths: [path.join(repositoryRoot, "openspec", "changes", changeId, "proposal.md")],
        traceability: expectedTraceability,
        validation: { valid: true },
      };
    },
  };
  return {
    repositoryRoot,
    runtimePath,
    calls,
    config,
    item,
    issue,
    dependencies,
    output: () => output,
    errorOutput: () => errorOutput,
    capturedPrompt: () => capturedPrompt,
  };
}

test("explicit issue CLI journey skips selection and preserves the safe proposal pipeline", async () => {
  const fixture = await explicitPlanningFixture();
  const result = await main(
    ["--issue", "https://github.com/example-owner/example-repo/issues/2"],
    fixture.dependencies,
  );

  assert.equal(result.kind, "proposal_ready");
  assert.equal(result.changeId, "gh-2-explicit-planning");
  assert.deepEqual(fixture.calls, ["preflight", "project", "items", "issue", "link-scan", "codex", "validate"]);
  assert.equal(fixture.calls.includes("selector"), false);
  assert.match(fixture.capturedPrompt(), /\$openspec-propose/);
  assert.doesNotMatch(fixture.capturedPrompt(), /\$openspec-apply-change/);
  assert.match(fixture.output(), /manually invoke \$openspec-apply-change gh-2-explicit-planning/);
  assert.match(fixture.output(), /No implementation or GitHub state change/);

  const link = JSON.parse(await readFile(result.recordPath, "utf8"));
  assert.equal(link.traceability.projectItemId, fixture.item.projectItemId);
  assert.equal(link.traceability.issueId, fixture.issue.id);
  for (const prohibited of ["selector", "apply", "mutation", "close", "checkout", "switch", "commit", "push", "merge", "deploy"]) {
    assert.equal(fixture.calls.includes(prohibited), false);
  }
});

test("cross-repository explicit URL stops before preflight or GitHub access", async () => {
  const fixture = await explicitPlanningFixture();
  const result = await main(
    ["--issue", "https://github.com/other/repository/issues/2"],
    fixture.dependencies,
  );
  assert.equal(result.code, "invalid_arguments");
  assert.deepEqual(fixture.calls, []);
  assert.match(fixture.errorOutput(), /does not match configured repository/);
});

for (const [name, items, code] of [
  ["ineligible", [], "explicit_issue_not_eligible"],
  [
    "ambiguous",
    [
      {
        projectItemId: "ITEM_2",
        issueId: "ISSUE_2",
        issueNumber: 2,
        repository: "example-owner/example-repo",
        status: "Todo",
      },
      {
        projectItemId: "ITEM_2_DUPLICATE",
        issueId: "ISSUE_2",
        issueNumber: 2,
        repository: "example-owner/example-repo",
        status: "Todo",
      },
    ],
    "explicit_issue_ambiguous",
  ],
]) {
  test(`${name} explicit Project resolution stops before issue loading or Codex`, async () => {
    const fixture = await explicitPlanningFixture({ items });
    const result = await main(
      ["--issue", "https://github.com/example-owner/example-repo/issues/2"],
      fixture.dependencies,
    );
    assert.equal(result.code, code);
    assert.deepEqual(fixture.calls, ["preflight", "project", "items"]);
    for (const prohibited of ["selector", "issue", "link-scan", "codex", "validate", "mutation"]) {
      assert.equal(fixture.calls.includes(prohibited), false);
    }
  });
}
