import { readdir, readFile } from "node:fs/promises";
import path from "node:path";

import { TraceabilityError } from "./errors.mjs";
import {
  parseLinkRecord,
  parseTraceabilityMarker,
  traceabilityMatches,
} from "./traceability.mjs";

async function proposalCandidates(directory, archived) {
  let entries;
  try {
    entries = await readdir(directory, { withFileTypes: true });
  } catch (error) {
    if (error.code === "ENOENT") return [];
    throw error;
  }
  const candidates = [];
  for (const entry of entries.filter((candidate) => candidate.isDirectory() && candidate.name !== "archive")) {
    const proposalPath = path.join(directory, entry.name, "proposal.md");
    let proposal;
    try {
      proposal = await readFile(proposalPath, "utf8");
    } catch (error) {
      if (error.code === "ENOENT") continue;
      throw error;
    }
    if (!proposal.includes("ai-local-trace:")) continue;
    const traceability = parseTraceabilityMarker(proposal);
    if (traceability.changeId !== entry.name) {
      throw new TraceabilityError(
        "link_disagreement",
        `Proposal directory ${entry.name} disagrees with marker changeId ${traceability.changeId}.`,
      );
    }
    candidates.push({
      changeId: entry.name,
      proposalPath,
      archived,
      traceability,
    });
  }
  return candidates;
}

export async function discoverSynchronizationCandidates({ repositoryRoot, runtimePaths }) {
  const changesRoot = path.join(repositoryRoot, "openspec", "changes");
  const candidates = [
    ...(await proposalCandidates(changesRoot, false)),
    ...(await proposalCandidates(path.join(changesRoot, "archive"), true)),
    ...(await proposalCandidates(path.join(repositoryRoot, "openspec", "archive"), true)),
  ];
  for (const candidate of candidates) {
    const recordPath = path.join(runtimePaths.links, `${candidate.changeId}.json`);
    let record;
    try {
      record = parseLinkRecord(JSON.parse(await readFile(recordPath, "utf8")));
    } catch (error) {
      if (error.code === "ENOENT") {
        throw new TraceabilityError(
          "link_record_missing",
          `Linked change ${candidate.changeId} has no runtime link record.`,
        );
      }
      throw error;
    }
    if (!traceabilityMatches(candidate.traceability, record.traceability)) {
      throw new TraceabilityError(
        "link_disagreement",
        `Proposal marker and link record disagree for ${candidate.changeId}.`,
      );
    }
    candidate.recordPath = recordPath;
    candidate.record = record;
  }
  return Object.freeze(candidates.map((candidate) => Object.freeze(candidate)));
}

export async function resolveSynchronizationCandidate({
  candidates,
  explicitChangeId,
  prompt,
  output = process.stdout,
}) {
  if (explicitChangeId) {
    const candidate = candidates.find((entry) => entry.changeId === explicitChangeId);
    if (!candidate) {
      throw new TraceabilityError(
        "sync_candidate_not_found",
        `No valid linked change exists for ${explicitChangeId}.`,
      );
    }
    if (candidate.archived) {
      throw new TraceabilityError("link_archived", `Change ${explicitChangeId} is archived.`);
    }
    output.write(`Using linked change ${candidate.changeId}.\n`);
    return { kind: "selected", candidate };
  }

  const active = candidates.filter((candidate) => !candidate.archived);
  if (active.length === 0) {
    output.write("No eligible linked OpenSpec changes are available for synchronization.\n");
    return { kind: "no_candidate", exitCode: 0 };
  }
  if (active.length === 1) {
    output.write(`Using sole linked change ${active[0].changeId}.\n`);
    return { kind: "selected", candidate: active[0] };
  }
  if (!prompt?.ask) throw new TypeError("Ambiguous synchronization candidates require a prompt.");
  output.write("Linked changes eligible for synchronization:\n");
  active.forEach((candidate, index) => {
    output.write(`${index + 1}. ${candidate.changeId} — issue #${candidate.traceability.issueNumber}\n`);
  });
  for (;;) {
    const answer = await prompt.ask("Select a change number, or q to cancel: ");
    if (answer === null || ["", "q", "quit", "cancel"].includes(String(answer).trim().toLowerCase())) {
      output.write("Synchronization selection cancelled.\n");
      return { kind: "cancelled", exitCode: 0 };
    }
    if (/^\d+$/.test(String(answer).trim())) {
      const selected = active[Number(answer) - 1];
      if (selected) return { kind: "selected", candidate: selected };
    }
    output.write("Invalid change selection. Try again or enter q.\n");
  }
}
