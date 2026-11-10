import assert from "node:assert/strict";
import { test } from "node:test";

import {
  createLinkRecord,
  createTraceability,
  parseLinkRecord,
  parseTraceabilityMarker,
  serializeTraceabilityMarker,
  traceabilityMatches,
} from "../traceability.mjs";

const identity = {
  repository: "dotin2001/ai-marketing-report",
  repositoryId: "R_repo",
  projectOwner: "dotin2001",
  projectNumber: 2,
  projectId: "P_project",
  projectItemId: "PVTI_item",
  issueId: "I_issue",
  issueNumber: 42,
  branch: "feature/set_up",
  baseCommit: "a".repeat(40),
  changeId: "gh-42-add-workflow",
};

test("traceability marker and link record round-trip", () => {
  const traceability = createTraceability(identity);
  const marker = serializeTraceabilityMarker(traceability);
  assert.deepEqual(parseTraceabilityMarker(`# Traceability\n${marker}`, identity), traceability);
  const record = createLinkRecord(traceability, { createdAt: "2026-01-01T00:00:00Z" });
  assert.deepEqual(parseLinkRecord(JSON.parse(JSON.stringify(record)), identity), record);
  assert.equal(traceabilityMatches(traceability, record.traceability), true);
});

test("rejects missing and duplicate markers", () => {
  assert.throws(() => parseTraceabilityMarker("no marker"), (error) => error.code === "traceability_missing");
  const marker = serializeTraceabilityMarker(createTraceability(identity));
  assert.throws(
    () => parseTraceabilityMarker(`${marker}\n${marker}`),
    (error) => error.code === "traceability_duplicate",
  );
});

test("rejects malformed and unsupported-version markers", () => {
  assert.throws(
    () => parseTraceabilityMarker("<!-- ai-local-trace:v1 {bad json} -->"),
    (error) => error.code === "traceability_malformed",
  );
  assert.throws(
    () => parseTraceabilityMarker("<!-- ai-local-trace:v2 {} -->"),
    (error) => error.code === "traceability_unsupported_version",
  );
});

test("rejects missing fields and mismatched identities", () => {
  const incomplete = { schemaVersion: 1, ...identity };
  delete incomplete.projectItemId;
  assert.throws(() => serializeTraceabilityMarker(incomplete), /projectItemId/);

  const marker = serializeTraceabilityMarker(createTraceability(identity));
  assert.throws(
    () => parseTraceabilityMarker(marker, { issueId: "OTHER" }),
    (error) => error.code === "traceability_mismatch",
  );
  assert.equal(traceabilityMatches(createTraceability(identity), { ...createTraceability(identity), issueId: "OTHER" }), false);
});

test("rejects unsupported link record versions", () => {
  assert.throws(
    () => parseLinkRecord({ schemaVersion: 2, traceability: createTraceability(identity) }),
    (error) => error.code === "link_record_malformed",
  );
});
