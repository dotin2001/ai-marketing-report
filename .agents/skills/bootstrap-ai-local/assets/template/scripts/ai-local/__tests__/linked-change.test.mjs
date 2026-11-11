import assert from "node:assert/strict";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import { generateChangeId, resolveLinkedChange } from "../openspec.mjs";
import { atomicWriteJson, ensureRuntimeLayout } from "../runtime.mjs";
import {
  createLinkRecord,
  createTraceability,
  serializeTraceabilityMarker,
} from "../traceability.mjs";

const baseIdentity = {
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
};

async function fixture() {
  const repositoryRoot = await mkdtemp(path.join(os.tmpdir(), "ai-local-linked-"));
  await mkdir(path.join(repositoryRoot, "openspec", "changes"), { recursive: true });
  const runtimePaths = await ensureRuntimeLayout(path.join(repositoryRoot, ".ai-local"));
  return { repositoryRoot, runtimePaths };
}

async function writeProposal(root, identity, { archived = false } = {}) {
  const changeRoot = archived
    ? path.join(root, "openspec", "changes", "archive", identity.changeId)
    : path.join(root, "openspec", "changes", identity.changeId);
  await mkdir(changeRoot, { recursive: true });
  await writeFile(
    path.join(changeRoot, "proposal.md"),
    `# Proposal\n${serializeTraceabilityMarker(createTraceability(identity))}\n`,
  );
}

test("returns no link when no proposal or record exists", async () => {
  const context = await fixture();
  assert.deepEqual(
    await resolveLinkedChange({ ...context, expected: { repository: "owner/repo", issueId: "ISSUE" } }),
    { kind: "none" },
  );
});

test("reuses one active internally consistent link", async () => {
  const context = await fixture();
  const identity = createTraceability(baseIdentity);
  await writeProposal(context.repositoryRoot, identity);
  await atomicWriteJson(
    path.join(context.runtimePaths.links, `${identity.changeId}.json`),
    createLinkRecord(identity),
  );
  const result = await resolveLinkedChange({
    ...context,
    expected: { repository: "owner/repo", issueId: "ISSUE" },
  });
  assert.equal(result.kind, "reuse");
  assert.equal(result.changeId, "gh-42-example");
});

test("rejects archived links", async () => {
  const context = await fixture();
  await writeProposal(context.repositoryRoot, createTraceability(baseIdentity), { archived: true });
  await assert.rejects(
    () => resolveLinkedChange({ ...context, expected: { repository: "owner/repo", issueId: "ISSUE" } }),
    (error) => error.code === "link_archived",
  );
});

test("rejects multiple candidates and record-marker disagreement", async () => {
  const multiple = await fixture();
  await writeProposal(multiple.repositoryRoot, createTraceability(baseIdentity));
  await writeProposal(
    multiple.repositoryRoot,
    createTraceability({ ...baseIdentity, changeId: "gh-42-second" }),
  );
  await assert.rejects(
    () => resolveLinkedChange({ ...multiple, expected: { repository: "owner/repo", issueId: "ISSUE" } }),
    (error) => error.code === "link_ambiguous",
  );

  const disagreement = await fixture();
  const marker = createTraceability(baseIdentity);
  await writeProposal(disagreement.repositoryRoot, marker);
  const badRecord = createLinkRecord(createTraceability({ ...baseIdentity, projectItemId: "OTHER" }));
  await atomicWriteJson(
    path.join(disagreement.runtimePaths.links, `${marker.changeId}.json`),
    badRecord,
  );
  await assert.rejects(
    () => resolveLinkedChange({ ...disagreement, expected: { repository: "owner/repo", issueId: "ISSUE" } }),
    (error) => error.code === "link_disagreement",
  );
});

test("generates deterministic collision-safe IDs for unrelated directories", async () => {
  const context = await fixture();
  const first = await generateChangeId({
    repositoryRoot: context.repositoryRoot,
    issueNumber: 42,
    issueId: "ISSUE",
    title: "Example Workflow",
  });
  assert.equal(first, "gh-42-example-workflow");
  await mkdir(path.join(context.repositoryRoot, "openspec", "changes", first));
  const collisionSafe = await generateChangeId({
    repositoryRoot: context.repositoryRoot,
    issueNumber: 42,
    issueId: "ISSUE",
    title: "Example Workflow",
  });
  assert.match(collisionSafe, /^gh-42-example-workflow-[0-9a-f]{8}$/);
  assert.equal(
    collisionSafe,
    await generateChangeId({
      repositoryRoot: context.repositoryRoot,
      issueNumber: 42,
      issueId: "ISSUE",
      title: "Example Workflow",
    }),
  );
});
