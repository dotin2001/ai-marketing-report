import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import {
  fingerprintIdentity,
  fingerprintIssueRequirements,
  fingerprintRequiredChecks,
  fingerprintSpecifications,
  fingerprintWorktree,
} from "../fingerprint.mjs";

function git(root, args) {
  const result = spawnSync("git", args, { cwd: root, encoding: "utf8" });
  assert.equal(result.status, 0, result.stderr);
}

async function repositoryFixture() {
  const root = await mkdtemp(path.join(os.tmpdir(), "ai-local-fingerprint-"));
  git(root, ["init", "-q"]);
  git(root, ["config", "user.email", "test@example.com"]);
  git(root, ["config", "user.name", "Test"]);
  await writeFile(path.join(root, ".gitignore"), ".ai-local/\nignored-cache/\n");
  await writeFile(path.join(root, "tracked.txt"), "one\n");
  git(root, ["add", ".gitignore", "tracked.txt"]);
  git(root, ["commit", "-qm", "initial"]);
  return root;
}

test("worktree fingerprint detects tracked, staged, unstaged, and non-ignored untracked changes", async () => {
  const root = await repositoryFixture();
  const initial = await fingerprintWorktree({ repositoryRoot: root });

  await writeFile(path.join(root, "tracked.txt"), "unstaged\n");
  const unstaged = await fingerprintWorktree({ repositoryRoot: root });
  assert.notEqual(unstaged.digest, initial.digest);

  git(root, ["add", "tracked.txt"]);
  const staged = await fingerprintWorktree({ repositoryRoot: root });
  assert.notEqual(staged.digest, unstaged.digest, "index identity is fingerprinted separately");

  await writeFile(path.join(root, "tracked.txt"), "staged plus working change\n");
  const stagedAndUnstaged = await fingerprintWorktree({ repositoryRoot: root });
  assert.notEqual(stagedAndUnstaged.digest, staged.digest);

  await writeFile(path.join(root, "untracked.txt"), "new\n");
  const untracked = await fingerprintWorktree({ repositoryRoot: root });
  assert.notEqual(untracked.digest, stagedAndUnstaged.digest);
});

test("worktree fingerprint excludes only runtime and Git-ignored generated files", async () => {
  const root = await repositoryFixture();
  const initial = await fingerprintWorktree({ repositoryRoot: root });
  await mkdir(path.join(root, ".ai-local"));
  await writeFile(path.join(root, ".ai-local", "evidence.json"), "runtime");
  await mkdir(path.join(root, "ignored-cache"));
  await writeFile(path.join(root, "ignored-cache", "cache.bin"), "cache");
  const ignored = await fingerprintWorktree({ repositoryRoot: root });
  assert.equal(ignored.digest, initial.digest);

  await writeFile(path.join(root, "relevant.bin"), "relevant");
  const relevant = await fingerprintWorktree({ repositoryRoot: root });
  assert.notEqual(relevant.digest, ignored.digest);
});

test("fingerprint detects a required check editing a tracked file", async () => {
  const root = await repositoryFixture();
  const before = await fingerprintWorktree({ repositoryRoot: root });
  await writeFile(path.join(root, "tracked.txt"), "edited by check\n");
  const after = await fingerprintWorktree({ repositoryRoot: root });
  assert.notEqual(after.digest, before.digest);
});

test("identity, specification, issue, and check fingerprints change with each input class", async () => {
  const root = await repositoryFixture();
  const spec = path.join(root, "spec.md");
  const instruction = path.join(root, "AGENTS.md");
  await writeFile(spec, "requirement one");
  await writeFile(instruction, "instruction one");
  const specOne = await fingerprintSpecifications({ artifactPaths: [spec], instructionPaths: [instruction] });
  await writeFile(spec, "requirement two");
  const specTwo = await fingerprintSpecifications({ artifactPaths: [spec], instructionPaths: [instruction] });
  assert.notEqual(specOne, specTwo);

  assert.notEqual(fingerprintIdentity({ branch: "a" }), fingerprintIdentity({ branch: "b" }));
  const issue = {
    id: "I",
    number: 1,
    title: "Title",
    body: "Body",
    updatedAt: "one",
    comments: [{ id: "C", order: 0, updatedAt: "one", body: "Comment" }],
  };
  assert.notEqual(
    fingerprintIssueRequirements(issue),
    fingerprintIssueRequirements({ ...issue, comments: [{ ...issue.comments[0], body: "Changed" }] }),
  );
  const checks = [{ command: "npm", args: ["test"], source: "package", rationale: "test", required: true, timeoutMs: 1 }];
  assert.notEqual(
    fingerprintRequiredChecks(checks, { npm: "1" }),
    fingerprintRequiredChecks([{ ...checks[0], args: ["run", "test"] }], { npm: "1" }),
  );
});
