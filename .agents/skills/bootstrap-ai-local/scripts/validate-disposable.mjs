#!/usr/bin/env node

import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, readdir, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

import { run as runBootstrap } from "./bootstrap.mjs";

async function filesBelow(root, relative = "") {
  const files = [];
  for (const entry of await readdir(path.join(root, relative), { withFileTypes: true })) {
    const child = path.join(relative, entry.name);
    if (entry.isDirectory()) files.push(...(await filesBelow(root, child)));
    else if (entry.isFile()) files.push(child);
  }
  return files.sort();
}

function execute(command, args, cwd) {
  const result = spawnSync(command, args, { cwd, encoding: "utf8", shell: false });
  if (result.status !== 0) {
    throw new Error(`${command} ${args.join(" ")} failed\n${result.stdout}\n${result.stderr}`);
  }
  return { stdout: result.stdout, stderr: result.stderr };
}

const target = await mkdtemp(path.join(os.tmpdir(), "bootstrap-ai-local-validation-"));
const keep = process.argv.includes("--keep");
let summary;
try {
  await mkdir(path.join(target, "openspec", "changes"), { recursive: true });
  await writeFile(path.join(target, "openspec", "config.yaml"), "schema: spec-driven\n", "utf8");
  await writeFile(
    path.join(target, "package.json"),
    `${JSON.stringify({
      name: "disposable-ai-local-validation",
      private: true,
      type: "module",
      scripts: { test: "node --test" },
      packageManager: "npm@10.9.0",
    }, null, 2)}\n`,
    "utf8",
  );
  await writeFile(path.join(target, "package-lock.json"), "{}\n", "utf8");
  await writeFile(path.join(target, "AGENTS.md"), "Run `npm test` for repository verification.\n", "utf8");
  execute("git", ["init", "--quiet"], target);

  const inspect = await runBootstrap(["--mode", "inspect", "--target", target]);
  assert.equal(inspect.inspection.packageManager.name, "npm");
  assert.equal(inspect.inspection.openspec.configured, true);
  assert.deepEqual(inspect.inspection.verificationCandidates, [["npm", "test"]]);

  const arguments_ = [
    "--target", target,
    "--repository", "example-org/disposable-repository",
    "--project-owner", "example-org",
    "--project-number", "9",
    "--status-field", "Workflow",
    "--todo-option", "Ready",
    "--done-option", "Complete",
    "--package-manager", "npm",
    "--verification-command", JSON.stringify(["npm", "test"]),
  ];
  const preview = await runBootstrap(["--mode", "preview", ...arguments_]);
  assert.equal(preview.plan.conflicts.length, 0);
  assert.ok(preview.plan.creates.includes("scripts/ai-local.mjs"));
  assert.equal(await readFile(path.join(target, "package.json"), "utf8").then((value) => value.includes("ai:local")), false);

  const applied = await runBootstrap(["--mode", "apply", ...arguments_]);
  assert.equal(applied.plan.conflicts.length, 0);
  const config = JSON.parse(await readFile(path.join(target, "ai-local.config.json"), "utf8"));
  assert.equal(config.github.repository, "example-org/disposable-repository");
  assert.equal(config.github.statusField, "Workflow");
  assert.equal(config.github.todoOption, "Ready");
  assert.equal(config.github.doneOption, "Complete");
  assert.deepEqual(config.verification.commands[0].args, ["test"]);

  const issueTemplate = await readFile(path.join(target, ".github", "ISSUE_TEMPLATE", "ai-local-task.md"), "utf8");
  assert.match(issueTemplate, /^## Acceptance Criteria$/m);
  assert.match(issueTemplate, /^- .+/m);

  const testFiles = (await filesBelow(path.join(target, "scripts", "ai-local", "__tests__")))
    .filter((entry) => entry.endsWith(".test.mjs"))
    .map((entry) => path.join("scripts", "ai-local", "__tests__", entry));
  const focused = execute(process.execPath, ["--test", "scripts/ai-local/__tests__/planning-workflow.test.mjs", "scripts/ai-local/__tests__/sync-workflow.test.mjs"], target);
  assert.match(focused.stdout, /planning journey validates and links a proposal, then stops for review/);
  assert.match(focused.stdout, /failed checks stops before mutation/);
  assert.match(focused.stdout, /blocked infrastructure stops before mutation/);
  assert.match(focused.stdout, /successful CLI journey changes only the selected Todo item to Done/);

  const full = execute(process.execPath, ["--test", ...testFiles], target);
  const syntax = execute(process.execPath, ["scripts/ai-local/check.mjs"], target);
  assert.match(full.stdout, /# fail 0/);
  assert.match(syntax.stdout, /Syntax checked/);

  const second = await runBootstrap(["--mode", "apply", ...arguments_]);
  assert.equal(second.plan.conflicts.length, 0);
  assert.equal(second.plan.creates.length, 0);
  assert.equal(second.plan.updates.length, 0);

  const entryPoint = path.join(target, "scripts", "ai-local.mjs");
  const original = await readFile(entryPoint, "utf8");
  await writeFile(entryPoint, `${original}\n// incompatible local change\n`, "utf8");
  const conflict = await runBootstrap(["--mode", "preview", ...arguments_]);
  assert.ok(conflict.plan.conflicts.some((entry) => entry.path === "scripts/ai-local.mjs"));
  assert.match(await readFile(entryPoint, "utf8"), /incompatible local change/);

  summary = {
    disposableRepository: target,
    liveGitHubCalls: 0,
    planningBoundary: "passed",
    failedCheckMutationCount: 0,
    blockedCheckMutationCount: 0,
    passingStatusDecision: "Complete",
    fullTestFiles: testFiles.length,
    syntax: syntax.stdout.trim(),
    compatibleSecondApply: "reused",
    incompatibleFileHandling: "conflict-without-overwrite",
  };
  process.stdout.write(`${JSON.stringify(summary, null, 2)}\n`);
} finally {
  if (!keep) await rm(target, { recursive: true, force: true });
  else process.stderr.write(`Kept disposable repository at ${target}\n`);
}
