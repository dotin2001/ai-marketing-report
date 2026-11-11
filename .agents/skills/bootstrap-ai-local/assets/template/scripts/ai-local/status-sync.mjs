import { GitHubError } from "./errors.mjs";

const ITEM_QUERY = `
query AiLocalProjectItem($itemId: ID!, $statusField: String!) {
  node(id: $itemId) {
    ... on ProjectV2Item {
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
      }
    }
  }
}`;

const UPDATE_STATUS_MUTATION = `
mutation AiLocalUpdateProjectStatus(
  $projectId: ID!
  $itemId: ID!
  $fieldId: ID!
  $optionId: String!
) {
  updateProjectV2ItemFieldValue(input: {
    projectId: $projectId
    itemId: $itemId
    fieldId: $fieldId
    value: { singleSelectOptionId: $optionId }
  }) {
    projectV2Item { id }
  }
}`;

export async function fetchProjectItem(client, project, itemId) {
  const data = await client.graphql(ITEM_QUERY, {
    itemId,
    statusField: project.statusField.name,
  });
  const item = data.node;
  if (item?.id !== itemId || item.content?.__typename !== "Issue") {
    throw new GitHubError("project_item_read_failed", `Project item ${itemId} is missing or is not linked to an issue.`);
  }
  return Object.freeze({
    projectId: project.id,
    projectItemId: item.id,
    projectItemUpdatedAt: item.updatedAt,
    status: item.status?.name ?? null,
    statusOptionId: item.status?.optionId ?? null,
    issueId: item.content.id,
    issueNumber: item.content.number,
    title: item.content.title,
    url: item.content.url,
    issueUpdatedAt: item.content.updatedAt,
    repositoryId: item.content.repository.id,
    repository: item.content.repository.nameWithOwner,
  });
}

export async function synchronizeProjectStatus(client, guarded, project) {
  if (guarded?.kind !== "ReadyStatusMutation") {
    throw new GitHubError("mutation_guard_missing", "A final ReadyStatusMutation guard is required.");
  }
  const data = await client.graphql(UPDATE_STATUS_MUTATION, {
    projectId: guarded.projectId,
    itemId: guarded.projectItemId,
    fieldId: guarded.statusFieldId,
    optionId: guarded.doneOptionId,
  });
  if (data.updateProjectV2ItemFieldValue?.projectV2Item?.id !== guarded.projectItemId) {
    throw new GitHubError("status_mutation_failed", "GitHub did not confirm the selected Project item update.");
  }
  const confirmed = await fetchProjectItem(client, project, guarded.projectItemId);
  if (confirmed.status !== guarded.doneName || confirmed.statusOptionId !== guarded.doneOptionId) {
    throw new GitHubError("status_confirmation_failed", "The Project item did not confirm the configured Done status.", {
      actualStatus: confirmed.status,
    });
  }
  return Object.freeze({ kind: "synchronized", confirmedStatus: confirmed.status, item: confirmed });
}

export const statusSyncQueries = Object.freeze({ item: ITEM_QUERY, updateStatus: UPDATE_STATUS_MUTATION });
