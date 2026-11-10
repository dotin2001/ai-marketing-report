import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { mkdtemp, readFile, stat, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import { acquireRepositoryLock } from "../lock.mjs";
import { ensureRuntimeLayout } from "../runtime.mjs";

async function fixture() {
  const root = await mkdtemp(path.join(os.tmpdir(), "ai-local-lock-"));
  return ensureRuntimeLayout(path.join(root, ".ai-local"));
}

test("lock acquisition is exclusive and release is owner-safe", async () => {
  const paths = await fixture();
  const first = await acquireRepositoryLock(paths, {
    hostname: "host-a",
    pid: 100,
    registerSignals: false,
  });
  await assert.rejects(
    () =>
      acquireRepositoryLock(paths, {
        hostname: "host-a",
        pid: 200,
        isProcessAlive: () => true,
        registerSignals: false,
      }),
    (error) => error.code === "lock_active",
  );
  assert.equal(await first.release(), true);
  await assert.rejects(() => stat(first.lockPath), { code: "ENOENT" });
});

test("a remote-host lock is uncertain and never removed", async () => {
  const paths = await fixture();
  const first = await acquireRepositoryLock(paths, {
    hostname: "remote-host",
    pid: 100,
    registerSignals: false,
  });
  await assert.rejects(
    () =>
      acquireRepositoryLock(paths, {
        hostname: "local-host",
        pid: 200,
        confirmStale: async () => true,
        registerSignals: false,
      }),
    (error) => error.code === "lock_uncertain",
  );
  assert.ok(await stat(first.lockPath));
});

test("a same-host stale lock requires confirmation and can be recovered", async () => {
  const paths = await fixture();
  await acquireRepositoryLock(paths, {
    hostname: "host-a",
    pid: 100,
    registerSignals: false,
  });
  await assert.rejects(
    () =>
      acquireRepositoryLock(paths, {
        hostname: "host-a",
        pid: 200,
        isProcessAlive: () => false,
        confirmStale: async () => false,
        registerSignals: false,
      }),
    (error) => error.code === "stale_lock_confirmation_required",
  );
  const recovered = await acquireRepositoryLock(paths, {
    hostname: "host-a",
    pid: 200,
    isProcessAlive: () => false,
    confirmStale: async () => true,
    registerSignals: false,
  });
  assert.equal(recovered.metadata.pid, 200);
  await recovered.release();
});

test("one process cannot remove another process lock", async () => {
  const paths = await fixture();
  const lock = await acquireRepositoryLock(paths, {
    hostname: "host-a",
    pid: 100,
    ownershipId: "owner-one",
    registerSignals: false,
  });
  const replacement = {
    ...JSON.parse(await readFile(lock.metadataPath, "utf8")),
    ownershipId: "owner-two",
  };
  await writeFile(lock.metadataPath, JSON.stringify(replacement));

  await assert.rejects(() => lock.release(), (error) => error.code === "lock_changed");
  assert.ok(await stat(lock.lockPath));
});

test("handled signals clean up the owned lock", async () => {
  const paths = await fixture();
  const signals = new EventEmitter();
  const lock = await acquireRepositoryLock(paths, {
    hostname: "host-a",
    pid: 100,
    signalTarget: signals,
  });
  await signals.listeners("SIGTERM")[0]();
  await assert.rejects(() => stat(lock.lockPath), { code: "ENOENT" });
});
