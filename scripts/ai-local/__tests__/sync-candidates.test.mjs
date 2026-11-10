import assert from "node:assert/strict";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import { atomicWriteJson, ensureRuntimeLayout } from "../runtime.mjs";
import {
  discoverSynchronizationCandidates,
  resolveSynchronizationCandidate,
} from "../sync-input.mjs";
import {
  createLinkRecord,
  createTraceability,
  serializeTraceabilityMarker,
} from "../traceability.mjs";

function identity(changeId, issueNumber = 1) {
  return createTraceability({
    repository: "owner/repo",
    repositoryId: "REPO",
    projectOwner: "owner",
    projectNumber: 2,
    projectId: "PROJECT",
    projectItemId: `ITEM-${issueNumber}`,
    issueId: `ISSUE-${issueNumber}`,
    issueNumber,
    branch: "feature/test",
    baseCommit: "a".repeat(40),
    changeId,
  });
}

async function fixture() {
  const repositoryRoot = await mkdtemp(path.join(os.tmpdir(), "ai-local-sync-candidates-"));
  const runtimePaths = await ensureRuntimeLayout(path.join(repositoryRoot, ".ai-local"));
  await mkdir(path.join(repositoryRoot, "openspec", "changes"), { recursive: true });
  return { repositoryRoot, runtimePaths };
}

async function addCandidate(context, traceability, archived = false, record = traceability) {
  const root = archived
    ? path.join(context.repositoryRoot, "openspec", "changes", "archive", traceability.changeId)
    : path.join(context.repositoryRoot, "openspec", "changes", traceability.changeId);
  await mkdir(root, { recursive: true });
  await writeFile(path.join(root, "proposal.md"), serializeTraceabilityMarker(traceability));
  await atomicWriteJson(
    path.join(context.runtimePaths.links, `${traceability.changeId}.json`),
    createLinkRecord(record),
  );
}

test("resolves an explicit or sole valid active candidate", async () => {
  const context = await fixture();
  await addCandidate(context, identity("gh-1-one"));
  const candidates = await discoverSynchronizationCandidates(context);
  const explicit = await resolveSynchronizationCandidate({
    candidates,
    explicitChangeId: "gh-1-one",
    output: { write: () => {} },
  });
  assert.equal(explicit.candidate.changeId, "gh-1-one");
  const sole = await resolveSynchronizationCandidate({ candidates, output: { write: () => {} } });
  assert.equal(sole.candidate.changeId, "gh-1-one");
});

test("handles zero and multiple candidates with safe selection", async () => {
  const empty = await fixture();
  const none = await resolveSynchronizationCandidate({
    candidates: await discoverSynchronizationCandidates(empty),
    output: { write: () => {} },
  });
  assert.equal(none.kind, "no_candidate");

  const multiple = await fixture();
  await addCandidate(multiple, identity("gh-1-one", 1));
  await addCandidate(multiple, identity("gh-2-two", 2));
  const candidates = await discoverSynchronizationCandidates(multiple);
  const answers = ["bad", "2"];
  let index = 0;
  const selected = await resolveSynchronizationCandidate({
    candidates,
    prompt: { ask: async () => answers[index++] },
    output: { write: () => {} },
  });
  assert.equal(selected.candidate.changeId, "gh-2-two");
});

test("rejects invalid, archived, and mismatched candidates", async () => {
  const invalid = await fixture();
  const trace = identity("gh-1-invalid");
  const root = path.join(invalid.repositoryRoot, "openspec", "changes", trace.changeId);
  await mkdir(root, { recursive: true });
  await writeFile(path.join(root, "proposal.md"), "<!-- ai-local-trace:v1 {bad} -->");
  await assert.rejects(() => discoverSynchronizationCandidates(invalid), (error) =>
    error.code === "traceability_malformed",
  );

  const archived = await fixture();
  await addCandidate(archived, identity("gh-1-archived"), true);
  const archivedCandidates = await discoverSynchronizationCandidates(archived);
  await assert.rejects(
    () =>
      resolveSynchronizationCandidate({
        candidates: archivedCandidates,
        explicitChangeId: "gh-1-archived",
        output: { write: () => {} },
      }),
    (error) => error.code === "link_archived",
  );

  const mismatch = await fixture();
  await addCandidate(
    mismatch,
    identity("gh-1-mismatch"),
    false,
    createTraceability({ ...identity("gh-1-mismatch"), projectItemId: "OTHER" }),
  );
  await assert.rejects(() => discoverSynchronizationCandidates(mismatch), (error) =>
    error.code === "link_disagreement",
  );
});
