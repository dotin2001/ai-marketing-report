import assert from "node:assert/strict";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import { buildVerificationManifest } from "../verification.mjs";

async function fixture(tasks = "- [x] 1.1 Implement.\n- [x] 1.2 Verify with tests.\n") {
  const repositoryRoot = await mkdtemp(path.join(os.tmpdir(), "ai-local-manifest-"));
  const changeId = "gh-42-test";
  const changeRoot = path.join(repositoryRoot, "openspec", "changes", changeId);
  await mkdir(path.join(changeRoot, "specs", "one"), { recursive: true });
  await writeFile(path.join(changeRoot, "proposal.md"), "# Proposal\n");
  await writeFile(path.join(changeRoot, "design.md"), "# Design\n");
  await writeFile(path.join(changeRoot, "tasks.md"), tasks);
  await writeFile(
    path.join(changeRoot, "specs", "one", "spec.md"),
    "### Requirement: First behavior\nThe tool SHALL work.\n#### Scenario: Happy path\n- **WHEN** used\n- **THEN** works\n#### Scenario: Failure path\n- **WHEN** broken\n- **THEN** fails closed\n",
  );
  const issue = {
    id: "ISSUE",
    url: "https://example.test/issues/42",
    body: "# Request\n## Acceptance Criteria\n- [ ] First criterion\n- Second criterion\n## Notes\n- not a criterion\n",
  };
  return { repositoryRoot, changeId, changeRoot, issue };
}

test("canonical manifest enumerates every criterion, requirement, scenario, and checked task", async () => {
  const context = await fixture();
  const manifest = await buildVerificationManifest(context);
  assert.equal(manifest.criteria.length, 2);
  assert.deepEqual(
    manifest.criteria.map(({ id, text, source }) => ({ id, text, line: source.line })),
    [
      { id: "issue:1", text: "First criterion", line: 3 },
      { id: "issue:2", text: "Second criterion", line: 4 },
    ],
  );
  assert.deepEqual(
    manifest.requirements.map((entry) => entry.kind),
    ["requirement", "scenario", "scenario"],
  );
  assert.equal(manifest.tasks.length, 2);
  assert.equal(manifest.entries.length, 7);
  for (const entry of manifest.entries) assert.ok(entry.source);
});

test("fails closed for missing artifacts and malformed tasks", async () => {
  const missing = await fixture();
  await writeFile(path.join(missing.changeRoot, "design.md"), "");
  await assert.rejects(() => buildVerificationManifest(missing), (error) =>
    error.code === "verification_artifact_missing",
  );

  const malformed = await fixture("- [maybe] invalid\n");
  await assert.rejects(() => buildVerificationManifest(malformed), (error) =>
    error.code === "verification_artifact_malformed",
  );
});

test("fails closed when any required task is unchecked", async () => {
  const context = await fixture("- [x] Implement.\n- [ ] Run required verification.\n");
  await assert.rejects(() => buildVerificationManifest(context), (error) =>
    error.code === "incomplete_tasks",
  );
});

test("explicit CommonMark-indented acceptance criteria take precedence over request prose", async () => {
  const context = await fixture();
  context.issue.body = "Customer request prose.\n   ## Acceptance Criteria ##\n   - [ ] First explicit outcome\n   * Second explicit outcome\n## Notes\n- ignored\n";
  const manifest = await buildVerificationManifest(context);
  assert.deepEqual(
    manifest.criteria.map(({ id, text, source }) => ({ id, text, line: source.line })),
    [
      { id: "issue:1", text: "First explicit outcome", line: 3 },
      { id: "issue:2", text: "Second explicit outcome", line: 4 },
    ],
  );
  assert.equal(manifest.criteria.some(({ text }) => text.includes("Customer request prose")), false);
});

test("uses a complete trimmed natural-language issue body as one criterion", async () => {
  const context = await fixture();
  context.issue.body = "\n  Build the requested report workflow.\nPreserve its safety gates.\n\n";
  const manifest = await buildVerificationManifest(context);
  assert.deepEqual(
    manifest.criteria.map(({ id, kind, text, source }) => ({ id, kind, text, line: source.line })),
    [{
      id: "issue:request",
      kind: "issue_criterion",
      text: "Build the requested report workflow.\nPreserve its safety gates.",
      line: 2,
    }],
  );
  assert.equal(manifest.entries.length, 6);
});

test("fails closed when the issue request is empty", async () => {
  const context = await fixture();
  context.issue.body = " \n\t\n";
  await assert.rejects(() => buildVerificationManifest(context), (error) =>
    error.code === "issue_request_missing",
  );
});

test("fails closed instead of falling back from malformed explicit criteria", async () => {
  const context = await fixture();
  context.issue.body = "Customer request prose.\n## Acceptance Criteria\nDescribe success without a list.\n## Notes\n- not a criterion\n";
  await assert.rejects(() => buildVerificationManifest(context), (error) =>
    error.code === "acceptance_criteria_malformed",
  );
});
