import { readFile } from "node:fs/promises";
import path from "node:path";

import { ConfigurationError } from "./errors.mjs";

const REPOSITORY_PATTERN = /^[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,38})\/[A-Za-z0-9_.-]+$/;
const OWNER_PATTERN = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$/;
const PACKAGE_MANAGERS = new Set(["npm", "pnpm", "yarn", "bun"]);
const VERIFICATION_EXECUTABLES = new Set([
  "npm", "pnpm", "yarn", "bun", "node", "npx", "python", "python3", "pytest",
  "ruff", "mypy", "alembic", "openspec", "cargo", "go", "make", "cmake",
  "ctest", "gradle", "mvn", "dotnet", "git",
]);
const EXECUTION_PROFILES = new Set(["neutral", "backend-test", "postgresql"]);
const DEFAULT_POSTGRES_HOSTS = Object.freeze(["localhost", "127.0.0.1", "::1"]);
const CREDENTIAL_MARKER = /(?:[A-Za-z][A-Za-z0-9+.-]*:\/\/|password|secret|token|credential|(?:^|\s)[A-Za-z_][A-Za-z0-9_]*=)/i;

function requireNonEmptyString(value, field) {
  if (typeof value !== "string" || value.length === 0 || value.trim() !== value) {
    throw new ConfigurationError(`${field} must be a non-empty exact string.`);
  }
  return value;
}

function validateVerification(value = {}, packageManager = "npm") {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new ConfigurationError("verification configuration must be an object.");
  }
  const allowedKeys = new Set(["autoDiscover", "commands", "executionProfiles", "approvedPostgresHosts", "syncTask"]);
  for (const key of Object.keys(value)) {
    if (!allowedKeys.has(key)) {
      throw new ConfigurationError(`verification.${key} is not supported.`);
    }
  }

  let syncTask = null;
  if (value.syncTask !== undefined) {
    const policy = value.syncTask;
    if (!policy || typeof policy !== "object" || Array.isArray(policy)
      || Object.keys(policy).some((key) => !["requiredCommands", "semanticReview"].includes(key))) {
      throw new ConfigurationError("verification.syncTask must contain only requiredCommands and semanticReview.");
    }
    const expected = ["git diff --check", `${packageManager} run frontend:test`, `${packageManager} run backend:test`];
    if (!Array.isArray(policy.requiredCommands)
      || policy.requiredCommands.length !== expected.length
      || policy.requiredCommands.some((command, index) => command !== expected[index])) {
      throw new ConfigurationError(`verification.syncTask.requiredCommands must be ${expected.join(", ")} in that order.`);
    }
    if (policy.semanticReview !== "optional") {
      throw new ConfigurationError("verification.syncTask.semanticReview must be optional.");
    }
    syncTask = Object.freeze({
      id: "basic-local-v1",
      requiredCommands: Object.freeze([...expected]),
      semanticReview: "optional",
    });
  }

  const rawProfiles = value.executionProfiles ?? {};
  if (!rawProfiles || typeof rawProfiles !== "object" || Array.isArray(rawProfiles)) {
    throw new ConfigurationError("verification.executionProfiles must be an object.");
  }
  const executionProfiles = {};
  for (const [selector, profile] of Object.entries(rawProfiles)) {
    const exactSelector = requireNonEmptyString(selector, "verification.executionProfiles selector");
    if (/\r|\n|\0/.test(exactSelector) || CREDENTIAL_MARKER.test(exactSelector)) {
      throw new ConfigurationError("verification execution-profile selectors must not contain credentials or environment assignments.");
    }
    if (!EXECUTION_PROFILES.has(profile)) {
      throw new ConfigurationError(
        `verification.executionProfiles.${exactSelector} must be neutral, backend-test, or postgresql.`,
      );
    }
    const normalized = /^(?:npm|pnpm|yarn|bun) run /.test(exactSelector)
      ? exactSelector
      : `${packageManager} run ${exactSelector}`;
    if (Object.hasOwn(executionProfiles, normalized)) {
      throw new ConfigurationError(`Conflicting execution profiles are configured for ${normalized}.`);
    }
    executionProfiles[normalized] = profile;
  }

  const rawHosts = value.approvedPostgresHosts ?? DEFAULT_POSTGRES_HOSTS;
  if (!Array.isArray(rawHosts) || rawHosts.length === 0) {
    throw new ConfigurationError("verification.approvedPostgresHosts must be a non-empty string array.");
  }
  const approvedPostgresHosts = [];
  for (const host of rawHosts) {
    const exactHost = requireNonEmptyString(host, "verification.approvedPostgresHosts entry").toLowerCase();
    if (/[\s/@?#]/.test(exactHost) || CREDENTIAL_MARKER.test(exactHost)) {
      throw new ConfigurationError("verification.approvedPostgresHosts contains a malformed or credential-bearing value.");
    }
    if (!approvedPostgresHosts.includes(exactHost)) approvedPostgresHosts.push(exactHost);
  }

  const autoDiscover = value.autoDiscover ?? true;
  if (typeof autoDiscover !== "boolean") {
    throw new ConfigurationError("verification.autoDiscover must be boolean.");
  }
  const rawCommands = value.commands ?? [];
  if (!Array.isArray(rawCommands)) {
    throw new ConfigurationError("verification.commands must be an array.");
  }
  const commands = rawCommands.map((entry, index) => {
    const label = `verification.commands[${index}]`;
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) {
      throw new ConfigurationError(`${label} must be an object.`);
    }
    const command = requireNonEmptyString(entry.command, `${label}.command`);
    if (!VERIFICATION_EXECUTABLES.has(command)) {
      throw new ConfigurationError(`${label}.command is not an allowed verification executable.`);
    }
    if (!Array.isArray(entry.args) || entry.args.some((arg) => typeof arg !== "string" || /[\0\r\n]/.test(arg))) {
      throw new ConfigurationError(`${label}.args must be a string array without control characters.`);
    }
    if (command === "git" && (entry.args.length !== 2 || entry.args[0] !== "diff" || entry.args[1] !== "--check")) {
      throw new ConfigurationError(`${label} permits only git diff --check.`);
    }
    const timeoutMs = entry.timeoutMs ?? 5 * 60_000;
    if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1_000 || timeoutMs > 30 * 60_000) {
      throw new ConfigurationError(`${label}.timeoutMs must be between 1000 and 1800000.`);
    }
    const executionProfile = entry.executionProfile ?? null;
    if (executionProfile !== null && !EXECUTION_PROFILES.has(executionProfile)) {
      throw new ConfigurationError(`${label}.executionProfile is unsupported.`);
    }
    return Object.freeze({
      command,
      args: Object.freeze([...entry.args]),
      timeoutMs,
      executionProfile,
    });
  });

  return Object.freeze({
    syncTask,
    autoDiscover,
    commands: Object.freeze(commands),
    executionProfiles: Object.freeze(executionProfiles),
    approvedPostgresHosts: Object.freeze(approvedPostgresHosts),
  });
}

export function validateConfiguration(value, repositoryRoot) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new ConfigurationError("Configuration must be a JSON object.");
  }
  const github = value.github;
  if (!github || typeof github !== "object" || Array.isArray(github)) {
    throw new ConfigurationError("github configuration is required.");
  }

  const repository = requireNonEmptyString(github.repository, "github.repository");
  if (!REPOSITORY_PATTERN.test(repository) || repository.includes("..")) {
    throw new ConfigurationError("github.repository must be an owner/name identity.");
  }
  const [repositoryOwner] = repository.split("/");
  const projectOwner = requireNonEmptyString(github.projectOwner, "github.projectOwner");
  if (!OWNER_PATTERN.test(projectOwner)) {
    throw new ConfigurationError("github.projectOwner is malformed.");
  }
  if (!Number.isSafeInteger(github.projectNumber) || github.projectNumber <= 0) {
    throw new ConfigurationError("github.projectNumber must be a positive integer.");
  }

  const statusField = requireNonEmptyString(github.statusField, "github.statusField");
  const todoOption = requireNonEmptyString(github.todoOption, "github.todoOption");
  const inProgressOption = requireNonEmptyString(github.inProgressOption, "github.inProgressOption");
  const doneOption = requireNonEmptyString(github.doneOption, "github.doneOption");
  if (new Set([todoOption, inProgressOption, doneOption]).size !== 3) {
    throw new ConfigurationError("Todo, In Progress, and Done option names must be different.");
  }

  const packageManager = value.packageManager ?? "npm";
  if (!PACKAGE_MANAGERS.has(packageManager)) {
    throw new ConfigurationError("packageManager must be npm, pnpm, yarn, or bun.");
  }

  const runtimeDirectory = requireNonEmptyString(value.runtimeDirectory, "runtimeDirectory");
  if (path.isAbsolute(runtimeDirectory)) {
    throw new ConfigurationError("runtimeDirectory must be repository-relative.");
  }
  const runtimePath = path.resolve(repositoryRoot, runtimeDirectory);
  const relativeRuntimePath = path.relative(repositoryRoot, runtimePath);
  if (
    relativeRuntimePath === "" ||
    relativeRuntimePath === ".git" ||
    relativeRuntimePath.startsWith(`.git${path.sep}`) ||
    relativeRuntimePath === ".." ||
    relativeRuntimePath.startsWith(`..${path.sep}`)
  ) {
    throw new ConfigurationError("runtimeDirectory must be a safe directory inside the repository.");
  }

  return Object.freeze({
    github: Object.freeze({
      repository,
      repositoryOwner,
      projectOwner,
      projectNumber: github.projectNumber,
      statusField,
      todoOption,
      inProgressOption,
      doneOption,
    }),
    repositoryRoot,
    runtimeDirectory,
    runtimePath,
    packageManager,
    verification: validateVerification(value.verification, packageManager),
  });
}

export async function loadConfiguration({
  repositoryRoot = process.cwd(),
  environment = process.env,
  readFileImpl = readFile,
} = {}) {
  const configuredPath = environment.AI_LOCAL_CONFIG || "ai-local.config.json";
  const configPath = path.isAbsolute(configuredPath)
    ? configuredPath
    : path.resolve(repositoryRoot, configuredPath);

  let raw;
  try {
    raw = await readFileImpl(configPath, "utf8");
  } catch (error) {
    throw new ConfigurationError(`Unable to read configuration at ${configPath}.`, {
      causeCode: error?.code,
    });
  }

  let value;
  try {
    value = JSON.parse(raw);
  } catch {
    throw new ConfigurationError(`Configuration at ${configPath} is not valid JSON.`);
  }

  return Object.freeze({
    ...validateConfiguration(value, path.resolve(repositoryRoot)),
    configPath,
  });
}
