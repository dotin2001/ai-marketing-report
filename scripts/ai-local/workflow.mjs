import path from "node:path";

import { runCodexPlanning } from "./codex.mjs";
import { loadConfiguration } from "./config.mjs";
import {
  assertConfiguredRepository,
  parseGitHubIssueUrl,
  resolveExplicitIssue,
} from "./explicit-issue.mjs";
import { createGitHubClient } from "./github.mjs";
import { fetchIssueContext } from "./issue.mjs";
import { acquireRepositoryLock } from "./lock.mjs";
import {
  generateChangeId,
  resolveLinkedChange,
  validateProposalOutput,
} from "./openspec.mjs";
import { createPlanningContext } from "./planning-context.mjs";
import { createPolicyTransport } from "./policy.mjs";
import { runPreflight } from "./preflight.mjs";
import { runProcess } from "./process.mjs";
import { fetchEligibleItems, fetchProjectIssues, resolveProject } from "./project.mjs";
import {
  atomicWriteJson,
  cleanupOwnedTemp,
  ensureRuntimeLayout,
} from "./runtime.mjs";
import { createTerminalPrompt, selectIssue } from "./selector.mjs";
import { startProjectWork } from "./status-sync.mjs";
import { TraceabilityError } from "./errors.mjs";
import {
  createLinkRecord,
  createTraceability,
} from "./traceability.mjs";

function yes(answer) {
  return ["y", "yes"].includes(String(answer ?? "").trim().toLowerCase());
}

function displayProposal(output, validated, kind, started) {
  output.write(`\n${kind === "reuse" ? "Reusing" : "Created"} validated OpenSpec change: ${validated.changeId}\n`);
  for (const artifactPath of validated.artifactPaths) output.write(`- ${artifactPath}\n`);
  output.write("Strict OpenSpec validation passed.\n");
  output.write(`Review the artifacts, then manually invoke $openspec-apply-change ${validated.changeId} in Codex.\n`);
  output.write(started
    ? "Project item is In Progress. No implementation was performed.\n"
    : "No implementation or GitHub state change was performed.\n");
}

export async function runPlanningWorkflow(options = {}, dependencies = {}) {
  const output = dependencies.output ?? process.stdout;
  const repositoryRoot = dependencies.repositoryRoot ?? process.cwd();
  const config = await (dependencies.loadConfiguration ?? loadConfiguration)({ repositoryRoot });
  const explicitTarget = options.issueUrl
    ? assertConfiguredRepository(
        options.issueTarget ?? parseGitHubIssueUrl(options.issueUrl),
        config.github.repository,
      )
    : null;
  const runCommand = createPolicyTransport(dependencies.runCommand ?? runProcess);
  const runtimePaths = await (dependencies.ensureRuntimeLayout ?? ensureRuntimeLayout)(config.runtimePath);
  const ownedPrompt = dependencies.prompt ? null : createTerminalPrompt();
  const prompt = dependencies.prompt ?? ownedPrompt;

  const confirmStale = dependencies.confirmStale ?? (async (existing) => {
    const answer = await prompt.ask(
      `Lock for dead PID ${existing.pid} on ${existing.hostname} appears stale. Remove it? [y/N] `,
    );
    return yes(answer);
  });
  const lock = await (dependencies.acquireRepositoryLock ?? acquireRepositoryLock)(runtimePaths, {
    mode: "planning",
    confirmStale,
  });

  try {
    const preflight = await (dependencies.runPreflight ?? runPreflight)(config, { ...dependencies, runCommand });
    const github = dependencies.githubClient ?? createGitHubClient({ cwd: repositoryRoot, runCommand });
    const project = await (dependencies.resolveProject ?? resolveProject)(github, config);
    const items = explicitTarget
      ? await (dependencies.fetchProjectIssues ?? fetchProjectIssues)(github, project, config)
      : await (dependencies.fetchEligibleItems ?? fetchEligibleItems)(github, project, config);
    const selection = explicitTarget
      ? (dependencies.resolveExplicitIssue ?? resolveExplicitIssue)(
          items,
          explicitTarget,
          project,
        )
      : await (dependencies.selectIssue ?? selectIssue)(items, { prompt, output });
    if (selection.kind !== "selected") return selection;

    const issue = await (dependencies.fetchIssueContext ?? fetchIssueContext)(github, selection.item);
    const linked = await (dependencies.resolveLinkedChange ?? resolveLinkedChange)({
      repositoryRoot,
      runtimePaths,
      expected: { repository: config.github.repository, issueId: issue.id },
    });

    if (linked.kind === "reuse") {
      if (
        linked.traceability.projectId !== project.id ||
        linked.traceability.projectItemId !== selection.item.projectItemId ||
        linked.traceability.issueId !== issue.id ||
        linked.traceability.repositoryId !== issue.repository.id
      ) {
        throw new TraceabilityError("link_disagreement", "The linked change does not match the selected Project item. Review its traceability before retrying.");
      }
      const reuse = dependencies.confirmReuse
        ? await dependencies.confirmReuse(linked)
        : yes(await prompt.ask(`Reuse linked change ${linked.changeId}? [y/N] `));
      if (!reuse) {
        output.write("Linked change reuse cancelled; no new proposal was created.\n");
        return { kind: "cancelled", exitCode: 0 };
      }
      await (dependencies.startProjectWork ?? startProjectWork)(github, project, selection.item, issue, {
        requireTodo: !explicitTarget,
      });
      const validated = await (dependencies.validateProposalOutput ?? validateProposalOutput)({
        repositoryRoot,
        changeId: linked.changeId,
        expectedTraceability: linked.traceability,
        runCommand,
      });
      displayProposal(output, validated, "reuse", true);
      return { kind: "proposal_ready", reused: true, exitCode: 0, changeId: linked.changeId };
    }

    const changeId = await (dependencies.generateChangeId ?? generateChangeId)({
      repositoryRoot,
      issueNumber: issue.number,
      issueId: issue.id,
      title: issue.title,
    });
    const traceability = createTraceability({
      repository: config.github.repository,
      repositoryId: issue.repository.id,
      projectOwner: config.github.projectOwner,
      projectNumber: config.github.projectNumber,
      projectId: project.id,
      projectItemId: selection.item.projectItemId,
      issueId: issue.id,
      issueNumber: issue.number,
      branch: preflight.branch,
      baseCommit: preflight.head,
      changeId,
    });
    await (dependencies.startProjectWork ?? startProjectWork)(github, project, selection.item, issue, {
      requireTodo: !explicitTarget,
    });
    const context = await (dependencies.createPlanningContext ?? createPlanningContext)(runtimePaths, {
      issue,
      traceability,
    });
    try {
      await (dependencies.runCodexPlanning ?? runCodexPlanning)({
        repositoryRoot,
        runtimePaths,
        prompt: context.prompt,
        runCommand,
        environment: dependencies.environment,
      });
    } finally {
      await (dependencies.cleanupOwnedTemp ?? cleanupOwnedTemp)(context);
    }
    const validated = await (dependencies.validateProposalOutput ?? validateProposalOutput)({
      repositoryRoot,
      changeId,
      expectedTraceability: traceability,
      runCommand,
    });
    const recordPath = path.join(runtimePaths.links, `${changeId}.json`);
    await (dependencies.atomicWriteJson ?? atomicWriteJson)(recordPath, createLinkRecord(traceability));
    displayProposal(output, validated, "created", true);
    return { kind: "proposal_ready", reused: false, exitCode: 0, changeId, recordPath };
  } finally {
    await lock.release();
    ownedPrompt?.close();
  }
}
