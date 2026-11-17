import assert from "node:assert/strict";
import test from "node:test";

import { executeAfterFinalGuard, prepareStatusMutation } from "../guard.mjs";

const fingerprints = {
  identity: "a",
  worktree: "b",
  specifications: "c",
  issueRequirements: "d",
  requiredChecks: "e",
};

function options(status = "Todo") {
  return {
    verification: { kind: "VerifiedSynchronization" },
    verifiedFingerprints: fingerprints,
    currentFingerprints: { ...fingerprints },
    todoName: "Todo",
    inProgressName: "In Progress",
    doneName: "Done",
    identityInput: {
      traceability: {
        repository: "owner/repo", repositoryId: "R", projectOwner: "owner", projectNumber: 2,
        projectId: "P", projectItemId: "PI", issueId: "I", issueNumber: 7,
        branch: "feature/work", changeId: "change-7",
      },
      changeId: "change-7",
      config: { github: { repository: "owner/repo" } },
      preflight: { repository: "owner/repo", branch: "feature/work", head: "abc" },
      project: {
        ownerLogin: "owner", number: 2, id: "P",
        statusField: { id: "F" }, todoOption: { id: "TODO" },
        inProgressOption: { id: "PROGRESS" }, doneOption: { id: "DONE" },
      },
      item: {
        projectId: "P", projectItemId: "PI", issueId: "I", issueNumber: 7,
        repository: "owner/repo", repositoryId: "R", status,
        statusOptionId: status === "Todo" ? "TODO" : status === "In Progress" ? "PROGRESS" : "DONE",
      },
      issue: { id: "I", number: 7, repository: { id: "R", nameWithOwner: "owner/repo" } },
    },
  };
}

test("matching live Todo state produces a typed mutation token", () => {
  const result = prepareStatusMutation(options());
  assert.equal(result.kind, "ReadyStatusMutation");
  assert.deepEqual(
    { project: result.projectId, item: result.projectItemId, field: result.statusFieldId, option: result.doneOptionId },
    { project: "P", item: "PI", field: "F", option: "DONE" },
  );
});

test("matching live In Progress state produces the same verified Done token", () => {
  const result = prepareStatusMutation(options("In Progress"));
  assert.equal(result.kind, "ReadyStatusMutation");
  assert.equal(result.doneOptionId, "DONE");
});

test("In Progress with the wrong live option ID is a conflict", () => {
  const value = options("In Progress");
  value.identityInput.item.statusOptionId = "OTHER";
  assert.throws(() => prepareStatusMutation(value), (error) => error.code === "status_conflict");
});

test("changed fingerprints stop before mutation", async () => {
  const value = options();
  value.currentFingerprints.worktree = "changed";
  let mutations = 0;
  await assert.rejects(
    executeAfterFinalGuard(value, async () => { mutations += 1; }),
    (error) => error.code === "fingerprint_changed",
  );
  assert.equal(mutations, 0);
});

test("live linkage conflict stops before mutation", async () => {
  const value = options();
  value.identityInput.item.issueId = "OTHER";
  let mutations = 0;
  await assert.rejects(
    executeAfterFinalGuard(value, async () => { mutations += 1; }),
    (error) => error.code === "identity_conflict",
  );
  assert.equal(mutations, 0);
});

test("already Done is idempotent and never calls mutation", async () => {
  let mutations = 0;
  const result = await executeAfterFinalGuard(options("Done"), async () => { mutations += 1; });
  assert.equal(result.kind, "already_done");
  assert.equal(result.exitCode, 0);
  assert.equal(mutations, 0);
});

test("a conflicting status never calls mutation", async () => {
  let mutations = 0;
  await assert.rejects(
    executeAfterFinalGuard(options("In progress"), async () => { mutations += 1; }),
    (error) => error.code === "status_conflict",
  );
  assert.equal(mutations, 0);
});

test("untyped verification never calls mutation", async () => {
  const value = options();
  value.verification = { kind: "something-else" };
  let mutations = 0;
  await assert.rejects(
    executeAfterFinalGuard(value, async () => { mutations += 1; }),
    (error) => error.code === "verification_token_invalid",
  );
  assert.equal(mutations, 0);
});
