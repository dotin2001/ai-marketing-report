import { readFile } from "node:fs/promises";
import path from "node:path";

import { ConfigurationError } from "./errors.mjs";

const REPOSITORY_PATTERN = /^[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,38})\/[A-Za-z0-9_.-]+$/;
const OWNER_PATTERN = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$/;

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
