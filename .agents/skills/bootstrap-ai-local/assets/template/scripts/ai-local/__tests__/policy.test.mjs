import assert from "node:assert/strict";
import test from "node:test";

import { assertAllowedGraphQL, assertAllowedWorkflowCommand, createPolicyTransport } from "../policy.mjs";
import { statusSyncQueries } from "../status-sync.mjs";

for (const [command, args] of [
  ["git", ["commit", "-m", "no"]],
  ["git", ["push", "origin", "main"]],
  ["git", ["merge", "other"]],
  ["git", ["checkout", "other"]],
  ["git", ["switch", "other"]],
  ["git", ["reset", "--hard"]],
  ["git", ["clean", "-fd"]],
  ["npm", ["run", "deploy"]],
  ["npm", ["publish"]],
  ["npm", ["run", "ai:local"]],
  ["gh", ["issue", "close", "7"]],
  ["gh", ["pr", "merge", "8"]],
  ["openspec", ["apply", "change"]],
  ["rm", ["-rf", "work"]],
]) {
  test(`process policy rejects ${command} ${args.join(" ")}`, () => {
    assert.throws(() => assertAllowedWorkflowCommand(command, args), (error) => error.code === "process_error");
  });
}

test("process spy sees safe read/check commands and blocks prohibited commands before transport", async () => {
  const calls = [];
  const transport = createPolicyTransport(async (command, args) => {
    calls.push([command, args]);
    return { exitCode: 0, stdout: "", stderr: "", timedOut: false };
  });
  await transport("git", ["rev-parse", "HEAD"], {});
  await transport("npm", ["test"], {});
  await assert.rejects(transport("git", ["push"], {}), (error) => error.code === "process_error");
  assert.deepEqual(calls, [["git", ["rev-parse", "HEAD"]], ["npm", ["test"]]]);
});

test("GraphQL policy allows the sole selected-item Status mutation", () => {
  assert.doesNotThrow(() => assertAllowedGraphQL(statusSyncQueries.updateStatus));
  assert.doesNotThrow(() => assertAllowedGraphQL("query ReadOnly { viewer { login } }"));
});

for (const mutation of [
  "mutation Bad { closeIssue(input: {issueId: \"I\"}) { issue { id } } }",
  "mutation Bad { updateIssue(input: {id: \"I\"}) { issue { id } } }",
  "mutation Bad { deleteProjectV2Item(input: {projectId: \"P\", itemId: \"PI\"}) { deletedItemId } }",
  "mutation Bad { a:updateProjectV2ItemFieldValue(input:{}){clientMutationId} b:updateProjectV2ItemFieldValue(input:{}){clientMutationId} }",
]) {
  test("GraphQL policy rejects issue close or non-single-item mutation", () => {
    assert.throws(() => assertAllowedGraphQL(mutation), (error) => error.code === "process_error");
  });
}
