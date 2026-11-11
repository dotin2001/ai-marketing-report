import { readFile } from "node:fs/promises";
import path from "node:path";

import { ConfigurationError } from "./errors.mjs";

const REPOSITORY_PATTERN = /^[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,38})\/[A-Za-z0-9_.-]+$/;
const OWNER_PATTERN = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$/;
const PACKAGE_MANAGERS = new Set(["npm", "pnpm", "yarn", "bun"]);
const VERIFICATION_EXECUTABLES = new Set([
  "npm", "pnpm", "yarn", "bun", "node", "npx", "python", "python3", "pytest",
  "ruff", "mypy", "alembic", "openspec", "cargo", "go", "make", "cmake",
  "ctest", "gradle", "mvn", "dotnet",
]);

function requireNonEmptyString(value, field) {
  if (typeof value !== "string" || value.length === 0 || value.trim() !== value) {
    throw new ConfigurationError(`${field} must be a non-empty exact string.`);
  }
  return value;
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
  const doneOption = requireNonEmptyString(github.doneOption, "github.doneOption");
  if (todoOption === doneOption) {
    throw new ConfigurationError("Todo and Done option names must be different.");
  }

  const packageManager = value.packageManager ?? "npm";
  if (!PACKAGE_MANAGERS.has(packageManager)) {
    throw new ConfigurationError("packageManager must be npm, pnpm, yarn, or bun.");
  }

  const verificationValue = value.verification ?? {};
  if (!verificationValue || typeof verificationValue !== "object" || Array.isArray(verificationValue)) {
    throw new ConfigurationError("verification must be a JSON object.");
  }
  const autoDiscover = verificationValue.autoDiscover ?? true;
  if (typeof autoDiscover !== "boolean") {
    throw new ConfigurationError("verification.autoDiscover must be boolean.");
  }
  const commandValues = verificationValue.commands ?? [];
  if (!Array.isArray(commandValues)) {
    throw new ConfigurationError("verification.commands must be an array.");
  }
  const commands = commandValues.map((entry, index) => {
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
    const timeoutMs = entry.timeoutMs ?? 5 * 60_000;
    if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1_000 || timeoutMs > 30 * 60_000) {
      throw new ConfigurationError(`${label}.timeoutMs must be between 1000 and 1800000.`);
    }
    return Object.freeze({ command, args: Object.freeze([...entry.args]), timeoutMs });
  });

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
      doneOption,
    }),
    packageManager,
    verification: Object.freeze({ autoDiscover, commands: Object.freeze(commands) }),
    repositoryRoot,
    runtimeDirectory,
    runtimePath,
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
