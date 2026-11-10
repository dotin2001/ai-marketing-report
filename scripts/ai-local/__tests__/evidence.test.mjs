import assert from "node:assert/strict";
import { mkdtemp, readFile, stat } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import { createEvidenceRecord, listEvidence, persistEvidence } from "../evidence.mjs";
import { ensureRuntimeLayout } from "../runtime.mjs";

function record(overrides = {}) {
  return createEvidenceRecord({
    attemptId: "attempt-1",
    changeId: "gh-42-test",
    recordedAt: "2026-01-01T00:00:00.000Z",
    identities: { repository: "owner/repo", issueId: "ISSUE", projectItemId: "ITEM" },
    criterionResults: [{ id: "issue:1", verdict: "failed", evidence: ["src/file"], commandEvidenceIds: [] }],
    commandResults: [
      {
        checkId: "check:1",
        command: "npm",
        args: ["test"],
        state: "failed",
        exitCode: 1,
        durationMs: 1,
        stdout: "gho_abcdefghijklmnopqrstuvwxyz",
        stderr: "failed",
      },
    ],
    fingerprints: {
      identity: "a",
      worktree: "b",
      specifications: "c",
      issueRequirements: "d",
      requiredChecks: "e",
    },
    toolVersions: { node: "22" },
    verificationState: "failed",
    synchronization: { state: "not_attempted" },
    ...overrides,
  });
}

test("atomic append-only evidence retains failed attempts and redacts credentials", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "ai-local-evidence-"));
  const runtimePaths = await ensureRuntimeLayout(path.join(root, ".ai-local"));
  const first = record();
  const firstPath = await persistEvidence(runtimePaths, first);
  const secondPath = await persistEvidence(
    runtimePaths,
    record({ attemptId: "attempt-2", recordedAt: "2026-01-01T00:01:00.000Z" }),
  );
  assert.notEqual(firstPath, secondPath);
  assert.equal((await listEvidence(runtimePaths, "gh-42-test")).length, 2);
  const content = await readFile(firstPath, "utf8");
  assert.doesNotMatch(content, /gho_abcdefghijklmnopqrstuvwxyz/);
  assert.match(content, /\[REDACTED\]/);
  assert.equal((await stat(firstPath)).mode & 0o777, 0o600);
  const parsed = JSON.parse(content);
  assert.equal(parsed.verification.state, "failed");
  assert.equal("body" in parsed, false);
  assert.equal("comments" in parsed, false);
  assert.equal("prompt" in parsed, false);
});

test("evidence records never overwrite an earlier attempt", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "ai-local-evidence-append-"));
  const runtimePaths = await ensureRuntimeLayout(path.join(root, ".ai-local"));
  const value = record();
  const destination = await persistEvidence(runtimePaths, value);
  const before = await readFile(destination, "utf8");
  await assert.rejects(() => persistEvidence(runtimePaths, value), (error) => error.code === "evidence_exists");
  assert.equal(await readFile(destination, "utf8"), before);
});
