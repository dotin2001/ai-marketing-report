import assert from "node:assert/strict";
import { test } from "node:test";

import { assertLiveIdentity } from "../identity.mjs";

const base = {
  traceability: {
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
    changeId: "gh-42-test",
  },
  changeId: "gh-42-test",
  config: { github: { repository: "owner/repo" } },
  preflight: { repository: "owner/repo", branch: "feature/test", head: "b".repeat(40) },
  project: { ownerLogin: "owner", number: 2, id: "PROJECT" },
  item: {
    projectId: "PROJECT",
    projectItemId: "ITEM",
    issueId: "ISSUE",
    issueNumber: 42,
    repository: "owner/repo",
    repositoryId: "REPO",
    status: "Todo",
  },
  issue: {
    id: "ISSUE",
    number: 42,
    repository: { id: "REPO", nameWithOwner: "owner/repo" },
  },
};

test("accepts matching recorded and live identities", () => {
  const identity = assertLiveIdentity(structuredClone(base));
  assert.equal(identity.head, "b".repeat(40));
  assert.equal(identity.projectItemId, "ITEM");
});

for (const [name, mutate] of [
  ["change", (value) => (value.changeId = "gh-42-other")],
  ["configured repository", (value) => (value.config.github.repository = "other/repo")],
  ["Git remote", (value) => (value.preflight.repository = "other/repo")],
  ["branch", (value) => (value.preflight.branch = "feature/other")],
  ["Project owner", (value) => (value.project.ownerLogin = "other")],
  ["Project number", (value) => (value.project.number = 3)],
  ["Project id", (value) => (value.project.id = "OTHER_PROJECT")],
  ["Project item", (value) => (value.item.projectItemId = "OTHER_ITEM")],
  ["item Project", (value) => (value.item.projectId = "OTHER_PROJECT")],
  ["item-to-issue linkage", (value) => (value.item.issueId = "OTHER_ISSUE")],
  ["item issue number", (value) => (value.item.issueNumber = 43)],
  ["item repository", (value) => (value.item.repository = "other/repo")],
  ["item repository id", (value) => (value.item.repositoryId = "OTHER_REPO")],
  ["issue id", (value) => (value.issue.id = "OTHER_ISSUE")],
  ["issue number", (value) => (value.issue.number = 43)],
  ["issue repository", (value) => (value.issue.repository.nameWithOwner = "other/repo")],
  ["issue repository id", (value) => (value.issue.repository.id = "OTHER_REPO")],
]) {
  test(`${name} mismatch stops before checks or mutation`, () => {
    const value = structuredClone(base);
    mutate(value);
    let checks = false;
    let mutation = false;
    assert.throws(() => {
      assertLiveIdentity(value);
      checks = true;
      mutation = true;
    }, (error) => error.code === "identity_conflict");
    assert.equal(checks, false);
    assert.equal(mutation, false);
  });
}
