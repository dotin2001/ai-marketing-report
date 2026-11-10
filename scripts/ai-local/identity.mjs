import { IdentityConflictError } from "./errors.mjs";

function same(field, expected, actual) {
  if (expected !== actual) throw new IdentityConflictError(field, expected, actual);
}

export function assertLiveIdentity({
  traceability,
  changeId,
  config,
  preflight,
  project,
  item,
  issue,
}) {
  same("changeId", traceability.changeId, changeId);
  same("configured repository", traceability.repository, config.github.repository);
  same("Git remote repository", traceability.repository, preflight.repository);
  same("branch", traceability.branch, preflight.branch);
  same("Project owner", traceability.projectOwner, project.ownerLogin);
  same("Project number", traceability.projectNumber, project.number);
  same("Project id", traceability.projectId, project.id);
  same("Project item id", traceability.projectItemId, item.projectItemId);
  same("item Project id", traceability.projectId, item.projectId);
  same("item linked issue id", traceability.issueId, item.issueId);
  same("item linked issue number", traceability.issueNumber, item.issueNumber);
  same("item repository", traceability.repository, item.repository);
  same("item repository id", traceability.repositoryId, item.repositoryId);
  same("issue id", traceability.issueId, issue.id);
  same("issue number", traceability.issueNumber, issue.number);
  same("issue repository", traceability.repository, issue.repository.nameWithOwner);
  same("issue repository id", traceability.repositoryId, issue.repository.id);

  return Object.freeze({
    repository: preflight.repository,
    branch: preflight.branch,
    head: preflight.head,
    projectId: project.id,
    projectItemId: item.projectItemId,
    issueId: issue.id,
    changeId,
    status: item.status,
  });
}
