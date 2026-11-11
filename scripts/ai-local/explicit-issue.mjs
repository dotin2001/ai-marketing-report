import { GitHubError, UsageError } from "./errors.mjs";

const SEGMENT_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_.-]*$/;

function invalidIssueUrl() {
  return new UsageError(
    "--issue requires https://github.com/<owner>/<repository>/issues/<positive-number> with no query or fragment.",
  );
}

export function parseGitHubIssueUrl(value) {
  let url;
  try {
    url = new URL(String(value));
  } catch {
    throw invalidIssueUrl();
  }

  if (
    url.protocol !== "https:" ||
    url.hostname !== "github.com" ||
    url.username ||
    url.password ||
    url.port ||
    url.search ||
    url.hash
  ) {
    throw invalidIssueUrl();
  }

  const pathname = url.pathname.endsWith("/") ? url.pathname.slice(0, -1) : url.pathname;
  const rawSegments = pathname.split("/");
  if (
    rawSegments.length !== 5 ||
    rawSegments[0] !== "" ||
    rawSegments[3] !== "issues" ||
    rawSegments[1].includes("%") ||
    rawSegments[2].includes("%") ||
    !/^[1-9]\d*$/.test(rawSegments[4])
  ) {
    throw invalidIssueUrl();
  }

  let owner;
  let repositoryName;
  try {
    owner = decodeURIComponent(rawSegments[1]);
    repositoryName = decodeURIComponent(rawSegments[2]);
  } catch {
    throw invalidIssueUrl();
  }
  const issueNumber = Number(rawSegments[4]);
  if (
    !SEGMENT_PATTERN.test(owner) ||
    !SEGMENT_PATTERN.test(repositoryName) ||
    !Number.isSafeInteger(issueNumber)
  ) {
    throw invalidIssueUrl();
  }

  return Object.freeze({
    url: url.href,
    repository: `${owner}/${repositoryName}`,
    issueNumber,
  });
}

export function assertConfiguredRepository(target, configuredRepository) {
  if (target.repository.toLowerCase() !== configuredRepository.toLowerCase()) {
    throw new UsageError(
      `Issue URL repository ${target.repository} does not match configured repository ${configuredRepository}.`,
      { supplied: target.repository, configured: configuredRepository },
    );
  }
  return Object.freeze({ ...target, repository: configuredRepository });
}

export function resolveExplicitIssue(items, target, todoOption = "Todo") {
  const matches = items.filter(
    (item) =>
      item.repository.toLowerCase() === target.repository.toLowerCase() &&
      item.issueNumber === target.issueNumber &&
      item.status === todoOption,
  );
  if (matches.length === 0) {
    throw new GitHubError(
      "explicit_issue_not_eligible",
      `Issue ${target.repository}#${target.issueNumber} is not an eligible Todo item in the configured Project.`,
    );
  }
  if (matches.length > 1) {
    throw new GitHubError(
      "explicit_issue_ambiguous",
      `Issue ${target.repository}#${target.issueNumber} resolves to ${matches.length} eligible Project items.`,
    );
  }
  return Object.freeze({ kind: "selected", item: matches[0] });
}
