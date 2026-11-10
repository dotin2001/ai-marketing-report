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
  assert.equal(config.runtimePath, path.join(root, ".runtime"));
});

for (const [name, mutate] of [
  ["missing github fields", (copy) => delete copy.github.statusField],
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
