import assert from "node:assert/strict";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import { validateProposalOutput } from "../openspec.mjs";
import { createTraceability, serializeTraceabilityMarker } from "../traceability.mjs";

const identity = createTraceability({
  repository: "owner/repo",
  repositoryId: "REPO",
  projectOwner: "owner",
  projectNumber: 2,
  projectId: "PROJECT",
  projectItemId: "ITEM",
  issueId: "ISSUE",
  issueNumber: 42,
  branch: "feature/test",
  baseCommit: "a".repeat(40),
  changeId: "gh-42-example",
});

async function fixture() {
  const root = await mkdtemp(path.join(os.tmpdir(), "ai-local-proposal-"));
  const changeRoot = path.join(root, "openspec", "changes", identity.changeId);
  await mkdir(path.join(changeRoot, "specs", "capability"), { recursive: true });
  await writeFile(
    path.join(changeRoot, "proposal.md"),
    `# Proposal\n## Traceability\n${serializeTraceabilityMarker(identity)}\n`,
  );
  await writeFile(path.join(changeRoot, "design.md"), "# Design\nComplete decisions.\n");
  await writeFile(
    path.join(changeRoot, "specs", "capability", "spec.md"),
    "## ADDED Requirements\n### Requirement: Behavior\nThe tool SHALL work.\n#### Scenario: Works\n- **WHEN** used\n- **THEN** it works\n",
  );
  await writeFile(
    path.join(changeRoot, "tasks.md"),
    "- [ ] 1.1 Implement behavior and verify it with tests.\n",
  );
  return { root, changeRoot };
}

function validationRunner(value = { valid: true }) {
  return async (command, args) => {
    assert.equal(command, "openspec");
    assert.deepEqual(args, ["validate", identity.changeId, "--strict", "--json"]);
    return { exitCode: 0, timedOut: false, stdout: JSON.stringify(value), stderr: "" };
  };
}

test("independently accepts complete, linked, strictly valid proposal output", async () => {
  const { root } = await fixture();
  const result = await validateProposalOutput({
    repositoryRoot: root,
    changeId: identity.changeId,
    expectedTraceability: identity,
    runCommand: validationRunner(),
  });
  assert.equal(result.traceability.issueId, "ISSUE");
  assert.equal(result.artifactPaths.length, 4);
});

test("rejects zero-exit Codex output with missing or incomplete artifacts", async () => {
  const missing = await fixture();
  await writeFile(path.join(missing.changeRoot, "design.md"), "");
  await assert.rejects(
    () =>
      validateProposalOutput({
        repositoryRoot: missing.root,
        changeId: identity.changeId,
        expectedTraceability: identity,
        runCommand: validationRunner(),
      }),
    (error) => error.code === "proposal_artifact_missing",
  );

  const incomplete = await fixture();
  await writeFile(path.join(incomplete.changeRoot, "tasks.md"), "- [ ] Implement someday.\n");
  await assert.rejects(
    () =>
      validateProposalOutput({
        repositoryRoot: incomplete.root,
        changeId: identity.changeId,
        expectedTraceability: identity,
        runCommand: validationRunner(),
      }),
    (error) => error.code === "proposal_artifact_incomplete",
  );
});

test("rejects wrong linkage and failed strict validation", async () => {
  const wrong = await fixture();
  await assert.rejects(
    () =>
      validateProposalOutput({
        repositoryRoot: wrong.root,
        changeId: identity.changeId,
        expectedTraceability: { ...identity, issueId: "OTHER" },
        runCommand: validationRunner(),
      }),
    (error) => error.code === "traceability_mismatch",
  );

  const invalid = await fixture();
  await assert.rejects(
    () =>
      validateProposalOutput({
        repositoryRoot: invalid.root,
        changeId: identity.changeId,
        expectedTraceability: identity,
        runCommand: validationRunner({ valid: false, errors: ["bad"] }),
      }),
    (error) => error.code === "openspec_validation_failed",
  );
});
