import { randomUUID } from "node:crypto";
import { chmod, link, mkdir, open, readdir, rm } from "node:fs/promises";
import path from "node:path";

import { VerificationError } from "./errors.mjs";
import { redact } from "./process.mjs";

export const EVIDENCE_SCHEMA_VERSION = 1;

function safeSegment(value, label) {
  if (typeof value !== "string" || !/^[A-Za-z0-9._-]+$/.test(value)) {
    throw new VerificationError("evidence_invalid", `${label} is not a safe evidence path segment.`);
  }
  return value;
}

function redactedClone(value) {
  return JSON.parse(redact(JSON.stringify(value)));
}

export function createEvidenceRecord({
  attemptId,
  changeId,
  recordedAt = new Date().toISOString(),
  identities,
  criterionResults,
  commandResults,
  fingerprints,
  toolVersions,
  verificationState,
  synchronization,
}) {
  safeSegment(attemptId, "attemptId");
  safeSegment(changeId, "changeId");
  if (!["passed", "failed", "blocked"].includes(verificationState)) {
    throw new VerificationError("evidence_invalid", "Evidence verification state is invalid.");
  }
  if (!identities || !fingerprints || !Array.isArray(criterionResults) || !Array.isArray(commandResults)) {
    throw new VerificationError("evidence_invalid", "Evidence identities, fingerprints, criteria, and commands are required.");
  }
  const record = {
    schemaVersion: EVIDENCE_SCHEMA_VERSION,
    attemptId,
    changeId,
    recordedAt,
    identities,
    verification: {
      state: verificationState,
      criteria: criterionResults.map((result) => ({
        id: result.id,
        verdict: result.verdict,
        evidence: result.evidence,
        commandEvidenceIds: result.commandEvidenceIds,
      })),
      commands: commandResults.map((result) => ({
        checkId: result.checkId,
        command: result.command,
        args: result.args,
        state: result.state,
        exitCode: result.exitCode,
        durationMs: result.durationMs,
        stdout: result.stdout,
        stderr: result.stderr,
        reason: result.reason,
      })),
    },
    fingerprints,
    toolVersions: toolVersions ?? {},
    synchronization: {
      state: synchronization?.state ?? "not_attempted",
      attemptedAt: synchronization?.attemptedAt ?? null,
      errorCode: synchronization?.errorCode ?? null,
      confirmedStatus: synchronization?.confirmedStatus ?? null,
    },
  };
  return Object.freeze(redactedClone(record));
}

async function appendOnlyJson(destination, value) {
  const directory = path.dirname(destination);
  await mkdir(directory, { recursive: true, mode: 0o700 });
  const temporary = path.join(directory, `.${path.basename(destination)}.${randomUUID()}.partial`);
  const handle = await open(temporary, "wx", 0o600);
  try {
    await handle.writeFile(`${JSON.stringify(value, null, 2)}\n`, "utf8");
    await handle.sync();
  } finally {
    await handle.close();
  }
  try {
    await link(temporary, destination);
    await chmod(destination, 0o600);
  } catch (error) {
    if (error.code === "EEXIST") {
      throw new VerificationError("evidence_exists", `Evidence record already exists: ${destination}.`);
    }
    throw error;
  } finally {
    await rm(temporary, { force: true });
  }
}

export async function persistEvidence(runtimePaths, record) {
  if (record.schemaVersion !== EVIDENCE_SCHEMA_VERSION) {
    throw new VerificationError("evidence_invalid", "Evidence schema version is unsupported.");
  }
  const changeId = safeSegment(record.changeId, "changeId");
  const attemptId = safeSegment(record.attemptId, "attemptId");
  const timestamp = String(record.recordedAt).replace(/[:.]/g, "-");
  const directory = path.join(runtimePaths.evidence, changeId);
  const destination = path.join(directory, `${timestamp}-${attemptId}.json`);
  await appendOnlyJson(destination, record);
  return destination;
}

export async function listEvidence(runtimePaths, changeId) {
  const directory = path.join(runtimePaths.evidence, safeSegment(changeId, "changeId"));
  try {
    return (await readdir(directory))
      .filter((entry) => entry.endsWith(".json"))
      .sort()
      .map((entry) => path.join(directory, entry));
  } catch (error) {
    if (error.code === "ENOENT") return [];
    throw error;
  }
}
