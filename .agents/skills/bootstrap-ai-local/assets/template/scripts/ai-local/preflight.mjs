import { PreflightError, ProcessError } from "./errors.mjs";
import { redact, runProcess } from "./process.mjs";

const REQUIRED_TOOLS = ["git", "node", "gh", "codex", "openspec"];

export function normalizeGitHubRepository(remoteUrl) {
  const value = String(remoteUrl ?? "").trim();
  const patterns = [
    /^https?:\/\/github\.com\/([^/]+\/[^/]+?)(?:\.git)?\/?$/i,
    /^git@github\.com:([^/]+\/[^/]+?)(?:\.git)?$/i,
    /^ssh:\/\/git@github\.com\/([^/]+\/[^/]+?)(?:\.git)?\/?$/i,
    /^git:\/\/github\.com\/([^/]+\/[^/]+?)(?:\.git)?\/?$/i,
  ];
  for (const pattern of patterns) {
    const match = value.match(pattern);
    if (match) return match[1];
  }
  throw new PreflightError("invalid_remote", `Unsupported GitHub remote: ${redact(value)}`);
}

async function requiredCommand(runCommand, command, args, cwd, failure) {
  let result;
  try {
    result = await runCommand(command, args, { cwd, timeoutMs: 15_000 });
  } catch (error) {
    if (error instanceof ProcessError) {
      throw new PreflightError("missing_prerequisite", `${command} is required but unavailable.`, {
        command,
      });
    }
    throw error;
  }
  if (result.timedOut) {
    throw new PreflightError("preflight_timeout", `${command} timed out during preflight.`, {
      command,
    });
  }
  if (result.exitCode !== 0) {
    throw new PreflightError(failure.code, failure.message, {
      command,
      stderr: redact(result.stderr),
    });
  }
  return result.stdout.trim();
}

export async function runPreflight(config, { runCommand = runProcess } = {}) {
  const cwd = config.repositoryRoot;
  const toolVersions = {};
  const requiredTools = [...new Set([...REQUIRED_TOOLS, config.packageManager ?? "npm"])];
  for (const tool of requiredTools) {
    const versionArgs = tool === "git" ? ["--version"] : ["--version"];
    toolVersions[tool] = await requiredCommand(runCommand, tool, versionArgs, cwd, {
      code: "missing_prerequisite",
      message: `${tool} is required but did not execute successfully.`,
    });
  }

  const remoteUrl = await requiredCommand(runCommand, "git", ["remote", "get-url", "origin"], cwd, {
    code: "invalid_remote",
    message: "Unable to resolve the origin Git remote.",
  });
  const repository = normalizeGitHubRepository(remoteUrl);
  if (repository.toLowerCase() !== config.github.repository.toLowerCase()) {
    throw new PreflightError(
      "repository_mismatch",
      `Configured repository ${config.github.repository} does not match Git remote ${repository}.`,
      { configured: config.github.repository, actual: repository },
    );
  }

  const branch = await requiredCommand(runCommand, "git", ["branch", "--show-current"], cwd, {
    code: "invalid_repository_state",
    message: "Unable to resolve the current Git branch.",
  });
  if (!branch) {
    throw new PreflightError("invalid_repository_state", "A named Git branch is required; detached HEAD is not supported.");
  }
  const head = await requiredCommand(runCommand, "git", ["rev-parse", "HEAD"], cwd, {
    code: "invalid_repository_state",
    message: "Unable to resolve the current Git commit.",
  });

  await requiredCommand(runCommand, "gh", ["auth", "status"], cwd, {
    code: "authentication_failed",
    message: "GitHub authentication is invalid. Run `gh auth login` and grant repo, read:project, and project access.",
  });

  return Object.freeze({ repository, remoteUrl, branch, head, toolVersions });
}
