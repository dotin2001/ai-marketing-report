import assert from "node:assert/strict";
import { test } from "node:test";

import { PreflightError, ProcessError } from "../errors.mjs";
import { normalizeGitHubRepository, runPreflight } from "../preflight.mjs";
import { redact } from "../process.mjs";

const config = {
  repositoryRoot: "/repo",
  github: { repository: "dotin2001/ai-marketing-report" },
};

function fakeRunner(overrides = {}) {
  return async (command, args) => {
    const key = `${command} ${args.join(" ")}`;
    if (overrides[key] instanceof Error) throw overrides[key];
    if (overrides[key]) return overrides[key];
    if (key === "git remote get-url origin") {
      return ok("https://github.com/dotin2001/ai-marketing-report.git\n");
    }
    if (key === "git branch --show-current") return ok("feature/set_up\n");
    if (key === "git rev-parse HEAD") return ok("a".repeat(40));
    if (key === "gh auth status") return ok("");
    return ok(`${command} 1.0`);
  };
}

function ok(stdout = "") {
  return { exitCode: 0, stdout, stderr: "", timedOut: false };
}

test("normalizes supported GitHub remote URLs", () => {
  for (const remote of [
    "https://github.com/dotin2001/ai-marketing-report.git",
    "git@github.com:dotin2001/ai-marketing-report.git",
    "ssh://git@github.com/dotin2001/ai-marketing-report.git",
    "git://github.com/dotin2001/ai-marketing-report.git",
  ]) {
    assert.equal(normalizeGitHubRepository(remote), "dotin2001/ai-marketing-report");
  }
});

test("preflight validates tools, configured remote, branch, head, and auth", async () => {
  const result = await runPreflight(config, { runCommand: fakeRunner() });
  assert.equal(result.repository, "dotin2001/ai-marketing-report");
  assert.equal(result.branch, "feature/set_up");
  assert.equal(result.head, "a".repeat(40));
});

test("preflight rejects repository mismatch with both identities", async () => {
  await assert.rejects(
    () =>
      runPreflight(config, {
        runCommand: fakeRunner({
          "git remote get-url origin": ok("git@github.com:someone/fork.git"),
        }),
      }),
    (error) => {
      assert.equal(error.code, "repository_mismatch");
      assert.match(error.message, /dotin2001\/ai-marketing-report/);
      assert.match(error.message, /someone\/fork/);
      return true;
    },
  );
});

test("preflight reports missing tools", async () => {
  await assert.rejects(
    () =>
      runPreflight(config, {
        runCommand: fakeRunner({
          "codex --version": new ProcessError("spawn failed", { causeCode: "ENOENT" }),
        }),
      }),
    (error) => error instanceof PreflightError && error.code === "missing_prerequisite",
  );
});

test("preflight reports timeouts", async () => {
  await assert.rejects(
    () =>
      runPreflight(config, {
        runCommand: fakeRunner({
          "openspec --version": { ...ok(), timedOut: true },
        }),
      }),
    (error) => error.code === "preflight_timeout",
  );
});

test("invalid authentication is redacted", async () => {
  const token = "gho_abcdefghijklmnopqrstuvwxyz";
  await assert.rejects(
    () =>
      runPreflight(config, {
        runCommand: fakeRunner({
          "gh auth status": { exitCode: 1, stdout: "", stderr: `bad ${token}`, timedOut: false },
        }),
      }),
    (error) => {
      assert.equal(error.code, "authentication_failed");
      assert.doesNotMatch(JSON.stringify(error), new RegExp(token));
      return true;
    },
  );
  assert.equal(redact(`token=${token}`), "token=[REDACTED]");
});
