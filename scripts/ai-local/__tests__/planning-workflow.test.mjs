import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import { main } from "../cli.mjs";
import { GitHubError } from "../errors.mjs";
import { ensureRuntimeLayout } from "../runtime.mjs";
import { runPlanningWorkflow } from "../workflow.mjs";
import { statusSyncQueries } from "../status-sync.mjs";

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
      inProgressOption: "In Progress",
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
  const selected = {
    projectItemId: "ITEM", issueId: "ISSUE", issueNumber: 42, title: "Safe",
    url: issue.url, repository: "owner/repo", repositoryId: "REPO",
    status: "Todo", statusOptionId: "TODO", isFork: false,
  };
  const other = { ...selected, projectItemId: "OTHER", issueId: "OTHER_ISSUE", issueNumber: 41 };
  let liveStatus = { name: "Todo", optionId: "TODO" };
  const githubClient = {
    async graphql(document, variables) {
      if (document.includes("mutation AiLocalUpdateProjectStatus")) {
        assert.equal(variables.itemId, selected.projectItemId);
        assert.equal(variables.optionId, "PROGRESS");
        calls.push("update");
        liveStatus = { name: "In Progress", optionId: "PROGRESS" };
        return { updateProjectV2ItemFieldValue: { projectV2Item: { id: selected.projectItemId } } };
      }
      assert.equal(variables.itemId, selected.projectItemId);
      calls.push("read");
      return { node: {
        id: selected.projectItemId, updatedAt: "2026-01-02T00:00:00Z",
        status: liveStatus,
        content: {
          __typename: "Issue", id: issue.id, number: issue.number,
          title: issue.title, url: issue.url, updatedAt: issue.updatedAt,
          repository: { id: "REPO", nameWithOwner: "owner/repo", isFork: false },
        },
      } };
    },
  };

  const result = await runPlanningWorkflow({}, {
    repositoryRoot,
    output: { write: (value) => (output += value) },
    prompt: { ask: async () => "1" },
    loadConfiguration: async () => config,
    ensureRuntimeLayout,
    runPreflight: async () => ({ branch: "feature/test", head: "a".repeat(40) }),
    githubClient,
    resolveProject: async () => ({
      id: "PROJECT", statusField: { id: "STATUS", name: "Status" },
      todoOption: { id: "TODO", name: "Todo" },
      inProgressOption: { id: "PROGRESS", name: "In Progress" },
    }),
    fetchEligibleItems: async () => [other, selected],
    selectIssue: async (items) => ({ kind: "selected", item: items[1] }),
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
  assert.deepEqual(calls, ["read", "update", "read", "codex", "validate"]);
  assert.match(capturedPrompt, /\$openspec-propose/);
  assert.doesNotMatch(capturedPrompt, /\$openspec-apply-change/);
  assert.match(output, /manually invoke \$openspec-apply-change gh-42-safe-planning/);
  assert.match(output, /Project item is In Progress/);
  const link = JSON.parse(await readFile(result.recordPath, "utf8"));
  assert.equal(link.traceability.projectItemId, "ITEM");
  assert.equal(link.traceability.issueId, "ISSUE");

  for (const prohibited of ["apply", "close", "checkout", "switch", "commit", "push", "merge", "deploy"]) {
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
      repository: "dotin2001/ai-marketing-report",
      projectOwner: "dotin2001",
      projectNumber: 2,
      statusField: "Status",
      todoOption: "Todo",
      inProgressOption: "In Progress",
      doneOption: "Done",
    },
  };
  const item = {
    projectItemId: "ITEM_2",
    issueId: "ISSUE_2",
    issueNumber: 2,
    title: "Explicit planning",
    url: "https://github.com/dotin2001/ai-marketing-report/issues/2",
    repositoryId: "REPO",
    repository: config.github.repository,
    status: "Todo",
    statusOptionId: "TODO",
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
      return {
        id: "PROJECT", statusField: { id: "STATUS", name: "Status" },
        todoOption: { id: "TODO", name: "Todo" },
        inProgressOption: { id: "PROGRESS", name: "In Progress" },
      };
    },
    fetchProjectIssues: async () => {
      calls.push("items");
      return items ?? [item];
    },
    startProjectWork: async () => {
      calls.push("start");
      return { kind: "started" };
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

async function interactivePlanningFixture() {
  const fixture = await explicitPlanningFixture();
  fixture.dependencies.fetchEligibleItems = async () => {
    fixture.calls.push("items");
    return [fixture.item];
  };
  fixture.dependencies.selectIssue = async (items) => {
    fixture.calls.push("selector");
    return { kind: "selected", item: items[0] };
  };
  return fixture;
}

function linkedChange(fixture, projectItemId = fixture.item.projectItemId) {
  return { kind: "reuse", changeId: "existing", traceability: {
    projectId: "PROJECT", projectItemId,
    issueId: fixture.issue.id, repositoryId: fixture.issue.repository.id,
  } };
}

function liveProjectItem(fixture, { status = "Todo", optionId = "TODO", issueId = fixture.issue.id } = {}) {
  return { node: {
    id: fixture.item.projectItemId, updatedAt: fixture.issue.updatedAt,
    status: { name: status, optionId },
    content: {
      __typename: "Issue", id: issueId, number: fixture.issue.number,
      title: fixture.issue.title, url: fixture.issue.url, updatedAt: fixture.issue.updatedAt,
      repository: { id: "REPO", nameWithOwner: fixture.config.github.repository, isFork: false },
    },
  } };
}

test("cancelled numbered selection stops before issue loading or status write", async () => {
  const fixture = await interactivePlanningFixture();
  fixture.dependencies.selectIssue = async () => {
    fixture.calls.push("selector");
    return { kind: "cancelled", exitCode: 0 };
  };
  const result = await main([], fixture.dependencies);
  assert.equal(result.kind, "cancelled");
  assert.deepEqual(fixture.calls, ["preflight", "project", "items", "selector"]);
});

test("declined numbered linked reuse leaves Todo unchanged", async () => {
  const fixture = await interactivePlanningFixture();
  fixture.dependencies.resolveLinkedChange = async () => {
    fixture.calls.push("link-scan");
    return linkedChange(fixture);
  };
  fixture.dependencies.confirmReuse = async () => false;
  const result = await main([], fixture.dependencies);
  assert.equal(result.kind, "cancelled");
  assert.deepEqual(fixture.calls, ["preflight", "project", "items", "selector", "issue", "link-scan"]);
});

test("accepted numbered linked reuse starts before validation", async () => {
  const fixture = await interactivePlanningFixture();
  fixture.dependencies.resolveLinkedChange = async () => {
    fixture.calls.push("link-scan");
    return linkedChange(fixture);
  };
  fixture.dependencies.confirmReuse = async () => true;
  const result = await main([], fixture.dependencies);
  assert.equal(result.kind, "proposal_ready");
  assert.equal(result.reused, true);
  assert.deepEqual(fixture.calls, ["preflight", "project", "items", "selector", "issue", "link-scan", "start", "validate"]);
  assert.match(fixture.output(), /Project item is In Progress/);
});

test("numbered linked item mismatch stops before start", async () => {
  const fixture = await interactivePlanningFixture();
  fixture.dependencies.resolveLinkedChange = async () => {
    fixture.calls.push("link-scan");
    return linkedChange(fixture, "OTHER_ITEM");
  };
  const result = await main([], fixture.dependencies);
  assert.equal(result.code, "link_disagreement");
  assert.deepEqual(fixture.calls, ["preflight", "project", "items", "selector", "issue", "link-scan"]);
});

test("numbered start rejects stale live status and linkage without mutation", async () => {
  for (const stale of [
    { status: "Done", optionId: "DONE" },
    { status: "In Progress", optionId: "PROGRESS" },
    { issueId: "OTHER" },
  ]) {
    const fixture = await interactivePlanningFixture();
    delete fixture.dependencies.startProjectWork;
    let writes = 0;
    fixture.dependencies.githubClient = { graphql: async (query) => {
      if (query === statusSyncQueries.updateStatus) writes += 1;
      return liveProjectItem(fixture, stale);
    } };
    const result = await main([], fixture.dependencies);
    assert.equal(result.kind, "error");
    assert.equal(writes, 0);
    assert.equal(fixture.calls.includes("codex"), false);
    assert.equal(fixture.calls.includes("validate"), false);
  }
});

test("numbered start mutation and confirmation failures stop before Codex", async () => {
  for (const failure of ["mutation", "confirmation"]) {
    const fixture = await interactivePlanningFixture();
    delete fixture.dependencies.startProjectWork;
    let writes = 0;
    fixture.dependencies.githubClient = { graphql: async (query) => {
      if (query === statusSyncQueries.updateStatus) {
        writes += 1;
        if (failure === "mutation") throw new Error("secret provider payload");
        return { updateProjectV2ItemFieldValue: { projectV2Item: { id: fixture.item.projectItemId } } };
      }
      return liveProjectItem(fixture);
    } };
    const result = await main([], fixture.dependencies);
    assert.equal(result.code, failure === "mutation" ? "work_start_mutation_failed" : "work_start_confirmation_failed");
    assert.equal(writes, 1);
    assert.equal(fixture.calls.includes("codex"), false);
    assert.equal(fixture.calls.includes("validate"), false);
    assert.doesNotMatch(fixture.errorOutput(), /secret provider payload/);
  }
});

test("failed numbered proposal retries by URL without another status write", async () => {
  const fixture = await interactivePlanningFixture();
  delete fixture.dependencies.startProjectWork;
  let status = "Todo";
  let writes = 0;
  fixture.dependencies.githubClient = { graphql: async (query, variables) => {
    if (query === statusSyncQueries.updateStatus) {
      assert.equal(variables.itemId, fixture.item.projectItemId);
      writes += 1;
      status = "In Progress";
      return { updateProjectV2ItemFieldValue: { projectV2Item: { id: fixture.item.projectItemId } } };
    }
    return liveProjectItem(fixture, {
      status, optionId: status === "Todo" ? "TODO" : "PROGRESS",
    });
  } };
  fixture.dependencies.runCodexPlanning = async () => {
    fixture.calls.push("codex-failed");
    throw new GitHubError("planning_failed", "Proposal generation failed; retry by issue URL.");
  };
  const first = await main([], fixture.dependencies);
  assert.equal(first.code, "planning_failed");
  assert.equal(writes, 1);
  assert.deepEqual(await readdir(path.join(fixture.runtimePath, "links")), []);
  assert.equal(fixture.calls.includes("validate"), false);

  fixture.dependencies.fetchProjectIssues = async () => {
    fixture.calls.push("items");
    return [{ ...fixture.item, status: "In Progress", statusOptionId: "PROGRESS" }];
  };
  fixture.dependencies.runCodexPlanning = async () => {
    fixture.calls.push("codex-retry");
    return { finalOutput: "planned" };
  };
  const retried = await main(["--issue", fixture.item.url], fixture.dependencies);
  assert.equal(retried.kind, "proposal_ready");
  assert.equal(writes, 1);
  assert.match(fixture.output(), /Project item is In Progress/);
});

test("explicit issue CLI journey skips selection and preserves the safe proposal pipeline", async () => {
  const fixture = await explicitPlanningFixture();
  const result = await main(
    ["--issue", "https://github.com/dotin2001/ai-marketing-report/issues/2"],
    fixture.dependencies,
  );

  assert.equal(result.kind, "proposal_ready");
  assert.equal(result.changeId, "gh-2-explicit-planning");
  assert.deepEqual(fixture.calls, ["preflight", "project", "items", "issue", "link-scan", "start", "codex", "validate"]);
  assert.equal(fixture.calls.includes("selector"), false);
  assert.match(fixture.capturedPrompt(), /\$openspec-propose/);
  assert.doesNotMatch(fixture.capturedPrompt(), /\$openspec-apply-change/);
  assert.match(fixture.output(), /manually invoke \$openspec-apply-change gh-2-explicit-planning/);
  assert.match(fixture.output(), /Project item is In Progress/);

  const link = JSON.parse(await readFile(result.recordPath, "utf8"));
  assert.equal(link.traceability.projectItemId, fixture.item.projectItemId);
  assert.equal(link.traceability.issueId, fixture.issue.id);
  for (const prohibited of ["selector", "apply", "close", "checkout", "switch", "commit", "push", "merge", "deploy"]) {
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

test("an already In Progress explicit issue resumes without another status write", async () => {
  const fixture = await explicitPlanningFixture();
  fixture.dependencies.fetchProjectIssues = async () => {
    fixture.calls.push("items");
    return [{ ...fixture.item, status: "In Progress", statusOptionId: "PROGRESS" }];
  };
  fixture.dependencies.startProjectWork = async () => {
    fixture.calls.push("start-read-only");
    return { kind: "already_in_progress" };
  };
  const result = await main(["--issue", fixture.item.url], fixture.dependencies);
  assert.equal(result.kind, "proposal_ready");
  assert.deepEqual(fixture.calls.slice(0, 7), ["preflight", "project", "items", "issue", "link-scan", "start-read-only", "codex"]);
});

test("declining linked reuse makes no status write or proposal", async () => {
  const fixture = await explicitPlanningFixture();
  fixture.dependencies.resolveLinkedChange = async () => {
    fixture.calls.push("link-scan");
    return { kind: "reuse", changeId: "existing", traceability: {
      projectId: "PROJECT", projectItemId: fixture.item.projectItemId,
      issueId: fixture.issue.id, repositoryId: fixture.issue.repository.id,
    } };
  };
  fixture.dependencies.confirmReuse = async () => false;
  const result = await main(["--issue", fixture.item.url], fixture.dependencies);
  assert.equal(result.kind, "cancelled");
  assert.deepEqual(fixture.calls, ["preflight", "project", "items", "issue", "link-scan"]);
});

test("accepted linked reuse confirms start before reporting proposal ready", async () => {
  const fixture = await explicitPlanningFixture();
  fixture.dependencies.resolveLinkedChange = async () => {
    fixture.calls.push("link-scan");
    return { kind: "reuse", changeId: "existing", traceability: {
      projectId: "PROJECT", projectItemId: fixture.item.projectItemId,
      issueId: fixture.issue.id, repositoryId: fixture.issue.repository.id,
    } };
  };
  fixture.dependencies.confirmReuse = async () => true;
  const result = await main(["--issue", fixture.item.url], fixture.dependencies);
  assert.equal(result.kind, "proposal_ready");
  assert.equal(result.reused, true);
  assert.deepEqual(fixture.calls, ["preflight", "project", "items", "issue", "link-scan", "start", "validate"]);
});

test("linked change for a different Project item fails before status change", async () => {
  const fixture = await explicitPlanningFixture();
  fixture.dependencies.resolveLinkedChange = async () => {
    fixture.calls.push("link-scan");
    return { kind: "reuse", changeId: "existing", traceability: {
      projectId: "PROJECT", projectItemId: "DIFFERENT",
      issueId: fixture.issue.id, repositoryId: fixture.issue.repository.id,
    } };
  };
  const result = await main(["--issue", fixture.item.url], fixture.dependencies);
  assert.equal(result.code, "link_disagreement");
  assert.deepEqual(fixture.calls, ["preflight", "project", "items", "issue", "link-scan"]);
});

test("required start failure stops before Codex and link persistence", async () => {
  const fixture = await explicitPlanningFixture();
  fixture.dependencies.startProjectWork = async () => {
    fixture.calls.push("start");
    throw new GitHubError("work_start_mutation_failed", "GitHub denied the update; retry the command.");
  };
  const result = await main(["--issue", fixture.item.url], fixture.dependencies);
  assert.equal(result.code, "work_start_mutation_failed");
  assert.match(fixture.errorOutput(), /retry the command/);
  assert.deepEqual(fixture.calls, ["preflight", "project", "items", "issue", "link-scan", "start"]);
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
        repository: "dotin2001/ai-marketing-report",
        status: "Todo",
        statusOptionId: "TODO",
      },
      {
        projectItemId: "ITEM_2_DUPLICATE",
        issueId: "ISSUE_2",
        issueNumber: 2,
        repository: "dotin2001/ai-marketing-report",
        status: "Todo",
        statusOptionId: "TODO",
      },
    ],
    "explicit_issue_ambiguous",
  ],
]) {
  test(`${name} explicit Project resolution stops before issue loading or Codex`, async () => {
    const fixture = await explicitPlanningFixture({ items });
    const result = await main(
      ["--issue", "https://github.com/dotin2001/ai-marketing-report/issues/2"],
      fixture.dependencies,
    );
    assert.equal(result.code, code);
    assert.deepEqual(fixture.calls, ["preflight", "project", "items"]);
    for (const prohibited of ["selector", "issue", "link-scan", "codex", "validate", "mutation"]) {
      assert.equal(fixture.calls.includes(prohibited), false);
    }
  });
}
