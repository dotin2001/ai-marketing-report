import assert from "node:assert/strict";
import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import { runCodexVerification } from "../codex.mjs";
import { ensureRuntimeLayout } from "../runtime.mjs";
import { validateStructuredVerification } from "../verification.mjs";

const manifest = {
  entries: [
    { id: "issue:1", kind: "issue_criterion", text: "Works" },
    { id: "requirement:1", kind: "requirement", text: "Must work" },
  ],
};
const checkSummary = {
  passed: true,
  results: [{ checkId: "check:1", state: "passed" }],
};

function passing() {
  return {
    schemaVersion: 1,
    overallVerdict: "passed",
    results: manifest.entries.map((entry) => ({
      id: entry.id,
      verdict: "passed",
      evidence: ["src/example.mjs implements the behavior"],
      commandEvidenceIds: ["check:1"],
      rationale: "Implemented and verified.",
    })),
  };
}

test("accepts exhaustive structured results with concrete real evidence", () => {
  assert.equal(validateStructuredVerification(passing(), manifest, checkSummary).passed, true);
});

test("strict Codex output schema omits unsupported array uniqueness keywords", async () => {
  const schemaPath = new URL("../schemas/verification.schema.json", import.meta.url);
  const schema = JSON.parse(await readFile(schemaPath, "utf8"));
  assert.equal(schema.properties.results.items.properties.commandEvidenceIds.uniqueItems, undefined);
});

for (const [name, mutate, code] of [
  ["missing coverage", (value) => value.results.pop(), "semantic_result_coverage_invalid"],
  ["unknown verdict", (value) => (value.results[0].verdict = "maybe"), "semantic_result_invalid"],
  [
    "unsupported not applicable",
    (value) => (value.results[0].verdict = "not_applicable"),
    "semantic_result_not_applicable_unsupported",
  ],
  ["evidence-free pass", (value) => (value.results[0].evidence = []), "semantic_result_evidence_missing"],
  [
    "duplicate command evidence",
    (value) => (value.results[0].commandEvidenceIds = ["check:1", "check:1"]),
    "semantic_result_duplicate_command_evidence",
  ],
  [
    "fabricated command",
    (value) => (value.results[0].commandEvidenceIds = ["check:fake"]),
    "semantic_result_fabricated_command",
  ],
  [
    "global success with unmet criterion",
    (value) => (value.results[0].verdict = "failed"),
    "semantic_result_global_conflict",
  ],
]) {
  test(`rejects ${name}`, () => {
    const value = passing();
    mutate(value);
    assert.throws(() => validateStructuredVerification(value, manifest, checkSummary), (error) =>
      error.code === code,
    );
  });
}

test("verification-only Codex invocation uses schema and validates final output", async () => {
  const repositoryRoot = await mkdtemp(path.join(os.tmpdir(), "ai-local-semantic-"));
  const runtimePaths = await ensureRuntimeLayout(path.join(repositoryRoot, ".ai-local"));
  const schemaPath = path.join(repositoryRoot, "scripts", "ai-local", "schemas", "verification.schema.json");
  await writeFile(schemaPath, "{}").catch(async (error) => {
    if (error.code === "ENOENT") {
      const { mkdir } = await import("node:fs/promises");
      await mkdir(path.dirname(schemaPath), { recursive: true });
      await writeFile(schemaPath, "{}");
    } else throw error;
  });
  let observed;
  const result = await runCodexVerification({
    repositoryRoot,
    runtimePaths,
    manifest,
    checkSummary,
    runCommand: async (command, args, options) => {
      observed = { command, args, prompt: options.stdin };
      const outputPath = args[args.indexOf("--output-last-message") + 1];
      await writeFile(outputPath, JSON.stringify(passing()));
      return {
        exitCode: 0,
        timedOut: false,
        stdout: `${JSON.stringify({ type: "turn.completed" })}\n`,
        stderr: "",
      };
    },
  });
  assert.equal(result.passed, true);
  assert.equal(observed.command, "codex");
  assert.ok(observed.args.includes("--output-schema"));
  assert.match(observed.prompt, /verification only/i);
  assert.match(observed.prompt, /Do not edit source/);
});
