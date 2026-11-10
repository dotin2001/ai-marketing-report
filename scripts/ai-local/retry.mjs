import { readFile } from "node:fs/promises";

import { listEvidence, EVIDENCE_SCHEMA_VERSION } from "./evidence.mjs";
import { canonicalSha256, fingerprintsEqual } from "./fingerprint.mjs";

function identitiesEqual(left, right) {
  return canonicalSha256(left) === canonicalSha256(right);
}

function reusable(record, identities, fingerprints) {
  return record?.schemaVersion === EVIDENCE_SCHEMA_VERSION
    && record.verification?.state === "passed"
    && record.synchronization?.state === "failed"
    && identitiesEqual(record.identities, identities)
    && fingerprintsEqual(record.fingerprints, fingerprints);
}

export async function findReusableEvidence({ runtimePaths, changeId, identities, fingerprints }) {
  const paths = (await listEvidence(runtimePaths, changeId)).reverse();
  for (const evidencePath of paths) {
    let record;
    try {
      record = JSON.parse(await readFile(evidencePath, "utf8"));
    } catch {
      continue;
    }
    if (reusable(record, identities, fingerprints)) {
      return Object.freeze({ kind: "reuse", evidencePath, record: Object.freeze(record) });
    }
  }
  return Object.freeze({ kind: "fresh" });
}

export async function resolveVerificationAttempt({
  runtimePaths,
  changeId,
  identities,
  fingerprints,
  verifyFresh,
  finalLiveCheck,
}) {
  const lookup = await findReusableEvidence({ runtimePaths, changeId, identities, fingerprints });
  if (lookup.kind === "reuse") {
    const live = await finalLiveCheck({ record: lookup.record, reused: true });
    return Object.freeze({ ...lookup, live });
  }
  const record = await verifyFresh();
  return Object.freeze({ kind: "fresh", record });
}
