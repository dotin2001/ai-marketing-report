import assert from "node:assert/strict";
import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import { ProcessError } from "../errors.mjs";
import { executeRequiredChecks } from "../verification.mjs";

function check(id, overrides = {}) {
  return {
    id,
    command: "tool",
    args: [id],
    required: true,
    timeoutMs: 1000,
    ...overrides,
  };
}

test("executor captures argument arrays, duration, exit, bounded redacted output, and states", async () => {
  const token = "gho_abcdefghijklmnopqrstuvwxyz";
  const observed = [];
  const checks = [
    check("pass"),
    check("fail"),
    check("timeout"),
    check("missing"),
    check("skip", { applicable: false }),
  ];
  const summary = await executeRequiredChecks(checks, {
    repositoryRoot: "/repo",
    runCommand: async (command, args, options) => {
      observed.push({ command, args, options });
      if (args[0] === "missing") throw new ProcessError("missing", { causeCode: "ENOENT" });
      return {
        exitCode: args[0] === "fail" ? 1 : 0,
        timedOut: args[0] === "timeout",
        durationMs: 12,
        stdout: `${token}\n${"x".repeat(20_000)}`,
        stderr: "diagnostic",
      };
    },
  });

  assert.deepEqual(summary.results.map((result) => result.state), [
    "passed",
    "failed",
    "blocked",
    "blocked",
    "skipped",
  ]);
  assert.equal(summary.passed, false);
  assert.equal(summary.failedRequired.length, 4);
  assert.equal(observed.length, 4);
  assert.deepEqual(observed[0].args, ["pass"]);
  assert.equal(observed[0].options.cwd, "/repo");
  assert.doesNotMatch(summary.results[0].stdout, new RegExp(token));
  assert.match(summary.results[0].stdout, /OUTPUT TRUNCATED/);
  assert.equal(summary.results[0].durationMs, 12);
});

test("every non-passed required state fails while optional skip does not", async () => {
  const optionalOnly = await executeRequiredChecks(
    [check("optional", { required: false, applicable: false })],
    { runCommand: async () => assert.fail("should not run") },
  );
  assert.equal(optionalOnly.passed, true);

  for (const state of ["failed", "blocked", "skipped"]) {
    const summary = await executeRequiredChecks(
      [check(state, state === "skipped" ? { applicable: false } : {})],
      {
        runCommand: async () => ({
          exitCode: state === "failed" ? 1 : 0,
          timedOut: state === "blocked",
          stdout: "",
          stderr: "",
        }),
      },
    );
    assert.equal(summary.passed, false, state);
  }
});

test("failed checks preserve unrelated worktree files", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "ai-local-check-preserve-"));
  const unrelated = path.join(root, "unrelated.txt");
  await writeFile(unrelated, "user work");
  await executeRequiredChecks([check("fail")], {
    repositoryRoot: root,
    runCommand: async () => ({ exitCode: 1, timedOut: false, stdout: "", stderr: "failed" }),
  });
  assert.equal(await readFile(unrelated, "utf8"), "user work");
});
