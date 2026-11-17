import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

const repositoryRoot = path.resolve(import.meta.dirname, "../../..");
const templateRoot = path.join(
  repositoryRoot,
  ".agents",
  "skills",
  "bootstrap-ai-local",
  "assets",
  "template",
  "scripts",
  "ai-local",
);

const sharedFiles = [
  "check-plan.mjs",
  "codex.mjs",
  "cli.mjs",
  "config.mjs",
  "evidence.mjs",
  "fingerprint.mjs",
  "guard.mjs",
  "explicit-issue.mjs",
  "project.mjs",
  "postgres-preflight.mjs",
  "process.mjs",
  "status-sync.mjs",
  "sync-workflow.mjs",
  "workflow.mjs",
  "verification.mjs",
  "schemas/verification.schema.json",
];

test("repository and bootstrap template verification modules stay byte-identical", async () => {
  for (const relativePath of sharedFiles) {
    const [runtime, template] = await Promise.all([
      readFile(path.join(repositoryRoot, "scripts", "ai-local", relativePath)),
      readFile(path.join(templateRoot, relativePath)),
    ]);
    assert.deepEqual(template, runtime, relativePath);
  }
});
