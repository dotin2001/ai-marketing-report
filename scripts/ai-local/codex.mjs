import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";

import { CodexError, ProcessError } from "./errors.mjs";
import { redact, runProcess } from "./process.mjs";
import {
  appendRedactedEvent,
  cleanupOwnedTemp,
  createOwnedTemp,
} from "./runtime.mjs";
import { validateStructuredVerification } from "./verification.mjs";

export async function runCodexPlanning({
  repositoryRoot,
  runtimePaths,
  prompt,
  attemptId = randomUUID(),
  timeoutMs = 20 * 60_000,
  runCommand = runProcess,
  environment = process.env,
}) {
  const lastMessage = await createOwnedTemp(runtimePaths, "codex-last-message", "");
  const eventLogPath = path.join(runtimePaths.events, `${attemptId}.jsonl`);
  const args = [
    "exec",
    "--cd",
    repositoryRoot,
    "--sandbox",
    "workspace-write",
    "--json",
    "--output-last-message",
    lastMessage.filePath,
    "-",
  ];

  let result;
  try {
    result = await runCommand("codex", args, {
      cwd: repositoryRoot,
      env: environment,
      stdin: prompt,
      timeoutMs,
      maxOutputBytes: 4 * 1024 * 1024,
    });
  } catch (error) {
    await cleanupOwnedTemp(lastMessage);
    if (error instanceof ProcessError) {
      throw new CodexError("codex_transport_failed", "Codex could not be started.", {
        causeCode: error.details?.causeCode,
      });
    }
    throw error;
  }

  const events = [];
  for (const line of String(result.stdout).split("\n").filter(Boolean)) {
    let event;
    try {
      event = JSON.parse(line);
    } catch {
      event = { type: "unparsed_codex_output", output: redact(line).slice(0, 4096) };
    }
    events.push(event);
    await appendRedactedEvent(eventLogPath, event);
  }

  let finalOutput = "";
  try {
    finalOutput = redact(await readFile(lastMessage.filePath, "utf8"));
  } finally {
    await cleanupOwnedTemp(lastMessage);
  }

  if (result.timedOut) {
    throw new CodexError("codex_timeout", "Codex proposal generation timed out.", {
      attemptId,
      eventLogPath,
    });
  }
  if (result.exitCode !== 0) {
    throw new CodexError("codex_failed", "Codex proposal generation failed.", {
      attemptId,
      eventLogPath,
      stderr: redact(result.stderr).slice(0, 8192),
    });
  }

  return Object.freeze({
    attemptId,
    args: Object.freeze([...args]),
    eventLogPath,
    events: Object.freeze(events),
    finalOutput,
    durationMs: result.durationMs,
  });
}

export async function runCodexVerification({
  repositoryRoot,
  runtimePaths,
  manifest,
  checkSummary,
  attemptId = randomUUID(),
  timeoutMs = 20 * 60_000,
  runCommand = runProcess,
  environment = process.env,
}) {
  const input = await createOwnedTemp(
    runtimePaths,
    "verification-input",
    `${JSON.stringify({ manifest, checkSummary }, null, 2)}\n`,
  );
  const output = await createOwnedTemp(runtimePaths, "verification-output", "");
  const schemaPath = path.join(repositoryRoot, "scripts", "ai-local", "schemas", "verification.schema.json");
  const eventLogPath = path.join(runtimePaths.events, `${attemptId}.verification.jsonl`);
  const prompt = `Perform verification only. Inspect the current repository and the trusted verification input at:
${input.filePath}

Return one structured result for every manifest entry using the supplied JSON schema. Cite concrete file,
behavior, or actual command-result evidence. Do not invent command results. Do not edit source, tasks,
specifications, runtime links, or GitHub state; do not clean, commit, push, merge, deploy, or switch branches.`;
  const args = [
    "exec",
    "--cd",
    repositoryRoot,
    "--sandbox",
    "workspace-write",
    "--json",
    "--output-schema",
    schemaPath,
    "--output-last-message",
    output.filePath,
    "-",
  ];
  let processResult;
  try {
    processResult = await runCommand("codex", args, {
      cwd: repositoryRoot,
      env: environment,
      stdin: prompt,
      timeoutMs,
      maxOutputBytes: 4 * 1024 * 1024,
    });
    for (const line of String(processResult.stdout).split("\n").filter(Boolean)) {
      let event;
      try {
        event = JSON.parse(line);
      } catch {
        event = { type: "unparsed_codex_output", output: redact(line).slice(0, 4096) };
      }
      await appendRedactedEvent(eventLogPath, event);
    }
    if (processResult.timedOut || processResult.exitCode !== 0) {
      throw new CodexError(
        processResult.timedOut ? "codex_verification_timeout" : "codex_verification_failed",
        "Codex semantic verification did not complete successfully.",
        { eventLogPath, stderr: redact(processResult.stderr).slice(0, 4096) },
      );
    }
    let parsed;
    try {
      parsed = JSON.parse(await readFile(output.filePath, "utf8"));
    } catch {
      throw new CodexError("codex_verification_malformed", "Codex returned malformed structured verification output.");
    }
    return validateStructuredVerification(parsed, manifest, checkSummary);
  } finally {
    await cleanupOwnedTemp(input);
    await cleanupOwnedTemp(output);
  }
}
