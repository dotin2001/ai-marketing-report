import assert from "node:assert/strict";
import { test } from "node:test";

import { ProcessError } from "../errors.mjs";
import { buildGraphQLArguments, createGitHubClient } from "../github.mjs";

function response(value) {
  return { exitCode: 0, stdout: JSON.stringify(value), stderr: "", timedOut: false };
}

test("GraphQL adapter parses one page and uses argument arrays", async () => {
  let observed;
  const client = createGitHubClient({
    runCommand: async (command, args, options) => {
      observed = { command, args, options };
      return response({ data: { viewer: { login: "user" } } });
    },
  });
  assert.deepEqual(await client.graphql("query Test { viewer { login } }", { value: 1 }), {
    viewer: { login: "user" },
  });
  assert.deepEqual(observed.command, "gh");
  assert.deepEqual(observed.args, [
    "api", "graphql", "--raw-field", "query=query Test { viewer { login } }", "--field", "value=1",
  ]);
  assert.equal(observed.options.stdin, undefined);
});

test("GraphQL adapter paginates every page", async () => {
  const pages = [
    response({ data: { items: { nodes: [1], pageInfo: { hasNextPage: true, endCursor: "c1" } } } }),
    response({ data: { items: { nodes: [2], pageInfo: { hasNextPage: false, endCursor: null } } } }),
  ];
  const invocations = [];
  const client = createGitHubClient({
    runCommand: async (_command, args) => {
      invocations.push(args);
      return pages.shift();
    },
  });
  const nodes = await client.paginate({
    query: "query ($cursor: String) { items { nodes pageInfo { hasNextPage endCursor } } }",
    getConnection: (data) => data.items,
  });
  assert.deepEqual(nodes, [1, 2]);
  assert.equal(invocations[0].some((argument) => argument === "cursor=null"), false);
  assert.ok(invocations[1].includes("cursor=c1"));
});

test("GraphQL arguments encode scalar variables and omit null optional variables", () => {
  assert.deepEqual(
    buildGraphQLArguments("query Test($login: String!, $number: Int!) { viewer { login } }", {
      login: "dotin2001",
      number: 2,
      enabled: true,
      cursor: null,
    }).slice(-6),
    ["--raw-field", "login=dotin2001", "--field", "number=2", "--field", "enabled=true"],
  );
});

test("GraphQL errors are typed and redacted", async () => {
  const token = "gho_abcdefghijklmnopqrstuvwxyz";
  const client = createGitHubClient({
    runCommand: async () => response({ errors: [{ message: `bad ${token}`, type: "FORBIDDEN" }] }),
  });
  await assert.rejects(() => client.graphql("query { viewer { login } }"), (error) => {
    assert.equal(error.code, "github_graphql_error");
    assert.doesNotMatch(JSON.stringify(error), new RegExp(token));
    return true;
  });
});

test("GraphQL adapter rejects malformed responses", async () => {
  const malformedJson = createGitHubClient({
    runCommand: async () => ({ exitCode: 0, stdout: "not-json", stderr: "", timedOut: false }),
  });
  await assert.rejects(() => malformedJson.graphql("query { viewer { login } }"), (error) =>
    error.code === "github_malformed_response",
  );

  const malformedPage = createGitHubClient({
    runCommand: async () => response({ data: { items: { nodes: [] } } }),
  });
  await assert.rejects(
    () => malformedPage.paginate({ query: "query {}", getConnection: (data) => data.items }),
    (error) => error.code === "github_malformed_response",
  );
});

test("GraphQL adapter reports transport failures without token output", async () => {
  const client = createGitHubClient({
    runCommand: async () => {
      throw new ProcessError("spawn gho_abcdefghijklmnopqrstuvwxyz", { causeCode: "ENOENT" });
    },
  });
  await assert.rejects(() => client.graphql("query {}"), (error) => {
    assert.equal(error.code, "github_transport_failed");
    assert.doesNotMatch(JSON.stringify(error), /gho_abcdefghijklmnopqrstuvwxyz/);
    return true;
  });
});
