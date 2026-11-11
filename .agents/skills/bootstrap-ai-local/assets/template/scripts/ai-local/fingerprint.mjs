import { createHash } from "node:crypto";
import { lstat, readFile, readlink } from "node:fs/promises";
import path from "node:path";

import { VerificationError } from "./errors.mjs";
import { runProcess } from "./process.mjs";

function canonicalize(value) {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value)
        .sort()
        .map((key) => [key, canonicalize(value[key])]),
    );
  }
  return value;
}

export function canonicalSha256(value) {
  return createHash("sha256").update(JSON.stringify(canonicalize(value))).digest("hex");
}

async function gitOutput(repositoryRoot, args, runCommand) {
  const result = await runCommand("git", args, {
    cwd: repositoryRoot,
    timeoutMs: 60_000,
    maxOutputBytes: 32 * 1024 * 1024,
  });
  if (result.timedOut || result.exitCode !== 0 || result.outputTruncated) {
    throw new VerificationError("fingerprint_git_failed", `Unable to fingerprint Git state: git ${args.join(" ")}.`);
  }
  return result.stdout;
}

function nulList(value) {
  return value.split("\0").filter(Boolean);
}

async function fileEntry(repositoryRoot, relativePath, indexEntry) {
  const absolutePath = path.join(repositoryRoot, relativePath);
  try {
    const info = await lstat(absolutePath);
    if (info.isSymbolicLink()) {
      return {
        path: relativePath,
        state: "symlink",
        mode: info.mode & 0o7777,
        content: canonicalSha256(await readlink(absolutePath)),
        indexEntry,
      };
    }
    if (info.isFile()) {
      return {
        path: relativePath,
        state: "file",
        mode: info.mode & 0o7777,
        size: info.size,
        content: createHash("sha256").update(await readFile(absolutePath)).digest("hex"),
        indexEntry,
      };
    }
    return { path: relativePath, state: "non_file", mode: info.mode & 0o7777, indexEntry };
  } catch (error) {
    if (error.code === "ENOENT") return { path: relativePath, state: "deleted", indexEntry };
    throw error;
  }
}

export async function fingerprintWorktree({ repositoryRoot, runCommand = runProcess }) {
  const [head, trackedRaw, untrackedRaw, indexRaw] = await Promise.all([
    gitOutput(repositoryRoot, ["rev-parse", "HEAD"], runCommand),
    gitOutput(repositoryRoot, ["ls-files", "-z"], runCommand),
    gitOutput(repositoryRoot, ["ls-files", "--others", "--exclude-standard", "-z"], runCommand),
    gitOutput(repositoryRoot, ["ls-files", "-s", "-z"], runCommand),
  ]);
  const index = new Map();
  for (const entry of nulList(indexRaw)) {
    const match = entry.match(/^(\d+) ([0-9a-f]+) (\d+)\t(.+)$/);
    if (match) index.set(match[4], { mode: match[1], object: match[2], stage: Number(match[3]) });
  }
  const paths = [...new Set([...nulList(trackedRaw), ...nulList(untrackedRaw)])]
    .filter((relativePath) => relativePath !== ".ai-local" && !relativePath.startsWith(".ai-local/"))
    .sort();
  const entries = [];
  for (const relativePath of paths) entries.push(await fileEntry(repositoryRoot, relativePath, index.get(relativePath) ?? null));
  const manifest = { head: head.trim(), entries };
  return Object.freeze({ digest: canonicalSha256(manifest), manifest: Object.freeze(manifest) });
}

export function fingerprintIdentity(identity) {
  return canonicalSha256(identity);
}

export async function fingerprintSpecifications({ artifactPaths, instructionPaths = [] }) {
  const entries = [];
  for (const filePath of [...new Set([...artifactPaths, ...instructionPaths])].sort()) {
    entries.push({ path: filePath, content: createHash("sha256").update(await readFile(filePath)).digest("hex") });
  }
  return canonicalSha256(entries);
}

export function fingerprintIssueRequirements(issue) {
  return canonicalSha256({
    id: issue.id,
    number: issue.number,
    title: issue.title,
    body: issue.body,
    updatedAt: issue.updatedAt,
    comments: issue.comments.map((comment) => ({
      id: comment.id,
      order: comment.order,
      updatedAt: comment.updatedAt,
      body: comment.body,
    })),
  });
}

export function fingerprintRequiredChecks(checks, toolVersions = {}) {
  return canonicalSha256({
    checks: checks.map((check) => ({
      command: check.command,
      args: check.args,
      source: check.source,
      rationale: check.rationale,
      required: check.required,
      timeoutMs: check.timeoutMs,
      applicable: check.applicable !== false,
    })),
    toolVersions,
  });
}

export async function buildFingerprints({
  repositoryRoot,
  identity,
  artifactPaths,
  instructionPaths,
  issue,
  checks,
  toolVersions,
  runCommand,
}) {
  const worktree = await fingerprintWorktree({ repositoryRoot, runCommand });
  return Object.freeze({
    identity: fingerprintIdentity(identity),
    worktree: worktree.digest,
    specifications: await fingerprintSpecifications({ artifactPaths, instructionPaths }),
    issueRequirements: fingerprintIssueRequirements(issue),
    requiredChecks: fingerprintRequiredChecks(checks, toolVersions),
  });
}

export function fingerprintsEqual(left, right) {
  return ["identity", "worktree", "specifications", "issueRequirements", "requiredChecks"].every(
    (field) => left?.[field] === right?.[field],
  );
}
