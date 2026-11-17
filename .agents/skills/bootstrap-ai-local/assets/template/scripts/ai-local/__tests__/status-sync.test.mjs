import assert from "node:assert/strict";
import test from "node:test";

import { fetchProjectItem, startProjectWork, statusSyncQueries, synchronizeProjectStatus } from "../status-sync.mjs";

const project = {
  id: "P", statusField: { id: "F", name: "Status" }, doneOption: { id: "DONE", name: "Done" },
};
const guarded = {
  kind: "ReadyStatusMutation", projectId: "P", projectItemId: "PI", statusFieldId: "F",
  doneOptionId: "DONE", doneName: "Done",
};
const workProject = {
  ...project,
  todoOption: { id: "TODO", name: "Todo" },
  inProgressOption: { id: "PROGRESS", name: "In Progress" },
};
const selected = {
  projectItemId: "PI", issueId: "I", issueNumber: 7,
  repository: "owner/repo", repositoryId: "R",
};
const issue = { id: "I", number: 7, repository: { id: "R", nameWithOwner: "owner/repo" } };

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

test("Todo start writes only the selected item and confirms In Progress", async () => {
  const calls = [];
  const client = { graphql: async (query, variables) => {
    calls.push({ query, variables });
    if (query === statusSyncQueries.updateStatus) {
      return { updateProjectV2ItemFieldValue: { projectV2Item: { id: "PI" } } };
    }
    return item(calls.some((call) => call.query === statusSyncQueries.updateStatus) ? "In Progress" : "Todo", calls.some((call) => call.query === statusSyncQueries.updateStatus) ? "PROGRESS" : "TODO");
  } };
  const result = await startProjectWork(client, workProject, selected, issue);
  assert.equal(result.kind, "started");
  assert.equal(calls.length, 3);
  assert.deepEqual(calls[1].variables, { projectId: "P", itemId: "PI", fieldId: "F", optionId: "PROGRESS" });
});

test("already In Progress start is read-only", async () => {
  let writes = 0;
  const client = { graphql: async (query) => {
    if (query === statusSyncQueries.updateStatus) writes += 1;
    return item("In Progress", "PROGRESS");
  } };
  assert.equal((await startProjectWork(client, workProject, selected, issue)).kind, "already_in_progress");
  assert.equal(writes, 0);
});

test("changed status or issue linkage stops before start mutation", async () => {
  for (const response of [item("Done", "DONE"), { node: { ...item("Todo", "TODO").node, content: { ...item().node.content, id: "OTHER" } } }]) {
    let writes = 0;
    const client = { graphql: async (query) => {
      if (query === statusSyncQueries.updateStatus) writes += 1;
      return response;
    } };
    await assert.rejects(startProjectWork(client, workProject, selected, issue));
    assert.equal(writes, 0);
  }
});

test("start mutation and confirmation failures are typed, sanitized, and retryable", async () => {
  for (const mutation of [async () => { throw new Error("secret provider body"); }, async () => ({ updateProjectV2ItemFieldValue: { projectV2Item: null } })]) {
    let reads = 0;
    const client = { graphql: async (query) => {
      if (query === statusSyncQueries.updateStatus) return mutation();
      reads += 1;
      return item("Todo", "TODO");
    } };
    await assert.rejects(startProjectWork(client, workProject, selected, issue), (error) =>
      error.code === "work_start_mutation_failed" && /retry/i.test(error.message) && !/secret/.test(error.message));
    assert.equal(reads, 1);
  }
  const client = { graphql: async (query) => query === statusSyncQueries.updateStatus
    ? { updateProjectV2ItemFieldValue: { projectV2Item: { id: "PI" } } }
    : item("Todo", "TODO") };
  await assert.rejects(startProjectWork(client, workProject, selected, issue), (error) =>
    error.code === "work_start_confirmation_failed" && /Retry/.test(error.message));
});

test("uncertain confirmed write is recovered by a read-only retry", async () => {
  let status = "Todo";
  let writes = 0;
  let failConfirmation = true;
  const client = { graphql: async (query) => {
    if (query === statusSyncQueries.updateStatus) {
      writes += 1;
      status = "In Progress";
      return { updateProjectV2ItemFieldValue: { projectV2Item: { id: "PI" } } };
    }
    if (status === "In Progress" && failConfirmation) {
      failConfirmation = false;
      throw new Error("provider response unavailable");
    }
    return status === "Todo" ? item("Todo", "TODO") : item("In Progress", "PROGRESS");
  } };
  await assert.rejects(startProjectWork(client, workProject, selected, issue), (error) =>
    error.code === "work_start_confirmation_failed" && !/provider/.test(error.message));
  const retry = await startProjectWork(client, workProject, selected, issue);
  assert.equal(retry.kind, "already_in_progress");
  assert.equal(writes, 1);
});
