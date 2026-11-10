import { UsageError, WorkflowError } from "./errors.mjs";
import { runSynchronizationWorkflow } from "./sync-workflow.mjs";
import { runPlanningWorkflow } from "./workflow.mjs";

export const HELP_TEXT = `Usage:
  npm run ai:local
  npm run ai:local -- --sync-task [--change <change-id>]
  npm run ai:local -- --help

Modes:
  planning                Select a Todo issue and create or reuse an OpenSpec proposal.
  --sync-task             Verify an implemented change and synchronize Todo to Done.

Options:
  --change <change-id>    Select the linked OpenSpec change for synchronization.
  -h, --help              Show this help text.

Planning stops after proposal validation for manual review. It never applies a change,
closes an issue, switches branches, commits, pushes, merges, or deploys.
`;

const CHANGE_ID_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

export function parseArguments(args) {
  if (!Array.isArray(args)) {
    throw new UsageError("Arguments must be an array.");
  }

  let syncTask = false;
  let changeId;
  let help = false;

  for (let index = 0; index < args.length; index += 1) {
    const argument = args[index];
    if (argument === "--sync-task") {
      if (syncTask) {
        throw new UsageError("--sync-task may be provided only once.");
      }
      syncTask = true;
      continue;
    }
    if (argument === "--change") {
      if (changeId !== undefined) {
        throw new UsageError("--change may be provided only once.");
      }
      const value = args[index + 1];
      if (!value || value.startsWith("-")) {
        throw new UsageError("--change requires a change identifier.");
      }
      if (!CHANGE_ID_PATTERN.test(value)) {
        throw new UsageError(`Invalid change identifier: ${value}`);
      }
      changeId = value;
      index += 1;
      continue;
    }
    if (argument === "--help" || argument === "-h") {
      if (help) {
        throw new UsageError("The help option may be provided only once.");
      }
      help = true;
      continue;
    }
    throw new UsageError(`Unknown argument: ${argument}`);
  }

  if (help && args.length !== 1) {
    throw new UsageError("Help cannot be combined with workflow options.");
  }
  if (changeId && !syncTask) {
    throw new UsageError("--change is valid only with --sync-task.");
  }

  if (help) {
    return { mode: "help" };
  }
  if (syncTask) {
    return { mode: "sync", changeId };
  }
  return { mode: "planning" };
}

export async function main(args, dependencies = {}) {
  const output = dependencies.output ?? process.stdout;
  const errorOutput = dependencies.errorOutput ?? process.stderr;
  try {
    const options = parseArguments(args);
    if (options.mode === "help") {
      output.write(HELP_TEXT);
      return { kind: "help", exitCode: 0 };
    }

    const runner =
      options.mode === "sync"
        ? (dependencies.runSync ?? runSynchronizationWorkflow)
        : (dependencies.runPlanning ?? runPlanningWorkflow);
    if (runner) {
      return await runner(options, dependencies);
    }

    throw new UsageError("The selected workflow is unavailable.");
  } catch (error) {
    if (error instanceof WorkflowError) {
      errorOutput.write(`${error.code}: ${error.message}\n`);
      return { kind: "error", code: error.code, exitCode: error.exitCode };
    }
    throw error;
  }
}
