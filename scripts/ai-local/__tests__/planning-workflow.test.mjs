import assert from "node:assert/strict";
import { mkdtemp, readFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

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
