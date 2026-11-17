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
    isFork: item.content.repository.isFork,
    repositoryId: item.content.repository.id,
    repository: item.content.repository.nameWithOwner,
  });
}

async function updateAndConfirm(client, project, itemId, option, failurePrefix) {
  let data;
  try {
    data = await client.graphql(UPDATE_STATUS_MUTATION, {
      projectId: project.id,
      itemId,
      fieldId: project.statusField.id,
      optionId: option.id,
    });
  } catch {
    throw new GitHubError(
      `${failurePrefix}_mutation_failed`,
      `Could not update the selected Project item to ${option.name}. Check GitHub Project access and retry the command.`,
    );
  }
  if (data?.updateProjectV2ItemFieldValue?.projectV2Item?.id !== itemId) {
    throw new GitHubError(
      `${failurePrefix}_mutation_failed`,
      `GitHub did not confirm the selected Project item update to ${option.name}. Retry the command.`,
    );
  }
  let confirmed;
  try {
    confirmed = await fetchProjectItem(client, project, itemId);
  } catch {
    throw new GitHubError(
      `${failurePrefix}_confirmation_failed`,
      `Could not confirm the selected Project item's ${option.name} status. Retry the command.`,
    );
  }
  if (confirmed.status !== option.name || confirmed.statusOptionId !== option.id) {
    throw new GitHubError(
      `${failurePrefix}_confirmation_failed`,
      `The selected Project item did not confirm ${option.name}. Retry the command.`,
      { actualStatus: confirmed.status },
    );
  }
  return confirmed;
}

export async function startProjectWork(client, project, selected, issue) {
  let live;
  try {
    live = await fetchProjectItem(client, project, selected.projectItemId);
  } catch {
    throw new GitHubError("work_start_read_failed", "Could not confirm the selected Project item. Retry the command.");
  }
  if (
    live.projectId !== project.id ||
    live.projectItemId !== selected.projectItemId ||
    live.issueId !== selected.issueId ||
    live.issueNumber !== selected.issueNumber ||
    live.repository !== selected.repository ||
    live.repositoryId !== selected.repositoryId ||
    live.isFork !== false ||
    live.issueId !== issue.id ||
    live.issueNumber !== issue.number ||
    issue.repository?.id !== selected.repositoryId ||
    issue.repository?.nameWithOwner !== selected.repository
  ) {
    throw new GitHubError("work_start_identity_conflict", "The selected Project item no longer matches the issue. Retry after reviewing its Project link.");
  }
  if (live.status === project.inProgressOption.name && live.statusOptionId === project.inProgressOption.id) {
    return Object.freeze({ kind: "already_in_progress", item: live });
  }
  if (live.status !== project.todoOption.name || live.statusOptionId !== project.todoOption.id) {
    throw new GitHubError("work_start_status_conflict", "The selected Project item is no longer Todo or In Progress. Review its status before retrying.");
  }
  const confirmed = await updateAndConfirm(
    client, project, selected.projectItemId, project.inProgressOption, "work_start",
  );
  if (
    confirmed.issueId !== selected.issueId ||
    confirmed.issueNumber !== selected.issueNumber ||
    confirmed.repositoryId !== selected.repositoryId ||
    confirmed.repository !== selected.repository ||
    confirmed.isFork !== false
  ) {
    throw new GitHubError("work_start_identity_conflict", "The selected Project item changed linkage during the status update. Review it before retrying.");
  }
  return Object.freeze({ kind: "started", item: confirmed });
}

export async function synchronizeProjectStatus(client, guarded, project) {
  if (guarded?.kind !== "ReadyStatusMutation") {
    throw new GitHubError("mutation_guard_missing", "A final ReadyStatusMutation guard is required.");
  }
  if (
    guarded.projectId !== project.id ||
    guarded.statusFieldId !== project.statusField.id ||
    guarded.doneOptionId !== project.doneOption.id ||
    guarded.doneName !== project.doneOption.name
  ) {
    throw new GitHubError("mutation_guard_missing", "The final Project status guard does not match the current Project configuration.");
  }
  const confirmed = await updateAndConfirm(
    client, project, guarded.projectItemId,
    { id: guarded.doneOptionId, name: guarded.doneName }, "status",
  );
  return Object.freeze({ kind: "synchronized", confirmedStatus: confirmed.status, item: confirmed });
}

export const statusSyncQueries = Object.freeze({ item: ITEM_QUERY, updateStatus: UPDATE_STATUS_MUTATION });
