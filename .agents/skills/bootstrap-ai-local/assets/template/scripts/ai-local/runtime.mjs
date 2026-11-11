import { randomUUID } from "node:crypto";
import {
  appendFile,
  chmod,
  mkdir,
  open,
  readFile,
  rename,
  rm,
  stat,
} from "node:fs/promises";
import path from "node:path";

import { ConfigurationError, ProcessError } from "./errors.mjs";
import { redact } from "./process.mjs";

const RUNTIME_DIRECTORIES = ["links", "evidence", "events", "locks", "tmp"];

function assertInside(parent, target, label) {
  const relative = path.relative(parent, target);
  if (relative === "" || relative === ".." || relative.startsWith(`..${path.sep}`)) {
    throw new ConfigurationError(`${label} must remain inside ${parent}.`);
  }
}

export async function ensureRuntimeLayout(runtimePath) {
  await mkdir(runtimePath, { recursive: true, mode: 0o700 });
  await chmod(runtimePath, 0o700);
  const paths = { root: runtimePath };
  for (const directory of RUNTIME_DIRECTORIES) {
    const target = path.join(runtimePath, directory);
    await mkdir(target, { recursive: true, mode: 0o700 });
    await chmod(target, 0o700);
    paths[directory] = target;
  }
  return Object.freeze(paths);
}

export async function createOwnedTemp(runtimePaths, prefix, content = "") {
  if (!/^[a-z0-9-]+$/i.test(prefix)) {
    throw new ConfigurationError("Temporary file prefix is invalid.");
  }
  const ownershipId = randomUUID();
  const filePath = path.join(runtimePaths.tmp, `${prefix}-${ownershipId}.tmp`);
  assertInside(runtimePaths.tmp, filePath, "Temporary file");
  const handle = await open(filePath, "wx", 0o600);
  try {
    await handle.writeFile(content, "utf8");
  } finally {
    await handle.close();
  }
  return Object.freeze({ filePath, ownershipId, runtimePaths });
}

export async function cleanupOwnedTemp(ownedTemp) {
  const { filePath, ownershipId, runtimePaths } = ownedTemp;
  assertInside(runtimePaths.tmp, filePath, "Temporary file");
  if (!path.basename(filePath).includes(ownershipId)) {
    throw new ProcessError("Refusing to remove a temporary file without matching ownership.");
  }
  await rm(filePath, { force: true });
}

export async function atomicWriteJson(destination, value, options = {}) {
  const directory = path.dirname(destination);
  await mkdir(directory, { recursive: true, mode: 0o700 });
  const temporary = path.join(directory, `.${path.basename(destination)}.${randomUUID()}.partial`);
  const serialized = `${JSON.stringify(value, null, 2)}\n`;
  const handle = await open(temporary, "wx", 0o600);
  try {
    await handle.writeFile(serialized, "utf8");
    await handle.sync();
    if (options.beforeRename) await options.beforeRename(temporary);
    await rename(temporary, destination);
    await chmod(destination, 0o600);
  } catch (error) {
    await rm(temporary, { force: true });
    throw error;
  } finally {
    await handle.close();
  }
}

export async function appendRedactedEvent(logPath, event, options = {}) {
  const maxBytes = options.maxBytes ?? 1024 * 1024;
  let existingSize = 0;
  try {
    existingSize = (await stat(logPath)).size;
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
  if (existingSize >= maxBytes) return { appended: false, reason: "bounded" };

  const cleanEvent = JSON.parse(redact(JSON.stringify(event), options.secrets));
  let line = `${JSON.stringify(cleanEvent)}\n`;
  const remaining = maxBytes - existingSize;
  if (Buffer.byteLength(line) > remaining) {
    line = `${JSON.stringify({ type: "log_truncated" })}\n`;
    if (Buffer.byteLength(line) > remaining) return { appended: false, reason: "bounded" };
  }
  await mkdir(path.dirname(logPath), { recursive: true, mode: 0o700 });
  await appendFile(logPath, line, { encoding: "utf8", mode: 0o600 });
  await chmod(logPath, 0o600);
  return { appended: true };
}

export async function readJson(filePath) {
  return JSON.parse(await readFile(filePath, "utf8"));
}
