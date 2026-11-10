import { randomUUID } from "node:crypto";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

import { LockError } from "./errors.mjs";

const LOCK_SCHEMA_VERSION = 1;
const SIGNAL_CODES = { SIGINT: 130, SIGTERM: 143, SIGHUP: 129 };

export function isLocalProcessAlive(pid) {
  if (!Number.isSafeInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return error.code === "EPERM";
  }
}

async function readMetadata(metadataPath) {
  try {
    return JSON.parse(await readFile(metadataPath, "utf8"));
  } catch (error) {
    throw new LockError("lock_uncertain", "Repository lock metadata is missing or invalid; recover it manually.", {
      metadataPath,
      causeCode: error.code,
    });
  }
}

function sameOwner(left, right) {
  return Boolean(left?.ownershipId && left.ownershipId === right?.ownershipId);
}

export async function acquireRepositoryLock(runtimePaths, options = {}) {
  const lockPath = path.join(runtimePaths.locks, "repository.lock");
  const metadataPath = path.join(lockPath, "owner.json");
  const hostname = options.hostname ?? os.hostname();
  const pid = options.pid ?? process.pid;
  const ownershipId = options.ownershipId ?? randomUUID();
  const metadata = Object.freeze({
    schemaVersion: LOCK_SCHEMA_VERSION,
    ownershipId,
    pid,
    hostname,
    mode: options.mode ?? "planning",
    changeId: options.changeId ?? null,
    issueId: options.issueId ?? null,
    startedAt: (options.now ?? (() => new Date()))().toISOString(),
  });

  async function createLock() {
    await mkdir(lockPath, { mode: 0o700 });
    await writeFile(metadataPath, `${JSON.stringify(metadata, null, 2)}\n`, {
      encoding: "utf8",
      flag: "wx",
      mode: 0o600,
    });
  }

  try {
    await createLock();
  } catch (error) {
    if (error.code !== "EEXIST") throw error;
    const existing = await readMetadata(metadataPath);
    if (existing.hostname !== hostname) {
      throw new LockError(
        "lock_uncertain",
        `Repository lock belongs to host ${existing.hostname}; it will not be removed automatically.`,
        { existing },
      );
    }
    const alive = (options.isProcessAlive ?? isLocalProcessAlive)(existing.pid);
    if (alive) {
      throw new LockError("lock_active", `Repository workflow is already running as PID ${existing.pid}.`, {
        existing,
      });
    }
    const confirmed = await options.confirmStale?.(existing);
    if (!confirmed) {
      throw new LockError(
        "stale_lock_confirmation_required",
        `Repository lock for dead PID ${existing.pid} appears stale; explicit confirmation is required.`,
        { existing },
      );
    }
    const rechecked = await readMetadata(metadataPath);
    if (!sameOwner(existing, rechecked)) {
      throw new LockError("lock_changed", "Repository lock ownership changed during stale-lock recovery.", {
        existing,
        rechecked,
      });
    }
    await rm(lockPath, { recursive: true });
    try {
      await createLock();
    } catch (retryError) {
      throw new LockError("lock_active", "Another workflow acquired the repository lock during recovery.", {
        causeCode: retryError.code,
      });
    }
  }

  let released = false;
  const signalTarget = options.signalTarget ?? process;
  const handlers = new Map();

  async function release() {
    if (released) return false;
    let current;
    try {
      current = await readMetadata(metadataPath);
    } catch (error) {
      if (error.code === "lock_uncertain") return false;
      throw error;
    }
    if (!sameOwner(metadata, current)) {
      throw new LockError("lock_changed", "Refusing to remove a repository lock owned by another process.", {
        expected: ownershipId,
        actual: current.ownershipId,
      });
    }
    await rm(lockPath, { recursive: true });
    released = true;
    for (const [signal, handler] of handlers) signalTarget.removeListener?.(signal, handler);
    return true;
  }

  if (options.registerSignals !== false) {
    for (const signal of Object.keys(SIGNAL_CODES)) {
      const handler = () =>
        release().finally(() => {
          if (signalTarget === process) process.exit(SIGNAL_CODES[signal]);
        });
      handlers.set(signal, handler);
      signalTarget.once?.(signal, handler);
    }
  }

  return Object.freeze({ lockPath, metadataPath, metadata, release });
}
