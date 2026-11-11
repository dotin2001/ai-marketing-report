import { createHash } from "node:crypto";
import { readdir, readFile, stat } from "node:fs/promises";
import path from "node:path";

import { OpenSpecValidationError, TraceabilityError } from "./errors.mjs";
import { redact, runProcess } from "./process.mjs";
import {
  parseLinkRecord,
  parseTraceabilityMarker,
  traceabilityMatches,
} from "./traceability.mjs";

async function exists(target) {
  try {
    await stat(target);
    return true;
  } catch (error) {
    if (error.code === "ENOENT") return false;
    throw error;
  }
}

async function childDirectories(directory) {
  try {
    return (await readdir(directory, { withFileTypes: true }))
      .filter((entry) => entry.isDirectory())
      .map((entry) => entry.name)
      .sort();
  } catch (error) {
    if (error.code === "ENOENT") return [];
    throw error;
  }
}

async function scanProposalDirectory(directory, archived, expected) {
  const candidates = [];
  for (const changeId of await childDirectories(directory)) {
    const proposalPath = path.join(directory, changeId, "proposal.md");
    if (!(await exists(proposalPath))) continue;
    const text = await readFile(proposalPath, "utf8");
    if (!text.includes("ai-local-trace:")) continue;
    const traceability = parseTraceabilityMarker(text);
    if (
      traceability.repository === expected.repository &&
      traceability.issueId === expected.issueId
    ) {
      candidates.push({ changeId, proposalPath, archived, traceability });
    }
  }
  return candidates;
}

async function scanLinkRecords(linksPath, expected) {
  const records = [];
  let entries;
  try {
    entries = await readdir(linksPath, { withFileTypes: true });
  } catch (error) {
    if (error.code === "ENOENT") return records;
    throw error;
  }
  for (const entry of entries.filter((candidate) => candidate.isFile() && candidate.name.endsWith(".json"))) {
    const recordPath = path.join(linksPath, entry.name);
    const record = parseLinkRecord(JSON.parse(await readFile(recordPath, "utf8")));
    if (
      record.traceability.repository === expected.repository &&
      record.traceability.issueId === expected.issueId
    ) {
      records.push({ recordPath, record });
    }
  }
  return records;
}

export async function resolveLinkedChange({ repositoryRoot, runtimePaths, expected }) {
  const activeRoot = path.join(repositoryRoot, "openspec", "changes");
  const archivedRoots = [
    path.join(repositoryRoot, "openspec", "changes", "archive"),
    path.join(repositoryRoot, "openspec", "archive"),
  ];
  const active = (await scanProposalDirectory(activeRoot, false, expected)).filter(
    (candidate) => path.basename(path.dirname(candidate.proposalPath)) !== "archive",
  );
  const archived = (
    await Promise.all(archivedRoots.map((root) => scanProposalDirectory(root, true, expected)))
  ).flat();
  const records = await scanLinkRecords(runtimePaths.links, expected);
  const proposals = [...active, ...archived];

  for (const candidate of proposals) {
    const matchingRecords = records.filter(
      ({ record }) => record.traceability.changeId === candidate.traceability.changeId,
    );
    if (matchingRecords.length > 1) {
      throw new TraceabilityError("link_ambiguous", `Multiple link records exist for ${candidate.changeId}.`);
    }
    if (matchingRecords.length === 1 && !traceabilityMatches(matchingRecords[0].record.traceability, candidate.traceability)) {
      throw new TraceabilityError(
        "link_disagreement",
        `Proposal marker and runtime link record disagree for ${candidate.changeId}.`,
      );
    }
    candidate.recordPath = matchingRecords[0]?.recordPath;
  }

  for (const { recordPath, record } of records) {
    const proposal = proposals.find(
      (candidate) => candidate.traceability.changeId === record.traceability.changeId,
    );
    if (!proposal) {
      throw new TraceabilityError(
        "link_disagreement",
        `Runtime link record ${recordPath} has no matching proposal marker.`,
      );
    }
  }

  if (proposals.length > 1) {
    throw new TraceabilityError("link_ambiguous", "Multiple linked OpenSpec changes exist for this issue.", {
      candidates: proposals.map((candidate) => candidate.changeId),
    });
  }
  if (archived.length === 1) {
    throw new TraceabilityError(
      "link_archived",
      `Linked change ${archived[0].changeId} is archived and cannot be reused for apply.`,
      { candidate: archived[0] },
    );
  }
  return active.length === 1 ? Object.freeze({ kind: "reuse", ...active[0] }) : Object.freeze({ kind: "none" });
}

function slugify(title) {
  return String(title)
    .normalize("NFKD")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48)
    .replace(/-+$/g, "") || "issue";
}

export async function generateChangeId({ repositoryRoot, issueNumber, issueId, title }) {
  const base = `gh-${issueNumber}-${slugify(title)}`;
  const changesRoot = path.join(repositoryRoot, "openspec", "changes");
  const archiveRoots = [path.join(changesRoot, "archive"), path.join(repositoryRoot, "openspec", "archive")];
  const collides = async (changeId) =>
    (await exists(path.join(changesRoot, changeId))) ||
    (await Promise.all(archiveRoots.map((root) => exists(path.join(root, changeId))))).some(Boolean);
  if (!(await collides(base))) return base;

  const issueHash = createHash("sha256").update(String(issueId)).digest("hex").slice(0, 8);
  const hashed = `${base}-${issueHash}`;
  if (!(await collides(hashed))) return hashed;
  for (let suffix = 2; suffix < 10_000; suffix += 1) {
    const candidate = `${hashed}-${suffix}`;
    if (!(await collides(candidate))) return candidate;
  }
  throw new TraceabilityError("change_id_exhausted", "Unable to allocate a collision-safe change identifier.");
}

async function markdownFiles(directory) {
  const files = [];
  let entries;
  try {
    entries = await readdir(directory, { withFileTypes: true });
  } catch (error) {
    if (error.code === "ENOENT") return files;
    throw error;
  }
  for (const entry of entries) {
    const target = path.join(directory, entry.name);
    if (entry.isDirectory()) files.push(...(await markdownFiles(target)));
    else if (entry.isFile() && entry.name.endsWith(".md")) files.push(target);
  }
  return files.sort();
}

async function requiredText(filePath, artifactName) {
  try {
    const text = await readFile(filePath, "utf8");
    if (!text.trim()) throw new Error("empty");
    return text;
  } catch (error) {
    throw new OpenSpecValidationError(
      "proposal_artifact_missing",
      `Required ${artifactName} artifact is missing or empty: ${filePath}`,
      { filePath, causeCode: error.code },
    );
  }
}

export async function validateProposalOutput({
  repositoryRoot,
  changeId,
  expectedTraceability,
  runCommand = runProcess,
}) {
  const changeRoot = path.join(repositoryRoot, "openspec", "changes", changeId);
  const proposalPath = path.join(changeRoot, "proposal.md");
  const designPath = path.join(changeRoot, "design.md");
  const tasksPath = path.join(changeRoot, "tasks.md");
  const proposal = await requiredText(proposalPath, "proposal");
  await requiredText(designPath, "design");
  const tasks = await requiredText(tasksPath, "tasks");
  const traceability = parseTraceabilityMarker(proposal, expectedTraceability);
  if (traceability.changeId !== changeId) {
    throw new OpenSpecValidationError(
      "proposal_traceability_invalid",
      `Proposal marker changeId ${traceability.changeId} does not match ${changeId}.`,
    );
  }

  const specPaths = await markdownFiles(path.join(changeRoot, "specs"));
  if (specPaths.length === 0) {
    throw new OpenSpecValidationError("proposal_artifact_missing", "At least one capability specification is required.");
  }
  for (const specPath of specPaths) {
    const spec = await requiredText(specPath, "specification");
    if (!/^### Requirement:\s+.+/m.test(spec) || !/^#### Scenario:\s+.+/m.test(spec)) {
      throw new OpenSpecValidationError(
        "proposal_artifact_incomplete",
        `Specification lacks a normative requirement or scenario: ${specPath}`,
      );
    }
  }
  if (!/^- \[[ xX]\]\s+.+/m.test(tasks) || !/\b(?:verify|test|check|validate)\b/i.test(tasks)) {
    throw new OpenSpecValidationError(
      "proposal_artifact_incomplete",
      "Tasks must contain implementation checkboxes and required verification definitions.",
    );
  }

  const result = await runCommand(
    "openspec",
    ["validate", changeId, "--strict", "--json"],
    { cwd: repositoryRoot, timeoutMs: 60_000 },
  );
  let validation;
  try {
    validation = JSON.parse(result.stdout);
  } catch {
    throw new OpenSpecValidationError("openspec_validation_failed", "OpenSpec validation returned malformed JSON.", {
      output: redact(result.stdout).slice(0, 2048),
    });
  }
  if (result.timedOut || result.exitCode !== 0 || validation.valid === false) {
    throw new OpenSpecValidationError("openspec_validation_failed", "Strict OpenSpec validation failed.", {
      exitCode: result.exitCode,
      timedOut: result.timedOut,
      validation,
      stderr: redact(result.stderr).slice(0, 4096),
    });
  }

  return Object.freeze({
    changeId,
    changeRoot,
    artifactPaths: Object.freeze([proposalPath, designPath, ...specPaths, tasksPath]),
    traceability,
    validation,
  });
}
