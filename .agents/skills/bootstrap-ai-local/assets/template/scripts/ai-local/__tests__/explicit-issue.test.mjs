import assert from "node:assert/strict";
import { test } from "node:test";

import {
  assertConfiguredRepository,
  parseGitHubIssueUrl,
  resolveExplicitIssue,
} from "../explicit-issue.mjs";

test("parses canonical GitHub issue URLs with an optional trailing slash", () => {
  const target = parseGitHubIssueUrl("https://github.com/Example-owner/example-repo/issues/2/");
  assert.deepEqual(target, {
    url: "https://github.com/Example-owner/example-repo/issues/2/",
    repository: "Example-owner/example-repo",
    issueNumber: 2,
  });
  assert.deepEqual(assertConfiguredRepository(target, "example-owner/example-repo"), {
    ...target,
    repository: "example-owner/example-repo",
  });
  assert.equal(Object.isFrozen(target), true);
});

for (const [name, value] of [
  ["malformed URL", "not-a-url"],
  ["HTTP", "http://github.com/o/r/issues/1"],
  ["other host", "https://example.com/o/r/issues/1"],
  ["credentials", "https://user:pass@github.com/o/r/issues/1"],
  ["non-default port", "https://github.com:444/o/r/issues/1"],
  ["query", "https://github.com/o/r/issues/1?x=1"],
  ["fragment", "https://github.com/o/r/issues/1#note"],
  ["pull request path", "https://github.com/o/r/pull/1"],
  ["extra path", "https://github.com/o/r/issues/1/files"],
  ["zero issue", "https://github.com/o/r/issues/0"],
  ["negative issue", "https://github.com/o/r/issues/-1"],
  ["non-numeric issue", "https://github.com/o/r/issues/one"],
  ["encoded owner", "https://github.com/%6f/r/issues/1"],
  ["malformed encoding", "https://github.com/%/r/issues/1"],
]) {
  test(`rejects ${name}`, () => {
    assert.throws(() => parseGitHubIssueUrl(value), (error) => error.code === "invalid_arguments");
  });
}

test("rejects a repository other than the configured repository", () => {
  const target = parseGitHubIssueUrl("https://github.com/other/repo/issues/2");
  assert.throws(
    () => assertConfiguredRepository(target, "example-owner/example-repo"),
    (error) =>
      error.code === "invalid_arguments" &&
      error.details.supplied === "other/repo" &&
      error.details.configured === "example-owner/example-repo",
  );
});

const eligible = Object.freeze({
  projectItemId: "ITEM",
  issueId: "ISSUE",
  issueNumber: 2,
  repository: "example-owner/example-repo",
  status: "Todo",
});

test("resolves exactly one matching eligible Project item", () => {
  const selection = resolveExplicitIssue([eligible], {
    repository: "EXAMPLE-OWNER/EXAMPLE-REPO",
    issueNumber: 2,
  });
  assert.equal(selection.kind, "selected");
  assert.equal(selection.item, eligible);
});

test("rejects an absent or ineligible Project item", () => {
  assert.throws(
    () => resolveExplicitIssue([], { repository: eligible.repository, issueNumber: 2 }),
    (error) => error.code === "explicit_issue_not_eligible",
  );
  assert.throws(
    () => resolveExplicitIssue([{ ...eligible, status: "In Progress" }], {
      repository: eligible.repository,
      issueNumber: 2,
    }),
    (error) => error.code === "explicit_issue_not_eligible",
  );
});

test("rejects duplicate matching Project items", () => {
  assert.throws(
    () => resolveExplicitIssue([eligible, { ...eligible, projectItemId: "ITEM_2" }], {
      repository: eligible.repository,
      issueNumber: 2,
    }),
    (error) => error.code === "explicit_issue_ambiguous",
  );
});
