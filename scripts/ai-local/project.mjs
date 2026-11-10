import { GitHubError } from "./errors.mjs";

const OWNER_QUERY = `
query AiLocalProjectOwner($login: String!, $number: Int!) {
  repositoryOwner(login: $login) {
    __typename
    ... on User { login projectV2(number: $number) { id number title } }
    ... on Organization { login projectV2(number: $number) { id number title } }
  }
}`;

const FIELDS_QUERY = `
query AiLocalProjectFields($projectId: ID!, $cursor: String) {
  node(id: $projectId) {
    ... on ProjectV2 {
      fields(first: 100, after: $cursor) {
        nodes {
          __typename
          ... on ProjectV2Field { id name }
          ... on ProjectV2IterationField { id name }
          ... on ProjectV2SingleSelectField { id name options { id name } }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}`;

const ITEMS_QUERY = `
query AiLocalProjectItems($projectId: ID!, $statusField: String!, $cursor: String) {
  node(id: $projectId) {
    ... on ProjectV2 {
      items(first: 100, after: $cursor) {
        nodes {
          id
          updatedAt
          status: fieldValueByName(name: $statusField) {
            ... on ProjectV2ItemFieldSingleSelectValue { optionId name }
          }
          content {
            __typename
            ... on Issue {
              id number title url updatedAt
              repository { id nameWithOwner isFork }
            }
            ... on PullRequest {
              id number title url
              repository { id nameWithOwner isFork }
            }
          }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}`;

function requireExactlyOne(values, code, description) {
  if (values.length !== 1) {
    throw new GitHubError(code, `${description} must resolve exactly once; found ${values.length}.`);
  }
  return values[0];
}

export async function resolveProject(client, config) {
  const ownerData = await client.graphql(OWNER_QUERY, {
    login: config.github.projectOwner,
    number: config.github.projectNumber,
  });
  const owner = ownerData.repositoryOwner;
  const candidates = owner?.projectV2 && ["User", "Organization"].includes(owner.__typename)
    ? [{ ownerType: owner.__typename, ownerLogin: owner.login, ...owner.projectV2 }]
    : [];
  const project = requireExactlyOne(
    candidates,
    "project_resolution_failed",
    `Project ${config.github.projectOwner}#${config.github.projectNumber}`,
  );

  const fields = await client.paginate({
    query: FIELDS_QUERY,
    variables: { projectId: project.id },
    getConnection: (data) => data.node?.fields,
  });
  const namedStatusFields = fields.filter((field) => field?.name === config.github.statusField);
  const statusField = requireExactlyOne(
    namedStatusFields,
    "status_field_resolution_failed",
    `Status field ${config.github.statusField}`,
  );
  if (statusField.__typename !== "ProjectV2SingleSelectField" || !Array.isArray(statusField.options)) {
    throw new GitHubError(
      "status_field_wrong_type",
      `${config.github.statusField} must be a ProjectV2 single-select field.`,
    );
  }
  const todoOption = requireExactlyOne(
    statusField.options.filter((option) => option.name === config.github.todoOption),
    "todo_option_resolution_failed",
    `Todo option ${config.github.todoOption}`,
  );
  const doneOption = requireExactlyOne(
    statusField.options.filter((option) => option.name === config.github.doneOption),
    "done_option_resolution_failed",
    `Done option ${config.github.doneOption}`,
  );

  return Object.freeze({
    ...project,
    statusField: Object.freeze({ id: statusField.id, name: statusField.name }),
    todoOption: Object.freeze({ id: todoOption.id, name: todoOption.name }),
    doneOption: Object.freeze({ id: doneOption.id, name: doneOption.name }),
  });
}

export async function fetchEligibleItems(client, project, config) {
  const items = await client.paginate({
    query: ITEMS_QUERY,
    variables: {
      projectId: project.id,
      statusField: config.github.statusField,
    },
    getConnection: (data) => data.node?.items,
  });

  return items
    .filter((item) => {
      const content = item?.content;
      return (
        typeof item?.id === "string" &&
        item.status?.name === config.github.todoOption &&
        item.status?.optionId === project.todoOption.id &&
        content?.__typename === "Issue" &&
        content.repository?.nameWithOwner === config.github.repository &&
        content.repository?.isFork === false
      );
    })
    .map((item) =>
      Object.freeze({
        projectItemId: item.id,
        projectItemUpdatedAt: item.updatedAt,
        status: item.status.name,
        statusOptionId: item.status.optionId,
        issueId: item.content.id,
        issueNumber: item.content.number,
        title: item.content.title,
        url: item.content.url,
        issueUpdatedAt: item.content.updatedAt,
        repositoryId: item.content.repository.id,
        repository: item.content.repository.nameWithOwner,
      }),
    );
}

export const projectQueries = Object.freeze({ owner: OWNER_QUERY, fields: FIELDS_QUERY, items: ITEMS_QUERY });
