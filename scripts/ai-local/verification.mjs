import { readdir, readFile } from "node:fs/promises";
import path from "node:path";

import { ProcessError, VerificationError } from "./errors.mjs";
import { redact, runProcess } from "./process.mjs";

async function readRequired(filePath, label) {
  try {
    const text = await readFile(filePath, "utf8");
    if (!text.trim()) throw new Error("empty");
    return text;
  } catch (error) {
    throw new VerificationError("verification_artifact_missing", `${label} is missing or empty: ${filePath}`, {
      filePath,
      causeCode: error.code,
    });
  }
}

async function findSpecs(directory) {
  let entries;
  try {
    entries = await readdir(directory, { withFileTypes: true });
  } catch (error) {
    if (error.code === "ENOENT") return [];
    throw error;
  }
  const files = [];
  for (const entry of entries) {
    const target = path.join(directory, entry.name);
    if (entry.isDirectory()) files.push(...(await findSpecs(target)));
    else if (entry.isFile() && entry.name.endsWith(".md")) files.push(target);
  }
  return files.sort();
}

function sourceReference(file, line) {
  return Object.freeze({ file, line });
}

export function parseIssueAcceptanceCriteria(issue) {
  const lines = String(issue.body ?? "").split(/\r?\n/);
  const criteria = [];
  let inSection = false;
  let sectionLevel = 0;
  for (let index = 0; index < lines.length; index += 1) {
    const heading = lines[index].match(/^(#{1,6})\s+(.+?)\s*$/);
    if (heading) {
      const level = heading[1].length;
      if (/acceptance\s+criteria/i.test(heading[2])) {
        inSection = true;
        sectionLevel = level;
        continue;
      }
      if (inSection && level <= sectionLevel) inSection = false;
    }
    if (!inSection) continue;
    const criterion = lines[index].match(/^\s*(?:[-*]\s+)(?:\[[ xX]\]\s*)?(.+?)\s*$/);
    if (criterion) {
      criteria.push(
        Object.freeze({
          id: `issue:${criteria.length + 1}`,
          kind: "issue_criterion",
          text: criterion[1],
          source: Object.freeze({ issueId: issue.id, issueUrl: issue.url, line: index + 1 }),
        }),
      );
    }
  }
  if (criteria.length === 0) {
    throw new VerificationError(
      "acceptance_criteria_missing",
      "The current issue has no parseable Acceptance Criteria section.",
    );
  }
  return criteria;
}

export function parseSpecification(text, filePath) {
  const lines = text.split(/\r?\n/);
  const entries = [];
  let currentRequirement;
  for (let index = 0; index < lines.length; index += 1) {
    const requirement = lines[index].match(/^### Requirement:\s+(.+?)\s*$/);
    if (requirement) {
      currentRequirement = {
        id: `requirement:${filePath}:${index + 1}`,
        kind: "requirement",
        text: requirement[1],
        source: sourceReference(filePath, index + 1),
      };
      entries.push(Object.freeze(currentRequirement));
      continue;
    }
    const scenario = lines[index].match(/^#### Scenario:\s+(.+?)\s*$/);
    if (scenario) {
      if (!currentRequirement) {
        throw new VerificationError(
          "verification_artifact_malformed",
          `Scenario appears before a requirement in ${filePath}:${index + 1}.`,
        );
      }
      entries.push(
        Object.freeze({
          id: `scenario:${filePath}:${index + 1}`,
          kind: "scenario",
          text: scenario[1],
          requirementId: currentRequirement.id,
          source: sourceReference(filePath, index + 1),
        }),
      );
    }
  }
  if (!entries.some((entry) => entry.kind === "requirement") || !entries.some((entry) => entry.kind === "scenario")) {
    throw new VerificationError(
      "verification_artifact_malformed",
      `Specification has no complete requirement/scenario definitions: ${filePath}.`,
    );
  }
  return entries;
}

export function parseTasks(text, filePath) {
  const lines = text.split(/\r?\n/);
  const tasks = [];
  for (let index = 0; index < lines.length; index += 1) {
    if (!/^\s*- \[/.test(lines[index])) continue;
    const task = lines[index].match(/^\s*- \[([ xX])\]\s+(.+?)\s*$/);
    if (!task) {
      throw new VerificationError(
        "verification_artifact_malformed",
        `Malformed task checkbox at ${filePath}:${index + 1}.`,
      );
    }
    tasks.push(
      Object.freeze({
        id: `task:${tasks.length + 1}`,
        kind: "task",
        text: task[2],
        complete: task[1].toLowerCase() === "x",
        source: sourceReference(filePath, index + 1),
      }),
    );
  }
  if (tasks.length === 0) {
    throw new VerificationError("verification_artifact_malformed", `No task checkboxes found in ${filePath}.`);
  }
  const incomplete = tasks.filter((task) => !task.complete);
  if (incomplete.length) {
    throw new VerificationError("incomplete_tasks", `${incomplete.length} required OpenSpec task(s) are unchecked.`, {
      tasks: incomplete.map((task) => task.text),
    });
  }
  return tasks;
}

export async function buildVerificationManifest({ repositoryRoot, changeId, issue }) {
  const changeRoot = path.join(repositoryRoot, "openspec", "changes", changeId);
  const proposalPath = path.join(changeRoot, "proposal.md");
  const designPath = path.join(changeRoot, "design.md");
  const tasksPath = path.join(changeRoot, "tasks.md");
  await readRequired(proposalPath, "Proposal");
  await readRequired(designPath, "Design");
  const tasksText = await readRequired(tasksPath, "Tasks");
  const specPaths = await findSpecs(path.join(changeRoot, "specs"));
  if (specPaths.length === 0) {
    throw new VerificationError("verification_artifact_missing", "No capability specifications were found.");
  }
  const requirements = [];
  for (const specPath of specPaths) {
    requirements.push(...parseSpecification(await readRequired(specPath, "Specification"), specPath));
  }
  const criteria = parseIssueAcceptanceCriteria(issue);
  const tasks = parseTasks(tasksText, tasksPath);
  return Object.freeze({
    schemaVersion: 1,
    changeId,
    issueId: issue.id,
    criteria: Object.freeze(criteria),
    requirements: Object.freeze(requirements),
    tasks: Object.freeze(tasks),
    entries: Object.freeze([...criteria, ...requirements, ...tasks]),
    artifactPaths: Object.freeze([proposalPath, designPath, ...specPaths, tasksPath]),
  });
}

const ALLOWED_CHECK_EXECUTABLES = new Set([
  "npm",
  "node",
  "python",
  "python3",
  "pytest",
  "ruff",
  "mypy",
  "alembic",
  "openspec",
]);
const PROHIBITED_CHECK_TOKENS = /(?:&&|\|\||[|;<>`]|\$\(|\n|\r)/;

function simpleCommand(value) {
  const trimmed = value.trim();
  if (!trimmed || PROHIBITED_CHECK_TOKENS.test(trimmed)) return null;
  const args = trimmed.match(/(?:[^\s"']+|"[^"]*"|'[^']*')+/g)?.map((part) =>
    part.replace(/^("|')|("|')$/g, ""),
  );
  if (!args?.length || !ALLOWED_CHECK_EXECUTABLES.has(args[0])) return null;
  if (args[0] === "npm" && args[1] === "run" && args[2] === "ai:local") return null;
  if (args.some((part) => /^[A-Za-z_][A-Za-z0-9_]*=/.test(part))) return null;
  return args;
}

function commandsFromMarkdown(text, source) {
  const commands = [];
  for (const match of String(text).matchAll(/`([^`]+)`/g)) {
    const args = simpleCommand(match[1]);
    if (args) {
      commands.push({ args, source, rationale: `Declared verification command in ${source}.` });
    }
  }
  return commands;
}

export async function discoverVerificationChecks({ repositoryRoot, changeId, manifest }) {
  const checks = [
    {
      args: ["openspec", "validate", changeId, "--strict", "--json"],
      source: path.join(repositoryRoot, "openspec", "changes", changeId),
      rationale: "Strict validation is mandatory for the approved OpenSpec change.",
    },
  ];

  const packagePath = path.join(repositoryRoot, "package.json");
  try {
    const packageJson = JSON.parse(await readFile(packagePath, "utf8"));
    for (const script of ["test", "check", "lint", "typecheck", "type-check", "build"]) {
      if (typeof packageJson.scripts?.[script] === "string") {
        checks.push({
          args: script === "test" ? ["npm", "test"] : ["npm", "run", script],
          source: `${packagePath}#scripts.${script}`,
          rationale: `Declared package ${script} script applies to the current repository.`,
        });
      }
    }
  } catch (error) {
    if (error.code !== "ENOENT") {
      throw new VerificationError("verification_config_malformed", `Unable to parse ${packagePath}.`);
    }
  }

  const trustedMarkdown = [
    path.join(repositoryRoot, "AGENTS.md"),
    path.join(repositoryRoot, "README.md"),
    path.join(repositoryRoot, "project.md"),
    ...manifest.artifactPaths.filter((filePath) => filePath.endsWith("tasks.md")),
  ];
  for (const filePath of trustedMarkdown) {
    try {
      checks.push(...commandsFromMarkdown(await readFile(filePath, "utf8"), filePath));
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
    }
  }

  const pyprojectPath = path.join(repositoryRoot, "pyproject.toml");
  try {
    const pyproject = await readFile(pyprojectPath, "utf8");
    if (/\[tool\.pytest/i.test(pyproject)) {
      checks.push({
        args: ["python", "-m", "pytest"],
        source: pyprojectPath,
        rationale: "pytest is configured for this repository.",
      });
    }
    if (/\[tool\.ruff/i.test(pyproject)) {
      checks.push({
        args: ["python", "-m", "ruff", "check", "."],
        source: pyprojectPath,
        rationale: "Ruff is configured for this repository.",
      });
    }
    if (/\[tool\.mypy/i.test(pyproject)) {
      checks.push({
        args: ["python", "-m", "mypy", "."],
        source: pyprojectPath,
        rationale: "mypy is configured for this repository.",
      });
    }
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }

  const deduplicated = new Map();
  for (const check of checks) {
    const key = JSON.stringify(check.args);
    if (!deduplicated.has(key)) {
      deduplicated.set(
        key,
        Object.freeze({
          id: `check:${deduplicated.size + 1}`,
          command: check.args[0],
          args: Object.freeze(check.args.slice(1)),
          source: check.source,
          rationale: check.rationale,
          required: true,
          timeoutMs: check.args[0] === "npm" && check.args.at(-1) === "build" ? 10 * 60_000 : 5 * 60_000,
        }),
      );
    }
  }
  return Object.freeze([...deduplicated.values()]);
}

function bounded(value, limit = 16 * 1024) {
  const redacted = redact(value ?? "");
  return redacted.length <= limit ? redacted : `${redacted.slice(0, limit)}\n[OUTPUT TRUNCATED]`;
}

export async function executeRequiredChecks(
  checks,
  { repositoryRoot = process.cwd(), runCommand = runProcess } = {},
) {
  const results = [];
  for (const check of checks) {
    if (check.applicable === false) {
      results.push(
        Object.freeze({
          checkId: check.id,
          command: check.command,
          args: check.args,
          required: check.required,
          state: "skipped",
          durationMs: 0,
          exitCode: null,
          stdout: "",
          stderr: "",
          reason: check.applicabilityReason ?? "Check marked inapplicable.",
        }),
      );
      continue;
    }
    const startedAt = Date.now();
    let processResult;
    try {
      processResult = await runCommand(check.command, [...check.args], {
        cwd: repositoryRoot,
        timeoutMs: check.timeoutMs,
        maxOutputBytes: 64 * 1024,
      });
    } catch (error) {
      if (error instanceof ProcessError || error?.code === "ENOENT") {
        results.push(
          Object.freeze({
            checkId: check.id,
            command: check.command,
            args: check.args,
            required: check.required,
            state: "blocked",
            durationMs: Date.now() - startedAt,
            exitCode: null,
            stdout: "",
            stderr: "",
            reason: `Unable to start required command ${check.command}.`,
          }),
        );
        continue;
      }
      throw error;
    }
    const state = processResult.timedOut
      ? "blocked"
      : processResult.exitCode === 0
        ? "passed"
        : "failed";
    results.push(
      Object.freeze({
        checkId: check.id,
        command: check.command,
        args: check.args,
        required: check.required,
        state,
        durationMs: processResult.durationMs ?? Date.now() - startedAt,
        exitCode: processResult.exitCode,
        stdout: bounded(processResult.stdout),
        stderr: bounded(processResult.stderr),
        reason: processResult.timedOut ? "Required check timed out." : null,
      }),
    );
  }
  const failedRequired = results.filter((result) => result.required && result.state !== "passed");
  return Object.freeze({
    passed: failedRequired.length === 0,
    results: Object.freeze(results),
    failedRequired: Object.freeze(failedRequired),
  });
}

export function validateStructuredVerification(value, manifest, checkSummary) {
  if (!value || typeof value !== "object" || value.schemaVersion !== 1) {
    throw new VerificationError("semantic_result_invalid", "Semantic verification schema version is missing or unsupported.");
  }
  if (!["passed", "failed"].includes(value.overallVerdict) || !Array.isArray(value.results)) {
    throw new VerificationError("semantic_result_invalid", "Semantic verification has an invalid verdict or results list.");
  }
  const manifestById = new Map(manifest.entries.map((entry) => [entry.id, entry]));
  const actualChecks = new Map(checkSummary.results.map((result) => [result.checkId, result]));
  const seen = new Set();
  for (const result of value.results) {
    if (!result || typeof result !== "object" || seen.has(result.id) || !manifestById.has(result.id)) {
      throw new VerificationError("semantic_result_coverage_invalid", `Unknown or duplicate semantic result id: ${result?.id}.`);
    }
    seen.add(result.id);
    if (!["passed", "failed", "not_applicable"].includes(result.verdict)) {
      throw new VerificationError("semantic_result_invalid", `Unknown semantic verdict for ${result.id}.`);
    }
    if (!Array.isArray(result.evidence) || !Array.isArray(result.commandEvidenceIds)) {
      throw new VerificationError("semantic_result_invalid", `Evidence arrays are required for ${result.id}.`);
    }
    if (result.verdict === "passed" && result.evidence.filter((entry) => typeof entry === "string" && entry.trim()).length === 0) {
      throw new VerificationError("semantic_result_evidence_missing", `Passing result ${result.id} has no concrete evidence.`);
    }
    if (result.verdict === "not_applicable") {
      const manifestEntry = manifestById.get(result.id);
      if (!manifestEntry.notApplicableAllowed || typeof result.rationale !== "string" || !result.rationale.trim()) {
        throw new VerificationError(
          "semantic_result_not_applicable_unsupported",
          `Result ${result.id} is not approved as not applicable.`,
        );
      }
    }
    for (const checkId of result.commandEvidenceIds) {
      const actual = actualChecks.get(checkId);
      if (!actual || actual.state !== "passed") {
        throw new VerificationError(
          "semantic_result_fabricated_command",
          `Result ${result.id} cites unavailable passing command ${checkId}.`,
        );
      }
    }
  }
  const missing = [...manifestById.keys()].filter((id) => !seen.has(id));
  if (missing.length) {
    throw new VerificationError("semantic_result_coverage_invalid", "Semantic verification omitted manifest entries.", {
      missing,
    });
  }
  const allPassed = value.results.every((result) => result.verdict === "passed");
  if (value.overallVerdict === "passed" && (!allPassed || !checkSummary.passed)) {
    throw new VerificationError(
      "semantic_result_global_conflict",
      "Global success conflicts with unmet criteria or non-passing required checks.",
    );
  }
  return Object.freeze({
    schemaVersion: 1,
    overallVerdict: value.overallVerdict,
    results: Object.freeze(value.results.map((result) => Object.freeze({ ...result }))),
    passed: value.overallVerdict === "passed" && allPassed && checkSummary.passed,
  });
}

export function reconcileVerification({ manifest, requiredChecks, checkSummary, semanticResult }) {
  if (manifest.tasks.some((task) => task.complete !== true)) {
    throw new VerificationError("verification_failed", "One or more required tasks are incomplete.");
  }
  const actualById = new Map(checkSummary.results.map((result) => [result.checkId, result]));
  for (const check of requiredChecks.filter((entry) => entry.required)) {
    const actual = actualById.get(check.id);
    if (!actual || actual.state !== "passed") {
      throw new VerificationError(
        actual ? "verification_failed" : "verification_check_missing",
        `Required check ${check.id} is missing or did not pass.`,
        { checkId: check.id, state: actual?.state },
      );
    }
  }
  const strictCheck = requiredChecks.find(
    (check) =>
      check.command === "openspec" &&
      check.args[0] === "validate" &&
      check.args.includes("--strict") &&
      check.args.includes("--json"),
  );
  if (!strictCheck || actualById.get(strictCheck.id)?.state !== "passed") {
    throw new VerificationError(
      "strict_validation_missing",
      "A passing strict OpenSpec validation event is required.",
    );
  }

  const semantic = validateStructuredVerification(semanticResult, manifest, checkSummary);
  if (!semantic.passed) {
    throw new VerificationError(
      "verification_failed",
      "Semantic verification did not pass every manifest entry.",
    );
  }
  return Object.freeze({
    kind: "VerifiedSynchronization",
    manifest,
    requiredChecks,
    checkSummary,
    semantic,
  });
}
