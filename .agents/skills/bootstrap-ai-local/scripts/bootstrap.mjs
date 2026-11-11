#!/usr/bin/env node

import { randomUUID } from "node:crypto";
import { mkdir, readFile, readdir, rename, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath, pathToFileURL } from "node:url";

const skillRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const templateRoot = path.join(skillRoot, "assets", "template");
const bootstrapScript = fileURLToPath(import.meta.url);
const packageManagers = new Set(["npm", "pnpm", "yarn", "bun"]);
const verificationExecutables = new Set([
  "npm", "pnpm", "yarn", "bun", "node", "npx", "python", "python3", "pytest",
  "ruff", "mypy", "alembic", "openspec", "cargo", "go", "make", "cmake",
  "ctest", "gradle", "mvn", "dotnet",
]);
const reservedScripts = Object.freeze({
  "ai:local": "node scripts/ai-local.mjs",
  "ai:local:test": "node --test scripts/ai-local/__tests__/*.test.mjs",
  "ai:local:check": "node scripts/ai-local/check.mjs",
});

const HELP = `Usage:
  node <skill>/scripts/bootstrap.mjs --mode inspect --target <repository>
  node <skill>/scripts/bootstrap.mjs --mode preview --target <repository> [settings]
  node <skill>/scripts/bootstrap.mjs --mode apply --target <repository> [settings]

Required settings for preview/apply:
  --repository <owner/name>
  --project-owner <owner>
  --project-number <positive-integer>

Optional settings:
  --status-field <name>             Default: Status
  --todo-option <name>              Default: Todo
  --done-option <name>              Default: Done
  --package-manager <name>          npm, pnpm, yarn, or bun; otherwise detected
  --verification-command <json>     Repeatable argv JSON, e.g. '["npm","test"]'
  --no-auto-discover                Run only strict OpenSpec validation plus explicit checks
  --help                            Show this text
`;

function fail(message, details = {}) {
  const error = new Error(message);
  error.details = details;
  throw error;
}

function parseArguments(args) {
  const seen = new Set();
  const options = {
    mode: null,
    target: null,
    statusField: "Status",
    todoOption: "Todo",
    doneOption: "Done",
    autoDiscover: true,
    verificationCommands: [],
  };
  for (let index = 0; index < args.length; index += 1) {
    const argument = args[index];
    if (argument === "--help" || argument === "-h") return { help: true };
    if (argument === "--no-auto-discover") {
      options.autoDiscover = false;
      continue;
    }
    const value = args[index + 1];
    if (!value || value.startsWith("--")) fail(`${argument} requires a value.`);
    const fields = {
      "--mode": "mode",
      "--target": "target",
      "--repository": "repository",
      "--project-owner": "projectOwner",
      "--project-number": "projectNumber",
      "--status-field": "statusField",
      "--todo-option": "todoOption",
      "--done-option": "doneOption",
      "--package-manager": "packageManager",
    };
    if (fields[argument]) {
      if (seen.has(argument)) fail(`${argument} may be provided only once.`);
      seen.add(argument);
      options[fields[argument]] = value;
      index += 1;
      continue;
    }
    if (argument === "--verification-command") {
      let command;
      try {
        command = JSON.parse(value);
      } catch {
        fail("--verification-command must be a JSON argv array.");
      }
      options.verificationCommands.push(command);
      index += 1;
      continue;
    }
    fail(`Unknown argument: ${argument}`);
  }

  if (!new Set(["inspect", "preview", "apply"]).has(options.mode)) {
    fail("--mode must be inspect, preview, or apply.");
  }
  if (!options.target) fail("--target is required.");
  options.target = path.resolve(options.target);
  if (options.mode !== "inspect") {
    for (const field of ["repository", "projectOwner", "projectNumber"]) {
      if (!options[field]) fail(`--${field.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`)} is required.`);
    }
    options.projectNumber = Number(options.projectNumber);
    if (!Number.isSafeInteger(options.projectNumber) || options.projectNumber <= 0) {
      fail("--project-number must be a positive integer.");
    }
    if (!/^[A-Za-z0-9][A-Za-z0-9_.-]*\/[A-Za-z0-9_.-]+$/.test(options.repository)) {
      fail("--repository must be an owner/name identity.");
    }
    if (!/^[A-Za-z0-9][A-Za-z0-9-]*$/.test(options.projectOwner)) {
      fail("--project-owner is malformed.");
    }
    for (const field of ["statusField", "todoOption", "doneOption"]) {
      if (!options[field] || options[field].trim() !== options[field]) fail(`${field} must be an exact non-empty name.`);
    }
    if (options.todoOption === options.doneOption) fail("Todo and Done option names must differ.");
  }
  return options;
}

async function exists(filePath) {
  try {
    await stat(filePath);
    return true;
  } catch (error) {
    if (error.code === "ENOENT") return false;
    throw error;
  }
}

async function readTextIfPresent(filePath) {
  try {
    return await readFile(filePath, "utf8");
  } catch (error) {
    if (error.code === "ENOENT") return null;
    throw error;
  }
}

async function readJsonIfPresent(filePath) {
  const text = await readTextIfPresent(filePath);
  if (text === null) return null;
  try {
    return JSON.parse(text);
  } catch {
    fail(`Existing JSON is malformed: ${filePath}`);
  }
}

async function walkFiles(root, relative = "") {
  const directory = path.join(root, relative);
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries.sort((left, right) => left.name.localeCompare(right.name))) {
    const child = path.join(relative, entry.name);
    if (entry.isDirectory()) files.push(...(await walkFiles(root, child)));
    else if (entry.isFile()) files.push(child);
  }
  return files;
}

async function detectPackageManager(target, packageJson = {}) {
  const declared = String(packageJson.packageManager ?? "").split("@")[0];
  if (packageManagers.has(declared)) return { name: declared, source: "package.json#packageManager" };
  for (const [file, name] of [
    ["pnpm-lock.yaml", "pnpm"],
    ["yarn.lock", "yarn"],
    ["bun.lock", "bun"],
    ["bun.lockb", "bun"],
    ["package-lock.json", "npm"],
    ["npm-shrinkwrap.json", "npm"],
  ]) {
    if (await exists(path.join(target, file))) return { name, source: file };
  }
  return { name: "npm", source: "default" };
}

function packageScriptCommand(packageManager, script) {
  if (packageManager === "npm" && script === "test") return ["npm", "test"];
  return [packageManager, "run", script];
}

async function ciFiles(target) {
  const results = [];
  const workflows = path.join(target, ".github", "workflows");
  if (await exists(workflows)) {
    for (const entry of await readdir(workflows, { withFileTypes: true })) {
      if (entry.isFile() && /\.ya?ml$/i.test(entry.name)) results.push(path.join(".github", "workflows", entry.name));
    }
  }
  for (const candidate of [".gitlab-ci.yml", "azure-pipelines.yml", "bitbucket-pipelines.yml", "Jenkinsfile", ".circleci/config.yml"]) {
    if (await exists(path.join(target, candidate))) results.push(candidate);
  }
  return results.sort();
}

async function detectVerificationCommands(target, packageJson, packageManager) {
  const commands = [];
  for (const script of ["test", "check", "lint", "typecheck", "type-check", "build"]) {
    if (typeof packageJson.scripts?.[script] === "string" && !script.startsWith("ai:local")) {
      commands.push(packageScriptCommand(packageManager, script));
    }
  }
  const pyproject = await readTextIfPresent(path.join(target, "pyproject.toml"));
  if (pyproject && /\[tool\.pytest/i.test(pyproject)) commands.push(["python", "-m", "pytest"]);
  if (pyproject && /\[tool\.ruff/i.test(pyproject)) commands.push(["python", "-m", "ruff", "check", "."]);
  if (pyproject && /\[tool\.mypy/i.test(pyproject)) commands.push(["python", "-m", "mypy", "."]);
  if (await exists(path.join(target, "Cargo.toml"))) commands.push(["cargo", "test"]);
  if (await exists(path.join(target, "go.mod"))) commands.push(["go", "test", "./..."]);
  if (await exists(path.join(target, "Makefile"))) {
    const makefile = await readTextIfPresent(path.join(target, "Makefile"));
    if (/^test\s*:/m.test(makefile)) commands.push(["make", "test"]);
  }
  const deduplicated = new Map(commands.map((command) => [JSON.stringify(command), command]));
  return [...deduplicated.values()];
}

function validateVerificationCommands(commands) {
  return commands.map((argv, index) => {
    if (!Array.isArray(argv) || argv.length === 0 || argv.some((value) => typeof value !== "string" || /[\0\r\n]/.test(value))) {
      fail(`Verification command ${index + 1} must be a non-empty JSON string array.`);
    }
    if (!verificationExecutables.has(argv[0])) {
      fail(`Verification executable is not allowed: ${argv[0]}`);
    }
    return Object.freeze([...argv]);
  });
}

async function inspectTarget(target) {
  const targetStat = await stat(target).catch(() => null);
  if (!targetStat?.isDirectory()) fail(`Target repository does not exist: ${target}`);
  const packageJson = (await readJsonIfPresent(path.join(target, "package.json"))) ?? {};
  const packageManager = await detectPackageManager(target, packageJson);
  const topLevel = (await readdir(target, { withFileTypes: true }))
    .map((entry) => `${entry.isDirectory() ? "directory" : "file"}:${entry.name}`)
    .sort();
  const workflowPaths = [
    "scripts/ai-local.mjs",
    "scripts/ai-local",
    "ai-local.config.json",
    "docs/ai-local-workflow.md",
    ".github/ISSUE_TEMPLATE/ai-local-task.md",
  ];
  const existingWorkflow = [];
  for (const candidate of workflowPaths) {
    if (await exists(path.join(target, candidate))) existingWorkflow.push(candidate);
  }
  const changesPath = path.join(target, "openspec", "changes");
  const activeChanges = (await exists(changesPath))
    ? (await readdir(changesPath, { withFileTypes: true })).filter((entry) => entry.isDirectory()).map((entry) => entry.name).sort()
    : [];
  return Object.freeze({
    target,
    topLevel,
    packageManager,
    ciFiles: await ciFiles(target),
    verificationCandidates: await detectVerificationCommands(target, packageJson, packageManager.name),
    openspec: Object.freeze({
      configured: await exists(path.join(target, "openspec", "config.yaml")),
      activeChanges,
    }),
    existingWorkflow,
    packageScripts: packageJson.scripts ?? {},
  });
}

function shellQuote(value) {
  return `'${String(value).replaceAll("'", `'"'"'`)}'`;
}

function buildSettings(options, inspection) {
  const packageManager = options.packageManager ?? inspection.packageManager.name;
  if (!packageManagers.has(packageManager)) fail("Unsupported package manager.");
  const detected = options.verificationCommands.length
    ? options.verificationCommands
    : inspection.verificationCandidates;
  const commands = validateVerificationCommands(detected);
  return Object.freeze({ ...options, packageManager, verificationCommands: Object.freeze(commands) });
}

function previewInvocation(settings) {
  const parts = [
    "node", shellQuote(bootstrapScript), "--mode", "preview", "--target", ".",
    "--repository", shellQuote(settings.repository),
    "--project-owner", shellQuote(settings.projectOwner),
    "--project-number", String(settings.projectNumber),
    "--status-field", shellQuote(settings.statusField),
    "--todo-option", shellQuote(settings.todoOption),
    "--done-option", shellQuote(settings.doneOption),
    "--package-manager", settings.packageManager,
  ];
  if (!settings.autoDiscover) parts.push("--no-auto-discover");
  for (const argv of settings.verificationCommands) {
    parts.push("--verification-command", shellQuote(JSON.stringify(argv)));
  }
  return parts.join(" ");
}

function replacements(settings) {
  const run = `${settings.packageManager} run ai:local`;
  return Object.freeze({
    "{{REPOSITORY}}": settings.repository,
    "{{PROJECT_OWNER}}": settings.projectOwner,
    "{{PROJECT_NUMBER}}": String(settings.projectNumber),
    "{{STATUS_FIELD}}": settings.statusField,
    "{{TODO_OPTION}}": settings.todoOption,
    "{{DONE_OPTION}}": settings.doneOption,
    "{{PACKAGE_MANAGER}}": settings.packageManager,
    "{{RUN_COMMAND}}": run,
    "{{BOOTSTRAP_SCRIPT}}": shellQuote(bootstrapScript),
    "{{PREVIEW_COMMAND}}": previewInvocation(settings),
  });
}

function render(text, values) {
  let rendered = text;
  for (const [token, value] of Object.entries(values)) rendered = rendered.replaceAll(token, value);
  return rendered;
}

function configuration(settings) {
  return {
    github: {
      repository: settings.repository,
      projectOwner: settings.projectOwner,
      projectNumber: settings.projectNumber,
      statusField: settings.statusField,
      todoOption: settings.todoOption,
      doneOption: settings.doneOption,
    },
    packageManager: settings.packageManager,
    verification: {
      autoDiscover: settings.autoDiscover,
      commands: settings.verificationCommands.map(([command, ...args]) => ({
        command,
        args,
        timeoutMs: args.at(-1) === "build" ? 600000 : 300000,
      })),
    },
    runtimeDirectory: ".ai-local",
  };
}

async function atomicWrite(destination, content) {
  await mkdir(path.dirname(destination), { recursive: true });
  const temporary = path.join(path.dirname(destination), `.${path.basename(destination)}.${randomUUID()}.partial`);
  await writeFile(temporary, content, { encoding: "utf8", mode: 0o644, flag: "wx" });
  await rename(temporary, destination);
}

async function buildPlan(settings, inspection) {
  if (!inspection.openspec.configured) {
    fail("Target has no openspec/config.yaml. Initialize OpenSpec before scaffolding.", {
      suggestedCommand: "openspec init .",
    });
  }
  const desired = new Map();
  const values = replacements(settings);
  for (const relativePath of await walkFiles(templateRoot)) {
    const source = path.join(templateRoot, relativePath);
    desired.set(relativePath, render(await readFile(source, "utf8"), values));
  }
  desired.set("ai-local.config.json", `${JSON.stringify(configuration(settings), null, 2)}\n`);

  const packagePath = path.join(settings.target, "package.json");
  const packageJson = (await readJsonIfPresent(packagePath)) ?? {
    name: path.basename(settings.target).toLowerCase().replace(/[^a-z0-9._-]+/g, "-") || "ai-local-target",
    private: true,
  };
  packageJson.scripts ??= {};
  const conflicts = [];
  for (const [name, command] of Object.entries(reservedScripts)) {
    if (packageJson.scripts[name] && packageJson.scripts[name] !== command) {
      conflicts.push({ path: "package.json", reason: `scripts.${name} is already ${JSON.stringify(packageJson.scripts[name])}` });
    } else {
      packageJson.scripts[name] = command;
    }
  }
  packageJson.engines ??= {};
  packageJson.engines.node ??= ">=22";
  desired.set("package.json", `${JSON.stringify(packageJson, null, 2)}\n`);

  const gitignorePath = path.join(settings.target, ".gitignore");
  const existingGitignore = (await readTextIfPresent(gitignorePath)) ?? "";
  const gitignoreLines = existingGitignore.split(/\r?\n/);
  const gitignore = gitignoreLines.includes(".ai-local/")
    ? existingGitignore
    : `${existingGitignore}${existingGitignore && !existingGitignore.endsWith("\n") ? "\n" : ""}.ai-local/\n`;
  desired.set(".gitignore", gitignore);

  const actions = [];
  const mergeable = new Set(["package.json", ".gitignore"]);
  for (const [relativePath, content] of [...desired.entries()].sort(([left], [right]) => left.localeCompare(right))) {
    const destination = path.join(settings.target, relativePath);
    const existing = await readTextIfPresent(destination);
    if (existing === null) actions.push({ kind: "create", path: relativePath, content });
    else if (existing === content) actions.push({ kind: "reuse", path: relativePath, content });
    else if (mergeable.has(relativePath)) actions.push({ kind: "update", path: relativePath, content });
    else conflicts.push({ path: relativePath, reason: "existing content differs from the portable template" });
  }
  return Object.freeze({ actions: Object.freeze(actions), conflicts: Object.freeze(conflicts) });
}

function publicPlan(plan) {
  return {
    creates: plan.actions.filter((entry) => entry.kind === "create").map((entry) => entry.path),
    updates: plan.actions.filter((entry) => entry.kind === "update").map((entry) => entry.path),
    reuses: plan.actions.filter((entry) => entry.kind === "reuse").map((entry) => entry.path),
    conflicts: plan.conflicts,
  };
}

async function applyPlan(plan, target) {
  if (plan.conflicts.length) fail("Scaffold has incompatible target files; nothing was written.", { conflicts: plan.conflicts });
  for (const action of plan.actions) {
    if (action.kind === "reuse") continue;
    await atomicWrite(path.join(target, action.path), action.content);
  }
}

export async function run(args = process.argv.slice(2)) {
  const options = parseArguments(args);
  if (options.help) return { kind: "help", text: HELP };
  const inspection = await inspectTarget(options.target);
  if (options.mode === "inspect") return { kind: "inspection", inspection };
  const settings = buildSettings(options, inspection);
  const plan = await buildPlan(settings, inspection);
  const result = {
    kind: options.mode === "apply" ? "applied" : "preview",
    inspection,
    settings: {
      repository: settings.repository,
      projectOwner: settings.projectOwner,
      projectNumber: settings.projectNumber,
      statusField: settings.statusField,
      todoOption: settings.todoOption,
      doneOption: settings.doneOption,
      packageManager: settings.packageManager,
      autoDiscover: settings.autoDiscover,
      verificationCommands: settings.verificationCommands,
    },
    plan: publicPlan(plan),
    commands: {
      preview: previewInvocation(settings),
      plan: `${settings.packageManager} run ai:local`,
      planIssue: `${settings.packageManager} run ai:local -- --issue <github-issue-url>`,
      apply: "$openspec-apply-change <change-id>",
      verify: [`${settings.packageManager} run ai:local:test`, `${settings.packageManager} run ai:local:check`],
      sync: `${settings.packageManager} run ai:local -- --sync-task`,
      syncChange: `${settings.packageManager} run ai:local -- --sync-task --change <change-id>`,
    },
  };
  if (options.mode === "apply") await applyPlan(plan, settings.target);
  return result;
}

async function main() {
  try {
    const result = await run();
    if (result.kind === "help") process.stdout.write(result.text);
    else process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
    if (result.plan?.conflicts?.length) process.exitCode = 2;
  } catch (error) {
    process.stderr.write(`${JSON.stringify({ error: "bootstrap_ai_local_failed", message: error.message, details: error.details ?? null }, null, 2)}\n`);
    process.exitCode = 2;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  await main();
}
