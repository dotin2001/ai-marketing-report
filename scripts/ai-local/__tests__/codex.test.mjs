import assert from "node:assert/strict";
import { chmod, mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import { runCodexPlanning } from "../codex.mjs";
import { buildPlanningPrompt } from "../planning-context.mjs";
import { ensureRuntimeLayout } from "../runtime.mjs";

test("Codex adapter invokes codex exec with stdin skill prompt and captures events/final output", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "ai-local-codex-"));
  const bin = path.join(root, "bin");
  await mkdir(bin);
  const observedPath = path.join(root, "observed.json");
  const executable = path.join(bin, "codex");
  await writeFile(
    executable,
    `#!/usr/bin/env node
const { writeFileSync } = require("node:fs");
const args = process.argv.slice(2);
let prompt = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => prompt += chunk);
process.stdin.on("end", () => {
  const outputIndex = args.indexOf("--output-last-message");
  writeFileSync(args[outputIndex + 1], "Proposal ready");
  writeFileSync(process.env.OBSERVED_PATH, JSON.stringify({ args, prompt }));
  process.stdout.write(JSON.stringify({ type: "turn.completed", usage: { input_tokens: 1 } }) + "\\n");
});
`,
  );
  await chmod(executable, 0o700);
  const runtimePaths = await ensureRuntimeLayout(path.join(root, ".ai-local"));
  const prompt = buildPlanningPrompt({ contextPath: path.join(root, "context.json"), changeId: "gh-42-safe" });
  const environment = {
    ...process.env,
    PATH: `${bin}${path.delimiter}${process.env.PATH}`,
    OBSERVED_PATH: observedPath,
  };

  const result = await runCodexPlanning({
    repositoryRoot: root,
    runtimePaths,
    prompt,
    attemptId: "attempt-one",
    environment,
  });
  const observed = JSON.parse(await readFile(observedPath, "utf8"));
  assert.equal(observed.args[0], "exec");
  assert.deepEqual(observed.args.slice(1, 5), ["--cd", root, "--sandbox", "workspace-write"]);
  assert.ok(observed.args.includes("--json"));
  assert.equal(observed.args.at(-1), "-");
  assert.match(observed.prompt, /Use the \$openspec-propose skill/);
  assert.doesNotMatch(observed.prompt, /\$openspec-apply-change/);
  assert.equal(result.finalOutput, "Proposal ready");
  assert.equal(result.events[0].type, "turn.completed");
  assert.match(await readFile(result.eventLogPath, "utf8"), /turn\.completed/);
});

test("Codex adapter reports timeout and redacts failure output", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "ai-local-codex-error-"));
  const runtimePaths = await ensureRuntimeLayout(path.join(root, ".ai-local"));
  await assert.rejects(
    () =>
      runCodexPlanning({
        repositoryRoot: root,
        runtimePaths,
        prompt: "safe",
        runCommand: async (_command, _args, options) => {
          await writeFile(options.args?.at?.(-2) ?? path.join(runtimePaths.tmp, "unused"), "").catch(() => {});
          return {
            exitCode: 1,
            timedOut: true,
            stdout: "",
            stderr: "gho_abcdefghijklmnopqrstuvwxyz",
          };
        },
      }),
    (error) => {
      assert.equal(error.code, "codex_timeout");
      assert.doesNotMatch(JSON.stringify(error), /gho_abcdefghijklmnopqrstuvwxyz/);
      return true;
    },
  );
});
