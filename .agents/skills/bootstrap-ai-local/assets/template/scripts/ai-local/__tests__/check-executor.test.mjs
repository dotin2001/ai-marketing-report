import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
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

test("backend profiles receive a child-only test environment", async () => {
  const parent = { APP_ENV: "local", KEEP: "yes" };
  const observed = [];
  await executeRequiredChecks([
    check("neutral", { executionProfile: "neutral", capabilities: { backendTest: false, postgresql: false } }),
    check("backend", { executionProfile: "backend-test", capabilities: { backendTest: true, postgresql: false } }),
  ], {
    environment: parent,
    runCommand: async (_command, args, options) => {
      observed.push({ id: args[0], env: options.env });
      return { exitCode: 0, timedOut: false, stdout: "", stderr: "" };
    },
  });

  assert.deepEqual(parent, { APP_ENV: "local", KEEP: "yes" });
  assert.deepEqual(observed[0].env, parent);
  assert.equal(observed[1].env.APP_ENV, "test");
  assert.equal(observed[1].env.AI_LOCAL_DISABLE_DOTENV, "1");
  assert.equal(observed[1].env.KEEP, "yes");
});

test("PostgreSQL preflight runs once and blocks all applicable checks safely", async () => {
  let probes = 0;
  let commands = 0;
  const summary = await executeRequiredChecks([
    check("db-one", { executionProfile: "postgresql", capabilities: { backendTest: true, postgresql: true } }),
    check("db-two", { executionProfile: "postgresql", capabilities: { backendTest: true, postgresql: true } }),
  ], {
    preflightPostgres: async () => {
      probes += 1;
      return { passed: false, code: "postgres_permission_denied", message: "TEST_DATABASE_URL: permission denied." };
    },
    runCommand: async () => { commands += 1; },
  });

  assert.equal(probes, 1);
  assert.equal(commands, 0);
  assert.deepEqual(summary.results.map((entry) => entry.reasonCode), [
    "postgres_permission_denied",
    "postgres_permission_denied",
  ]);
});

test("an executed PostgreSQL assertion failure remains failed", async () => {
  const databaseUrl = "postgresql+psycopg://user:recognizable_password@localhost/workflow_test";
  const summary = await executeRequiredChecks([
    check("database", { executionProfile: "postgresql", capabilities: { backendTest: true, postgresql: true } }),
  ], {
    preflightPostgres: async () => ({ passed: true }),
    runCommand: async () => ({ exitCode: 1, timedOut: false, stdout: "", stderr: `assertion failed for ${databaseUrl}` }),
  });
  assert.equal(summary.results[0].state, "failed");
  assert.equal(summary.results[0].reasonCode, "test_assertion_failed");
  assert.equal(summary.results[0].exitCode, 1);
  assert.doesNotMatch(summary.results[0].stderr, /recognizable_password|postgresql\+psycopg/);
});

test("caller-local backend check leaves an existing dotenv file untouched", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "ai-local-dotenv-preserve-"));
  const backend = path.join(root, "backend");
  const dotenv = path.join(backend, ".env");
  await mkdir(backend);
  await writeFile(dotenv, "APP_ENV=local\nDATABASE_URL=postgresql://local-only\n");
  const before = await readFile(dotenv, "utf8");
  let childEnvironment;

  await executeRequiredChecks([
    check("backend", { executionProfile: "backend-test", capabilities: { backendTest: true, postgresql: false } }),
  ], {
    repositoryRoot: root,
    environment: { APP_ENV: "local" },
    runCommand: async (_command, _args, options) => {
      childEnvironment = options.env;
      return { exitCode: 0, timedOut: false, stdout: "", stderr: "" };
    },
  });

  assert.equal(childEnvironment.APP_ENV, "test");
  assert.equal(childEnvironment.AI_LOCAL_DISABLE_DOTENV, "1");
  assert.equal(await readFile(dotenv, "utf8"), before);
});
