import assert from "node:assert/strict";
import { test } from "node:test";

import { fetchEligibleItems } from "../project.mjs";

const config = {
  github: {
    repository: "dotin2001/ai-marketing-report",
    statusField: "Status",
    todoOption: "Todo",
  },
};
const project = { id: "PROJECT", todoOption: { id: "TODO" } };

function item(overrides = {}) {
  return {
    id: "ITEM-1",
    updatedAt: "2026-01-01T00:00:00Z",
    status: { optionId: "TODO", name: "Todo" },
    content: {
      __typename: "Issue",
      id: "ISSUE-1",
      number: 1,
      title: "Eligible",
      url: "https://github.com/dotin2001/ai-marketing-report/issues/1",
      updatedAt: "2026-01-01T00:00:00Z",
      repository: {
        id: "REPOSITORY",
        nameWithOwner: "dotin2001/ai-marketing-report",
        isFork: false,
      },
    },
    ...overrides,
  };
}

test("fetches every page and retains only exact eligible Todo issues", async () => {
  const eligibleSecondPage = item({
    id: "ITEM-2",
    content: { ...item().content, id: "ISSUE-2", number: 2, title: "Second" },
  });
  const nodes = [
    item(),
    item({ id: "PULL", content: { ...item().content, __typename: "PullRequest" } }),
    item({ id: "DRAFT", content: { __typename: "DraftIssue", title: "draft" } }),
    item({ id: "NO-STATUS", status: null }),
    item({ id: "DONE", status: { optionId: "DONE", name: "Done" } }),
    item({
      id: "OTHER-REPO",
      content: {
        ...item().content,
        repository: { ...item().content.repository, nameWithOwner: "dotin2001/other" },
      },
    }),
    item({
      id: "FORK",
      content: {
        ...item().content,
        repository: { ...item().content.repository, isFork: true },
      },
    }),
    item({ id: "CASE", status: { optionId: "TODO", name: "todo" } }),
    eligibleSecondPage,
  ];
  let paginationCalled = false;
  const client = {
    paginate: async ({ variables, getConnection }) => {
      paginationCalled = true;
      assert.deepEqual(variables, { projectId: "PROJECT", statusField: "Status" });
      assert.deepEqual(getConnection({ node: { items: { nodes: [] } } }), { nodes: [] });
      return nodes;
    },
  };

  const eligible = await fetchEligibleItems(client, project, config);
  assert.equal(paginationCalled, true);
  assert.deepEqual(
    eligible.map((entry) => entry.projectItemId),
    ["ITEM-1", "ITEM-2"],
  );
  assert.equal(eligible[1].issueNumber, 2);
  assert.equal(eligible[1].repository, "dotin2001/ai-marketing-report");
});
