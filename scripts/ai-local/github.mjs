import { GitHubError, ProcessError } from "./errors.mjs";
import { assertAllowedGraphQL } from "./policy.mjs";
import { redact, runProcess } from "./process.mjs";

function sanitizeErrors(errors) {
  if (!Array.isArray(errors)) return [];
  return errors.map((error) => ({
    type: redact(error?.type ?? "unknown"),
    message: redact(error?.message ?? "GitHub GraphQL error"),
    path: Array.isArray(error?.path) ? error.path.map(String) : undefined,
  }));
}

function appendField(args, key, value) {
  if (value === null || value === undefined) return;
  if (Array.isArray(value)) {
    for (const entry of value) appendField(args, `${key}[]`, entry);
    return;
  }
  if (!["string", "number", "boolean"].includes(typeof value)) {
    throw new GitHubError("github_invalid_variables", `GraphQL variable ${key} must be a scalar or scalar array.`);
  }
  args.push(typeof value === "string" ? "--raw-field" : "--field", `${key}=${String(value)}`);
}

export function buildGraphQLArguments(query, variables = {}) {
  if (typeof query !== "string" || !query.trim()) {
    throw new GitHubError("github_invalid_query", "GraphQL query must be a non-empty string.");
  }
  if (!variables || typeof variables !== "object" || Array.isArray(variables)) {
    throw new GitHubError("github_invalid_variables", "GraphQL variables must be an object.");
  }
  const args = ["api", "graphql", "--raw-field", `query=${query}`];
  for (const [key, value] of Object.entries(variables)) appendField(args, key, value);
  return args;
}

export function createGitHubClient({ runCommand = runProcess, cwd, timeoutMs = 30_000 } = {}) {
  async function graphql(query, variables = {}) {
    assertAllowedGraphQL(query);
    const args = buildGraphQLArguments(query, variables);
    let result;
    try {
      result = await runCommand("gh", args, {
        cwd,
        timeoutMs,
      });
    } catch (error) {
      if (error instanceof ProcessError) {
        throw new GitHubError("github_transport_failed", "GitHub GraphQL transport could not start.", {
          causeCode: error.details?.causeCode,
        });
      }
      throw error;
    }
    if (result.timedOut) {
      throw new GitHubError("github_timeout", "GitHub GraphQL request timed out.");
    }
    if (result.exitCode !== 0) {
      throw new GitHubError("github_transport_failed", "GitHub GraphQL request failed.", {
        stderr: redact(result.stderr),
      });
    }

    let response;
    try {
      response = JSON.parse(result.stdout);
    } catch {
      throw new GitHubError("github_malformed_response", "GitHub returned malformed JSON.", {
        output: redact(result.stdout).slice(0, 1024),
      });
    }
    if (!response || typeof response !== "object" || Array.isArray(response)) {
      throw new GitHubError("github_malformed_response", "GitHub returned a non-object response.");
    }
    if (response.errors?.length) {
      throw new GitHubError("github_graphql_error", "GitHub GraphQL returned errors.", {
        errors: sanitizeErrors(response.errors),
      });
    }
    if (!response.data || typeof response.data !== "object") {
      throw new GitHubError("github_malformed_response", "GitHub response did not contain data.");
    }
    return response.data;
  }

  async function paginate({ query, variables = {}, getConnection }) {
    if (typeof getConnection !== "function") {
      throw new GitHubError("github_invalid_pagination", "Pagination requires a connection selector.");
    }
    const nodes = [];
    let cursor = null;
    const seenCursors = new Set();
    for (;;) {
      const data = await graphql(query, { ...variables, cursor });
      const connection = getConnection(data);
      if (!connection || !Array.isArray(connection.nodes) || !connection.pageInfo) {
        throw new GitHubError("github_malformed_response", "GitHub pagination connection is malformed.");
      }
      nodes.push(...connection.nodes);
      if (!connection.pageInfo.hasNextPage) return nodes;
      const nextCursor = connection.pageInfo.endCursor;
      if (typeof nextCursor !== "string" || !nextCursor || seenCursors.has(nextCursor)) {
        throw new GitHubError("github_malformed_response", "GitHub pagination cursor is missing or repeated.");
      }
      seenCursors.add(nextCursor);
      cursor = nextCursor;
    }
  }

  return Object.freeze({ graphql, paginate });
}
