import assert from "node:assert/strict";
import { test } from "node:test";

import { reconcileVerification } from "../verification.mjs";

const manifest = {
  entries: [
    { id: "issue:1", kind: "issue_criterion" },
    { id: "task:1", kind: "task", complete: true },
  ],
  tasks: [{ id: "task:1", complete: true }],
};
const checks = [
  {
    id: "check:openspec",
    command: "openspec",
    args: ["validate", "change", "--strict", "--json"],
    required: true,
  },
  { id: "check:test", command: "npm", args: ["test"], required: true },
];
const passedSummary = {
  passed: true,
  results: checks.map((check) => ({ checkId: check.id, state: "passed" })),
};

function semantic(verdict = "passed") {
  return {
    schemaVersion: 1,
    overallVerdict: verdict === "passed" ? "passed" : "failed",
    results: manifest.entries.map((entry, index) => ({
      id: entry.id,
      verdict: index === 0 ? verdict : "passed",
      evidence: ["concrete evidence"],
      commandEvidenceIds: ["check:test"],
      rationale: "checked",
    })),
  };
}

test("reconciles only fully passing semantic and subprocess evidence", () => {
  const verified = reconcileVerification({
    manifest,
    requiredChecks: checks,
    checkSummary: passedSummary,
    semanticResult: semantic(),
  });
  assert.equal(verified.kind, "VerifiedSynchronization");
  assert.equal(verified.semantic.passed, true);
});

test("passing commands alone cannot pass an unimplemented criterion", () => {
  assert.throws(
    () =>
      reconcileVerification({
        manifest,
        requiredChecks: checks,
        checkSummary: passedSummary,
        semanticResult: semantic("failed"),
      }),
    (error) => error.code === "verification_failed",
  );
});

test("successful agent output cannot bypass a failed or missing check", () => {
  const failedSummary = {
    passed: false,
    results: [
      { checkId: "check:openspec", state: "passed" },
      { checkId: "check:test", state: "failed" },
    ],
  };
  assert.throws(
    () =>
      reconcileVerification({
        manifest,
        requiredChecks: checks,
        checkSummary: failedSummary,
        semanticResult: semantic(),
      }),
    (error) => error.code === "verification_failed",
  );

  assert.throws(
    () =>
      reconcileVerification({
        manifest,
        requiredChecks: checks,
        checkSummary: { passed: true, results: [{ checkId: "check:openspec", state: "passed" }] },
        semanticResult: semantic(),
      }),
    (error) => error.code === "verification_check_missing",
  );
});

test("strict OpenSpec validation cannot be omitted", () => {
  assert.throws(
    () =>
      reconcileVerification({
        manifest,
        requiredChecks: [checks[1]],
        checkSummary: { passed: true, results: [{ checkId: "check:test", state: "passed" }] },
        semanticResult: semantic(),
      }),
    (error) => error.code === "strict_validation_missing",
  );
});
