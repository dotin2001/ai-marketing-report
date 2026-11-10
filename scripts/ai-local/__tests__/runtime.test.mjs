import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtemp, readFile, stat, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import {
  appendRedactedEvent,
  atomicWriteJson,
  cleanupOwnedTemp,
  createOwnedTemp,
  ensureRuntimeLayout,
  readJson,
} from "../runtime.mjs";

test("runtime records are ignored by Git", () => {
  const result = spawnSync("git", ["check-ignore", "-q", ".ai-local/example.json"], {
    cwd: process.cwd(),
  });
  assert.equal(result.status, 0);
});

test("runtime layout and temporary files use owner-only permissions", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "ai-local-runtime-"));
  const paths = await ensureRuntimeLayout(path.join(root, ".ai-local"));
  const temporary = await createOwnedTemp(paths, "context", "untrusted");

  assert.equal((await stat(paths.root)).mode & 0o777, 0o700);
  assert.equal((await stat(temporary.filePath)).mode & 0o777, 0o600);
  await cleanupOwnedTemp(temporary);
  await assert.rejects(() => stat(temporary.filePath), { code: "ENOENT" });
});

test("atomic JSON writes expose only complete records", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "ai-local-atomic-"));
  const destination = path.join(root, "links", "change.json");
  let observedBeforeRename;
  await atomicWriteJson(destination, { schemaVersion: 1, value: "complete" }, {
    beforeRename: async () => {
      try {
        observedBeforeRename = await readFile(destination, "utf8");
      } catch (error) {
        observedBeforeRename = error.code;
      }
    },
  });

  assert.equal(observedBeforeRename, "ENOENT");
  assert.deepEqual(await readJson(destination), { schemaVersion: 1, value: "complete" });
  assert.equal((await stat(destination)).mode & 0o777, 0o600);
});

test("event logs redact credentials and remain bounded", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "ai-local-events-"));
  const logPath = path.join(root, "events", "attempt.jsonl");
  const token = "gho_abcdefghijklmnopqrstuvwxyz";
  await appendRedactedEvent(logPath, { message: `failure ${token}` }, { maxBytes: 100 });
  await appendRedactedEvent(logPath, { message: "x".repeat(500) }, { maxBytes: 100 });
  const content = await readFile(logPath, "utf8");

  assert.doesNotMatch(content, new RegExp(token));
  assert.ok(Buffer.byteLength(content) <= 100);
});

test("cleanup removes only the owned temporary file", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "ai-local-cleanup-"));
  const paths = await ensureRuntimeLayout(path.join(root, ".ai-local"));
  const unrelated = path.join(paths.tmp, "unrelated.txt");
  await writeFile(unrelated, "keep");
  const temporary = await createOwnedTemp(paths, "context", "remove");

  await cleanupOwnedTemp(temporary);
  assert.equal(await readFile(unrelated, "utf8"), "keep");
});
