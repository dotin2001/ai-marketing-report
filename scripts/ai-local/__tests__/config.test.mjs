import assert from "node:assert/strict";
import { mkdtemp, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import { loadConfiguration, validateConfiguration } from "../config.mjs";
import { ConfigurationError } from "../errors.mjs";

const valid = {
  github: {
    repository: "example-owner/example-repo",
    projectOwner: "example-owner",
    projectNumber: 7,
    statusField: "Status",
    todoOption: "Todo",
    inProgressOption: "In Progress",
    doneOption: "Done",
  },
  runtimeDirectory: ".runtime",
};

test("loads a valid alternate AI_LOCAL_CONFIG", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "ai-local-config-"));
  const alternate = path.join(root, "fork.json");
  await writeFile(alternate, JSON.stringify(valid));

  const config = await loadConfiguration({
    repositoryRoot: root,
    environment: { AI_LOCAL_CONFIG: alternate },
  });

  assert.equal(config.github.repository, "example-owner/example-repo");
  assert.equal(config.github.projectNumber, 7);
  assert.equal(config.github.inProgressOption, "In Progress");
  assert.equal(config.runtimePath, path.join(root, ".runtime"));
});

test("committed configuration declares the exact In Progress option", async () => {
  const configPath = path.resolve(import.meta.dirname, "../../../ai-local.config.json");
  const config = await loadConfiguration({ repositoryRoot: path.dirname(configPath), environment: { AI_LOCAL_CONFIG: configPath } });
  assert.equal(config.github.inProgressOption, "In Progress");
});

for (const [name, mutate] of [
  ["missing github fields", (copy) => delete copy.github.statusField],
  ["missing In Progress option", (copy) => delete copy.github.inProgressOption],
  ["blank In Progress option", (copy) => (copy.github.inProgressOption = "")],
  ["whitespace In Progress option", (copy) => (copy.github.inProgressOption = " In Progress")],
  ["duplicate Todo and In Progress", (copy) => (copy.github.inProgressOption = "Todo")],
  ["duplicate In Progress and Done", (copy) => (copy.github.inProgressOption = "Done")],
  ["zero project number", (copy) => (copy.github.projectNumber = 0)],
  ["absolute runtime path", (copy) => (copy.runtimeDirectory = "/tmp/outside")],
  ["escaping runtime path", (copy) => (copy.runtimeDirectory = "../outside")],
  ["git runtime path", (copy) => (copy.runtimeDirectory = ".git/ai-local")],
  ["malformed repository", (copy) => (copy.github.repository = "not-a-repository")],
  ["repository path traversal", (copy) => (copy.github.repository = "owner/../repo")],
]) {
  test(`rejects ${name}`, () => {
    const copy = structuredClone(valid);
    mutate(copy);
    assert.throws(() => validateConfiguration(copy, "/repo"), ConfigurationError);
  });
}

test("rejects malformed JSON", async () => {
  await assert.rejects(
    () =>
      loadConfiguration({
        repositoryRoot: "/repo",
        environment: {},
        readFileImpl: async () => "{not json",
      }),
    ConfigurationError,
  );
});

test("accepts neutral, backend-test, and PostgreSQL execution profiles", () => {
  const config = validateConfiguration({
    ...valid,
    verification: {
      executionProfiles: {
        test: "neutral",
        "backend:check": "backend-test",
        "npm run database:check": "postgresql",
      },
      approvedPostgresHosts: ["localhost", "127.0.0.1"],
    },
  }, "/repo");

  assert.deepEqual(config.verification.executionProfiles, {
    "npm run test": "neutral",
    "npm run backend:check": "backend-test",
    "npm run database:check": "postgresql",
  });
});

for (const [name, verification] of [
  ["non-object verification", []],
  ["non-object profiles", { executionProfiles: [] }],
  ["unknown profile", { executionProfiles: { test: "production" } }],
  ["credential-bearing selector", { executionProfiles: { "DATABASE_URL=postgresql://user:password@localhost/db_test npm test": "neutral" } }],
  ["conflicting normalized selectors", { executionProfiles: { test: "neutral", "npm run test": "backend-test" } }],
  ["empty approved hosts", { approvedPostgresHosts: [] }],
  ["credential-bearing host", { approvedPostgresHosts: ["user:password@localhost"] }],
  ["unknown verification field", { unsupported: true }],
]) {
  test(`rejects ${name}`, () => {
    assert.throws(
      () => validateConfiguration({ ...valid, verification }, "/repo"),
      ConfigurationError,
    );
  });
}
