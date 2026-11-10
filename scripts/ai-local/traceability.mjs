import { TraceabilityError } from "./errors.mjs";

export const TRACEABILITY_SCHEMA_VERSION = 1;
export const TRACEABILITY_PREFIX = "ai-local-trace:v1";

const REQUIRED_STRINGS = [
  "repository",
  "repositoryId",
  "projectOwner",
  "projectId",
  "projectItemId",
  "issueId",
  "branch",
  "baseCommit",
  "changeId",
];
const IDENTITY_FIELDS = [
  ...REQUIRED_STRINGS,
  "projectNumber",
  "issueNumber",
];

function fail(message, details) {
  throw new TraceabilityError("invalid_traceability", message, details);
}

export function validateTraceability(value, expected = undefined) {
  if (!value || typeof value !== "object" || Array.isArray(value)) fail("Traceability must be an object.");
  if (value.schemaVersion !== TRACEABILITY_SCHEMA_VERSION) {
    fail(`Unsupported traceability schema version: ${String(value.schemaVersion)}.`);
  }
  for (const field of REQUIRED_STRINGS) {
    if (typeof value[field] !== "string" || !value[field]) fail(`Traceability field ${field} is required.`);
  }
  if (!/^[^/\s]+\/[^/\s]+$/.test(value.repository)) fail("Traceability repository is malformed.");
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(value.changeId)) fail("Traceability changeId is malformed.");
  if (!/^[0-9a-f]{40,64}$/i.test(value.baseCommit)) fail("Traceability baseCommit is malformed.");
  if (!Number.isSafeInteger(value.projectNumber) || value.projectNumber <= 0) {
    fail("Traceability projectNumber must be positive.");
  }
  if (!Number.isSafeInteger(value.issueNumber) || value.issueNumber <= 0) {
    fail("Traceability issueNumber must be positive.");
  }
  if (expected) {
    for (const field of IDENTITY_FIELDS) {
      if (expected[field] !== undefined && value[field] !== expected[field]) {
        throw new TraceabilityError(
          "traceability_mismatch",
          `Traceability ${field} does not match the expected identity.`,
          { field, expected: expected[field], actual: value[field] },
        );
      }
    }
  }
  return Object.freeze(Object.fromEntries(["schemaVersion", ...IDENTITY_FIELDS].map((field) => [field, value[field]])));
}

export function createTraceability(identity) {
  return validateTraceability({ schemaVersion: TRACEABILITY_SCHEMA_VERSION, ...identity });
}

export function serializeTraceabilityMarker(identity) {
  const traceability = validateTraceability(identity);
  return `<!-- ${TRACEABILITY_PREFIX} ${JSON.stringify(traceability)} -->`;
}

export function parseTraceabilityMarker(proposalText, expected = undefined) {
  const markerPattern = /<!--\s*ai-local-trace:v(\d+)\s+([\s\S]*?)\s*-->/g;
  const matches = [...String(proposalText).matchAll(markerPattern)];
  if (matches.length !== 1) {
    throw new TraceabilityError(
      matches.length === 0 ? "traceability_missing" : "traceability_duplicate",
      `Proposal must contain exactly one traceability marker; found ${matches.length}.`,
    );
  }
  if (Number(matches[0][1]) !== TRACEABILITY_SCHEMA_VERSION) {
    throw new TraceabilityError(
      "traceability_unsupported_version",
      `Unsupported traceability marker version: ${matches[0][1]}.`,
    );
  }
  let parsed;
  try {
    parsed = JSON.parse(matches[0][2]);
  } catch {
    throw new TraceabilityError("traceability_malformed", "Traceability marker contains malformed JSON.");
  }
  return validateTraceability(parsed, expected);
}

export function createLinkRecord(identity, { createdAt = new Date().toISOString() } = {}) {
  const traceability = validateTraceability(identity);
  return Object.freeze({
    schemaVersion: TRACEABILITY_SCHEMA_VERSION,
    traceability,
    createdAt,
    lastSynchronizedAt: null,
  });
}

export function parseLinkRecord(value, expected = undefined) {
  if (!value || typeof value !== "object" || value.schemaVersion !== TRACEABILITY_SCHEMA_VERSION) {
    throw new TraceabilityError("link_record_malformed", "Link record schema is missing or unsupported.");
  }
  if (typeof value.createdAt !== "string" || !value.createdAt) {
    throw new TraceabilityError("link_record_malformed", "Link record createdAt is required.");
  }
  return Object.freeze({ ...value, traceability: validateTraceability(value.traceability, expected) });
}

export function traceabilityMatches(left, right) {
  try {
    validateTraceability(left, right);
    validateTraceability(right, left);
    return true;
  } catch {
    return false;
  }
}
