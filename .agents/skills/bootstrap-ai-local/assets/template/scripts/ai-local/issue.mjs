import { GitHubError } from "./errors.mjs";

const ISSUE_QUERY = `
query AiLocalIssue($issueId: ID!) {
  node(id: $issueId) {
    __typename
    ... on Issue {
      id number title body url createdAt updatedAt
      repository { id nameWithOwner isFork }
    }
  }
}`;

const COMMENTS_QUERY = `
query AiLocalIssueComments($issueId: ID!, $cursor: String) {
  node(id: $issueId) {
    ... on Issue {
      comments(first: 100, after: $cursor) {
        nodes {
          id body url createdAt updatedAt
          author { login }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}`;

export async function fetchIssueContext(client, selectedItem) {
  const data = await client.graphql(ISSUE_QUERY, { issueId: selectedItem.issueId });
  const issue = data.node;
  if (issue?.__typename !== "Issue" || issue.id !== selectedItem.issueId) {
    throw new GitHubError("issue_identity_conflict", "Selected Project item no longer resolves to the expected issue.", {
      expected: selectedItem.issueId,
      actual: issue?.id,
    });
  }
  const comments = await client.paginate({
    query: COMMENTS_QUERY,
    variables: { issueId: issue.id },
    getConnection: (page) => page.node?.comments,
  });

  return Object.freeze({
    id: issue.id,
    number: issue.number,
    title: issue.title,
    body: issue.body ?? "",
    url: issue.url,
    createdAt: issue.createdAt,
    updatedAt: issue.updatedAt,
    repository: Object.freeze({ ...issue.repository }),
    comments: Object.freeze(
      comments.map((comment, index) =>
        Object.freeze({
          id: comment.id,
          order: index,
          body: comment.body ?? "",
          url: comment.url,
          createdAt: comment.createdAt,
          updatedAt: comment.updatedAt,
          author: comment.author?.login ?? null,
        }),
      ),
    ),
  });
}

export const issueQueries = Object.freeze({ issue: ISSUE_QUERY, comments: COMMENTS_QUERY });
