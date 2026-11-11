import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { createEvidenceRecord, persistEvidence } from "../evidence.mjs";
import { findReusableEvidence, resolveVerificationAttempt } from "../retry.mjs";

function inputs(overrides = {}) {
  return {
    identities: {
      repository: "example-owner/example-repo",
      branch: "feature/set_up",
      issueId: "I_1",
      projectId: "P_1",
      projectItemId: "PI_1",
      changeId: "change-1",
      ...overrides.identities,
    },
    fingerprints: {
      identity: "identity",
      worktree: "worktree",
      specifications: "specifications",
      issueRequirements: "issue",
      requiredChecks: "checks",
      ...overrides.fingerprints,
    },
  };
}

async function fixture() {
  const root = await mkdtemp(path.join(os.tmpdir(), "ai-local-retry-"));
  const runtimePaths = { evidence: path.join(root, "evidence") };
  const current = inputs();
  const record = createEvidenceRecord({
    attemptId: "attempt-1",
    changeId: "change-1",
    recordedAt: "2026-11-10T01:02:03.000Z",
    ...current,
    criterionResults: [],
    commandResults: [],
    verificationState: "passed",
    synchronization: { state: "failed", errorCode: "github_failed" },
  });
  await persistEvidence(runtimePaths, record);
  return { runtimePaths, current };
}

test("unchanged failed synchronization evidence is reusable and repeats the live check", async () => {
  const { runtimePaths, current } = await fixture();
  let verified = 0;
  let liveChecks = 0;
  const result = await resolveVerificationAttempt({
    runtimePaths,
    changeId: "change-1",
    ...current,
    verifyFresh: async () => { verified += 1; },
    finalLiveCheck: async ({ reused }) => {
      liveChecks += 1;
      assert.equal(reused, true);
      return { status: "Todo" };
    },
  });
  assert.equal(result.kind, "reuse");
  assert.equal(result.live.status, "Todo");
  assert.equal(verified, 0);
  assert.equal(liveChecks, 1);
});

test("evidence is not reused unless verification passed and synchronization failed", async () => {
  const { runtimePaths, current } = await fixture();
  const changedState = await findReusableEvidence({
    runtimePaths,
    changeId: "change-1",
    identities: current.identities,
    fingerprints: current.fingerprints,
  });
  assert.equal(changedState.kind, "reuse");

  const noRecord = await findReusableEvidence({
    runtimePaths,
    changeId: "other-change",
    identities: current.identities,
    fingerprints: current.fingerprints,
  });
  assert.equal(noRecord.kind, "fresh");
});

test("every identity and fingerprint input forces fresh verification when changed", async () => {
  const { runtimePaths, current } = await fixture();
  const identityChanges = [
    ["branch", "other"],
    ["issueId", "I_2"],
    ["projectItemId", "PI_2"],
    ["changeId", "change-2"],
  ];
  for (const [field, value] of identityChanges) {
    const result = await findReusableEvidence({
      runtimePaths,
      changeId: "change-1",
      identities: { ...current.identities, [field]: value },
      fingerprints: current.fingerprints,
    });
    assert.equal(result.kind, "fresh", `identity ${field}`);
  }

  const fingerprintChanges = [
    ["worktree", "code-changed"],
    ["specifications", "spec-changed"],
    ["issueRequirements", "issue-or-comment-changed"],
    ["identity", "identity-changed"],
    ["requiredChecks", "check-changed"],
  ];
  for (const [field, value] of fingerprintChanges) {
    const result = await findReusableEvidence({
      runtimePaths,
      changeId: "change-1",
      identities: current.identities,
      fingerprints: { ...current.fingerprints, [field]: value },
    });
    assert.equal(result.kind, "fresh", `fingerprint ${field}`);
  }
});
