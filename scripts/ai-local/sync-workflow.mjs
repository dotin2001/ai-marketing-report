import { randomUUID } from "node:crypto";

import { runCodexVerification } from "./codex.mjs";
import { loadConfiguration } from "./config.mjs";
import { createEvidenceRecord, persistEvidence } from "./evidence.mjs";
import { VerificationError } from "./errors.mjs";
import { buildFingerprints, fingerprintsEqual } from "./fingerprint.mjs";
import { createGitHubClient } from "./github.mjs";
import { executeAfterFinalGuard } from "./guard.mjs";
import { assertLiveIdentity } from "./identity.mjs";
import { fetchIssueContext } from "./issue.mjs";
import { acquireRepositoryLock } from "./lock.mjs";
import { createPolicyTransport } from "./policy.mjs";
import { runPreflight } from "./preflight.mjs";
import { runProcess } from "./process.mjs";
import { resolveProject } from "./project.mjs";
import { findReusableEvidence } from "./retry.mjs";
import { ensureRuntimeLayout } from "./runtime.mjs";
import { createTerminalPrompt } from "./selector.mjs";
import { fetchProjectItem, synchronizeProjectStatus } from "./status-sync.mjs";
import {
  discoverSynchronizationCandidates,
  resolveSynchronizationCandidate,
} from "./sync-input.mjs";
import {
  buildVerificationManifest,
  discoverVerificationChecks,
  executeRequiredChecks,
  reconcileVerification,
} from "./verification.mjs";

function evidenceInputs({ traceability, semantic, checkSummary, fingerprints, toolVersions }) {
  return {
    identities: traceability,
    criterionResults: semantic?.results ?? [],
    commandResults: checkSummary?.results ?? [],
    fingerprints,
    toolVersions,
  };
}

export async function runSynchronizationWorkflow(options = {}, dependencies = {}) {
  const output = dependencies.output ?? process.stdout;
  const repositoryRoot = dependencies.repositoryRoot ?? process.cwd();
  const config = await (dependencies.loadConfiguration ?? loadConfiguration)({ repositoryRoot });
  const runCommand = createPolicyTransport(dependencies.runCommand ?? runProcess);
  const runtimePaths = await (dependencies.ensureRuntimeLayout ?? ensureRuntimeLayout)(config.runtimePath);
  const ownedPrompt = dependencies.prompt ? null : createTerminalPrompt();
  const prompt = dependencies.prompt ?? ownedPrompt;
  const lock = await (dependencies.acquireRepositoryLock ?? acquireRepositoryLock)(runtimePaths, { mode: "sync" });
  const attemptId = dependencies.attemptId ?? randomUUID();

  let passing;
  let evidenceWritten = false;
  try {
    const preflight = await (dependencies.runPreflight ?? runPreflight)(config, { ...dependencies, runCommand });
    const github = dependencies.githubClient ?? createGitHubClient({ cwd: repositoryRoot, runCommand });
    const project = await (dependencies.resolveProject ?? resolveProject)(github, config);
    const candidates = await (dependencies.discoverSynchronizationCandidates ?? discoverSynchronizationCandidates)({
      repositoryRoot,
      runtimePaths,
    });
    const selected = await (dependencies.resolveSynchronizationCandidate ?? resolveSynchronizationCandidate)({
      candidates,
      explicitChangeId: options.changeId,
      prompt,
      output,
    });
    if (selected.kind !== "selected") return selected;

    const { candidate } = selected;
    const traceability = candidate.traceability;
    const item = await (dependencies.fetchProjectItem ?? fetchProjectItem)(github, project, traceability.projectItemId);
    const issue = await (dependencies.fetchIssueContext ?? fetchIssueContext)(github, item);
    assertLiveIdentity({ traceability, changeId: candidate.changeId, config, preflight, project, item, issue });

    const manifest = await (dependencies.buildVerificationManifest ?? buildVerificationManifest)({
      repositoryRoot,
      changeId: candidate.changeId,
      issue,
    });
    const checks = await (dependencies.discoverVerificationChecks ?? discoverVerificationChecks)({
      repositoryRoot,
      changeId: candidate.changeId,
      manifest,
    });
    const fingerprintArgs = {
      repositoryRoot,
      identity: traceability,
      artifactPaths: manifest.artifactPaths,
      instructionPaths: dependencies.instructionPaths ?? [],
      issue,
      checks,
      toolVersions: preflight.toolVersions,
      runCommand,
    };
    const initialFingerprints = await (dependencies.buildFingerprints ?? buildFingerprints)(fingerprintArgs);
    const retry = await (dependencies.findReusableEvidence ?? findReusableEvidence)({
      runtimePaths,
      changeId: candidate.changeId,
      identities: traceability,
      fingerprints: initialFingerprints,
    });

    let verification;
    let semantic;
    let checkSummary;
    let verifiedFingerprints = initialFingerprints;
    if (retry.kind === "reuse") {
      semantic = { results: retry.record.verification.criteria, passed: true };
      checkSummary = { results: retry.record.verification.commands, passed: true };
      verification = Object.freeze({ kind: "VerifiedSynchronization", reused: true });
      output.write(`Reusing passing verification evidence ${retry.record.attemptId}.\n`);
    } else {
      checkSummary = await (dependencies.executeRequiredChecks ?? executeRequiredChecks)(checks, {
        repositoryRoot,
        runCommand,
      });
      if (!checkSummary.passed) {
        const record = createEvidenceRecord({
          attemptId,
          changeId: candidate.changeId,
          ...evidenceInputs({ traceability, checkSummary, fingerprints: initialFingerprints, toolVersions: preflight.toolVersions }),
          verificationState: checkSummary.failedRequired?.some((entry) => entry.state === "blocked") ? "blocked" : "failed",
          synchronization: { state: "not_attempted" },
        });
        await (dependencies.persistEvidence ?? persistEvidence)(runtimePaths, record);
        evidenceWritten = true;
        throw new VerificationError("verification_failed", "One or more required checks did not pass.");
      }
      verifiedFingerprints = await (dependencies.buildFingerprints ?? buildFingerprints)(fingerprintArgs);
      if (!fingerprintsEqual(initialFingerprints, verifiedFingerprints)) {
        const record = createEvidenceRecord({
          attemptId,
          changeId: candidate.changeId,
          ...evidenceInputs({ traceability, checkSummary, fingerprints: verifiedFingerprints, toolVersions: preflight.toolVersions }),
          verificationState: "failed",
          synchronization: { state: "not_attempted", errorCode: "fingerprint_changed" },
        });
        await (dependencies.persistEvidence ?? persistEvidence)(runtimePaths, record);
        evidenceWritten = true;
        throw new VerificationError("fingerprint_changed", "A required check changed verification inputs.");
      }
      semantic = await (dependencies.runCodexVerification ?? runCodexVerification)({
        repositoryRoot,
        runtimePaths,
        manifest,
        checkSummary,
        runCommand,
        environment: dependencies.environment,
      });
      verification = (dependencies.reconcileVerification ?? reconcileVerification)({
        manifest,
        requiredChecks: checks,
        checkSummary,
        semanticResult: semantic,
      });
    }

    passing = { traceability, semantic, checkSummary, fingerprints: verifiedFingerprints, toolVersions: preflight.toolVersions };

    // All Git/GitHub state used by the write guard is fetched again after verification.
    const finalPreflight = await (dependencies.runPreflight ?? runPreflight)(config, { ...dependencies, runCommand });
    const finalProject = await (dependencies.resolveProject ?? resolveProject)(github, config);
    const finalItem = await (dependencies.fetchProjectItem ?? fetchProjectItem)(github, finalProject, traceability.projectItemId);
    const finalIssue = await (dependencies.fetchIssueContext ?? fetchIssueContext)(github, finalItem);
    const currentFingerprints = await (dependencies.buildFingerprints ?? buildFingerprints)({
      ...fingerprintArgs,
      issue: finalIssue,
      toolVersions: finalPreflight.toolVersions,
    });
    const statusResult = await (dependencies.executeAfterFinalGuard ?? executeAfterFinalGuard)(
      {
        verification,
        verifiedFingerprints,
        currentFingerprints,
        identityInput: {
          traceability,
          changeId: candidate.changeId,
          config,
          preflight: finalPreflight,
          project: finalProject,
          item: finalItem,
          issue: finalIssue,
        },
        todoName: config.github.todoOption,
        doneName: config.github.doneOption,
      },
      (guarded) => (dependencies.synchronizeProjectStatus ?? synchronizeProjectStatus)(github, guarded, finalProject),
    );
    const confirmedStatus = statusResult.kind === "already_done" ? config.github.doneOption : statusResult.confirmedStatus;
    const record = createEvidenceRecord({
      attemptId,
      changeId: candidate.changeId,
      ...evidenceInputs(passing),
      verificationState: "passed",
      synchronization: {
        state: statusResult.kind === "already_done" ? "already_done" : "succeeded",
        attemptedAt: new Date().toISOString(),
        confirmedStatus,
      },
    });
    await (dependencies.persistEvidence ?? persistEvidence)(runtimePaths, record);
    evidenceWritten = true;
    output.write(`Verified ${candidate.changeId}; Project item is ${confirmedStatus}. Issue remains open.\n`);
    return { kind: statusResult.kind, exitCode: 0, changeId: candidate.changeId, confirmedStatus };
  } catch (error) {
    if (passing && !evidenceWritten) {
      const record = createEvidenceRecord({
        attemptId,
        changeId: passing.traceability.changeId,
        ...evidenceInputs(passing),
        verificationState: "passed",
        synchronization: {
          state: "failed",
          attemptedAt: new Date().toISOString(),
          errorCode: error.code ?? "synchronization_failed",
        },
      });
      await (dependencies.persistEvidence ?? persistEvidence)(runtimePaths, record);
    }
    throw error;
  } finally {
    await lock.release();
    ownedPrompt?.close();
  }
}
