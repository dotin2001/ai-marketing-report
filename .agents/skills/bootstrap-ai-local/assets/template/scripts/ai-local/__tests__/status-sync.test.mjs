import assert from "node:assert/strict";
import test from "node:test";

import { fetchProjectItem, statusSyncQueries, synchronizeProjectStatus } from "../status-sync.mjs";

const project = {
  id: "P", statusField: { id: "F", name: "Status" }, doneOption: { id: "DONE", name: "Done" },
};
const guarded = {
  kind: "ReadyStatusMutation", projectId: "P", projectItemId: "PI", statusFieldId: "F",
  doneOptionId: "DONE", doneName: "Done",
};

function item(status = "Done", optionId = "DONE") {
  return {
    node: {
      id: "PI", updatedAt: "2026-11-10T00:00:00Z", status: { name: status, optionId },
      content: {
        __typename: "Issue", id: "I", number: 7, title: "Task", url: "https://example.test/7",
        updatedAt: "2026-11-10T00:00:00Z",
        repository: { id: "R", nameWithOwner: "owner/repo", isFork: false },
      },
    },
  };
}

test("single selected item Status mutation is followed by a confirming read", async () => {
  const operations = [];
  const client = {
    graphql: async (query, variables) => {
      operations.push({ query, variables });
      if (query === statusSyncQueries.updateStatus) {
        return { updateProjectV2ItemFieldValue: { projectV2Item: { id: "PI" } } };
      }
      return item();
    },
  };
  const result = await synchronizeProjectStatus(client, guarded, project);
  assert.equal(result.confirmedStatus, "Done");
  assert.equal(operations.length, 2);
  assert.deepEqual(operations[0].variables, { projectId: "P", itemId: "PI", fieldId: "F", optionId: "DONE" });
  assert.match(operations[0].query, /updateProjectV2ItemFieldValue/);
  assert.doesNotMatch(operations.map(({ query }) => query).join("\n"), /closeIssue|updateIssue/);
  assert.equal(operations.filter(({ query }) => query.includes("mutation ")).length, 1);
});

test("item read returns the live linkage and status", async () => {
  const result = await fetchProjectItem({ graphql: async () => item("Todo", "TODO") }, project, "PI");
  assert.equal(result.projectId, "P");
  assert.equal(result.issueId, "I");
  assert.equal(result.status, "Todo");
});

test("mutation response failure is accurately typed", async () => {
  const client = { graphql: async () => ({ updateProjectV2ItemFieldValue: { projectV2Item: null } }) };
  await assert.rejects(synchronizeProjectStatus(client, guarded, project), (error) => error.code === "status_mutation_failed");
});

test("failed Done confirmation is accurately typed", async () => {
  let call = 0;
  const client = {
    graphql: async () => {
      call += 1;
      return call === 1
        ? { updateProjectV2ItemFieldValue: { projectV2Item: { id: "PI" } } }
        : item("Todo", "TODO");
    },
  };
  await assert.rejects(
    synchronizeProjectStatus(client, guarded, project),
    (error) => error.code === "status_confirmation_failed" && error.details.actualStatus === "Todo",
  );
});

test("unguarded calls cannot reach GitHub", async () => {
  let calls = 0;
  await assert.rejects(
    synchronizeProjectStatus({ graphql: async () => { calls += 1; } }, {}, project),
    (error) => error.code === "mutation_guard_missing",
  );
  assert.equal(calls, 0);
});
