import path from "node:path";

import { redact } from "./process.mjs";

const POSTGRES_SCHEMES = new Set(["postgresql:", "postgresql+psycopg:"]);
const PERMISSION_CODES = new Set(["EACCES", "EPERM"]);
const UNREACHABLE_CODES = new Set(["ECONNREFUSED", "ETIMEDOUT", "ENOTFOUND", "EHOSTUNREACH", "ENETUNREACH"]);

function failure(code, settingName, message) {
  return Object.freeze({ passed: false, code, settingName, message: `${settingName}: ${message}` });
}

function decodedContainsWhitespace(value) {
  try {
    return /\s/.test(decodeURIComponent(value));
  } catch {
    return true;
  }
}

function validateOne(settingName, rawValue, approvedHosts) {
  if (typeof rawValue !== "string" || rawValue.length === 0) {
    return failure("postgres_preflight_invalid", settingName, "required value is missing.");
  }
  if (/\s/.test(rawValue)) {
    return failure("postgres_preflight_invalid", settingName, "value contains whitespace.");
  }
  let parsed;
  try {
    parsed = new URL(rawValue);
  } catch {
    return failure("postgres_preflight_invalid", settingName, "value does not use supported PostgreSQL URL syntax.");
  }
  if (!POSTGRES_SCHEMES.has(parsed.protocol)) {
    return failure("postgres_preflight_invalid", settingName, "URL scheme is not approved.");
  }
  const components = [parsed.username, parsed.password, parsed.hostname, parsed.pathname, parsed.search, parsed.hash];
  if (components.some(decodedContainsWhitespace)) {
    return failure("postgres_preflight_invalid", settingName, "decoded URL components contain whitespace.");
  }
  const host = parsed.hostname.toLowerCase();
  if (!host || !approvedHosts.map((entry) => entry.toLowerCase()).includes(host)) {
    return failure("postgres_preflight_invalid", settingName, "host is not approved for isolated tests.");
  }
  if (parsed.hash || parsed.pathname.split("/").filter(Boolean).length !== 1) {
    return failure("postgres_preflight_invalid", settingName, "database target syntax is unsupported.");
  }
  let databaseName;
  try {
    databaseName = decodeURIComponent(parsed.pathname.slice(1));
  } catch {
    return failure("postgres_preflight_invalid", settingName, "database target encoding is invalid.");
  }
  if (/[/?#]/.test(databaseName)) {
    return failure("postgres_preflight_invalid", settingName, "database target contains unsupported decoded delimiters.");
  }
  if (!databaseName.toLowerCase().endsWith("_test")) {
    return failure("postgres_preflight_invalid", settingName, "database target is not an isolated _test database.");
  }
  return Object.freeze({
    passed: true,
    settingName,
    rawValue,
    target: Object.freeze({ host, port: parsed.port || "5432", databaseName }),
  });
}

export function validatePostgresEnvironment(environment, approvedHosts = ["localhost", "127.0.0.1", "::1"]) {
  const test = validateOne("TEST_DATABASE_URL", environment?.TEST_DATABASE_URL, approvedHosts);
  if (!test.passed) return test;
  const migration = validateOne("MIGRATION_DATABASE_URL", environment?.MIGRATION_DATABASE_URL, approvedHosts);
  if (!migration.passed) return migration;
  if (typeof environment?.DATABASE_URL === "string") {
    let application;
    try {
      const parsed = new URL(environment.DATABASE_URL);
      application = {
        host: parsed.hostname.toLowerCase(),
        port: parsed.port || "5432",
        databaseName: decodeURIComponent(parsed.pathname.slice(1)),
      };
    } catch {
      application = null;
    }
    if (application && [test.target, migration.target].some((target) => (
      target.host === application.host
      && target.port === application.port
      && target.databaseName === application.databaseName
    ))) {
      return failure("postgres_preflight_invalid", "DATABASE_URL", "ordinary application target must differ from test targets.");
    }
  }
  if (
    test.target.host !== migration.target.host
    || test.target.port !== migration.target.port
    || test.target.databaseName !== migration.target.databaseName
  ) {
    return failure(
      "postgres_preflight_invalid",
      "MIGRATION_DATABASE_URL",
      "migration and test URLs must identify the same isolated server and database.",
    );
  }
  return Object.freeze({ passed: true, test, migration });
}

export function classifyPostgresFailure(error, settingName = "PostgreSQL preflight") {
  const safeText = redact(error?.message ?? error?.stderr ?? "").slice(0, 512);
  const code = error?.causeCode ?? error?.code;
  if (PERMISSION_CODES.has(code) || /operation not permitted|permission denied/i.test(safeText)) {
    return failure("postgres_permission_denied", settingName, "local process or sandbox permission denied the connection.");
  }
  if (UNREACHABLE_CODES.has(code) || /connection refused|timed? out|could not translate host|network is unreachable/i.test(safeText)) {
    return failure("postgres_unreachable", settingName, "PostgreSQL service is unreachable.");
  }
  if (/authentication failed|password authentication failed|does not exist|not permitted|insufficient privilege/i.test(safeText)) {
    return failure("postgres_access_denied", settingName, "PostgreSQL server denied access.");
  }
  return failure("postgres_preflight_unknown", settingName, "PostgreSQL infrastructure probe failed.");
}

async function defaultProbe({ settingName, url, environment, repositoryRoot, runCommand }) {
  const result = await runCommand("uv", [
    "--cache-dir", "backend/.uv-cache",
    "--directory", "backend",
    "run", "python", "-m", "app.db.preflight",
  ], {
    cwd: repositoryRoot,
    env: { ...environment, AI_LOCAL_POSTGRES_PROBE_URL: url },
    timeoutMs: 15_000,
    maxOutputBytes: 8 * 1024,
    secrets: [url],
  });
  if (result.timedOut) return failure("postgres_unreachable", settingName, "PostgreSQL service probe timed out.");
  let payload;
  try {
    payload = JSON.parse(result.stdout);
  } catch {
    if (result.exitCode !== 0) return classifyPostgresFailure({ stderr: result.stderr }, settingName);
    return failure("postgres_preflight_unknown", settingName, "PostgreSQL probe returned an invalid response.");
  }
  if (result.exitCode === 0 && payload?.passed === true) return Object.freeze({ passed: true });
  const allowed = new Set(["postgres_permission_denied", "postgres_unreachable", "postgres_access_denied", "postgres_preflight_unknown"]);
  const code = allowed.has(payload?.code) ? payload.code : "postgres_preflight_unknown";
  return failure(code, settingName, payload?.message ?? "PostgreSQL infrastructure probe failed.");
}

export async function runPostgresPreflight({
  environment = process.env,
  approvedHosts,
  repositoryRoot = process.cwd(),
  runCommand,
  probeDatabase = defaultProbe,
}) {
  const validated = validatePostgresEnvironment(environment, approvedHosts);
  if (!validated.passed) return validated;
  for (const entry of [validated.test, validated.migration]) {
    try {
      const result = await probeDatabase({
        settingName: entry.settingName,
        url: entry.rawValue,
        environment,
        repositoryRoot: path.resolve(repositoryRoot),
        runCommand,
      });
      if (!result?.passed) return result?.code ? result : classifyPostgresFailure(result, entry.settingName);
    } catch (error) {
      return classifyPostgresFailure(error, entry.settingName);
    }
  }
  return Object.freeze({ passed: true, code: "postgres_preflight_passed" });
}
