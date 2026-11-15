import { VerificationError } from "./errors.mjs";

const PROFILE_RANK = Object.freeze({ neutral: 0, "backend-test": 1, postgresql: 2 });

function commandText(check) {
  return [check.command, ...(check.args ?? [])].join(" ");
}

function referencedNpmScripts(scriptBody) {
  const references = [];
  for (const match of String(scriptBody).matchAll(/(?:^|(?:&&|\|\||;))\s*npm\s+(?:run\s+)?([A-Za-z0-9:._-]+)/g)) {
    references.push(match[1]);
  }
  return references;
}

function expandNpmScript(scriptName, scripts, visiting = new Set()) {
  if (visiting.has(scriptName)) {
    throw new VerificationError(
      "verification_config_malformed",
      `Package script graph contains a cycle at ${scriptName}.`,
    );
  }
  const body = scripts[scriptName];
  if (typeof body !== "string") return Object.freeze({ names: [scriptName], bodies: [] });
  const next = new Set(visiting);
  next.add(scriptName);
  const names = [scriptName];
  const bodies = [body];
  for (const referenced of referencedNpmScripts(body)) {
    const expanded = expandNpmScript(referenced, scripts, next);
    names.push(...expanded.names);
    bodies.push(...expanded.bodies);
  }
  return Object.freeze({ names: [...new Set(names)], bodies: [...new Set(bodies)] });
}

function inferredProfile(check, expansion) {
  const haystack = [commandText(check), ...expansion.names, ...expansion.bodies].join("\n");
  const postgres = /(?:\bpostgres(?:ql)?\b|\balembic\b|database:|tests\/integration\/db|(?:^|\s)-m\s+postgres\b)/i.test(haystack);
  const backend = postgres || /(?:backend:|--directory\s+backend\b|--prefix\s+backend\b|\bpytest\b|\bruff\b|\bmypy\b)/i.test(haystack);
  return postgres ? "postgresql" : backend ? "backend-test" : "neutral";
}

function explicitProfile(check, configuration) {
  const profiles = configuration?.verification?.executionProfiles ?? {};
  const exact = commandText(check);
  const mapped = Object.hasOwn(profiles, exact) ? profiles[exact] : null;
  if (check.configuredExecutionProfile && mapped && check.configuredExecutionProfile !== mapped) {
    throw new VerificationError("verification_profile_conflict", `Conflicting execution-profile metadata for ${exact}.`);
  }
  if (check.configuredExecutionProfile) return check.configuredExecutionProfile;
  if (mapped) return mapped;
  if (check.command === "npm" && check.args?.[0] === "test" && Object.hasOwn(profiles, "npm run test")) {
    return profiles["npm run test"];
  }
  return null;
}

export function normalizeCheckPlan(checks, { packageScripts = {}, configuration = {} } = {}) {
  return Object.freeze(checks.map((check) => {
    let expansion = Object.freeze({ names: [], bodies: [] });
    if (check.command === "npm") {
      const scriptName = check.args?.[0] === "test"
        ? "test"
        : check.args?.[0] === "run"
          ? check.args?.[1]
          : null;
      if (scriptName) expansion = expandNpmScript(scriptName, packageScripts);
    }
    const inferred = inferredProfile(check, expansion);
    const configured = explicitProfile(check, configuration);
    const executionProfile = configured ?? inferred;
    if (!(executionProfile in PROFILE_RANK)) {
      throw new VerificationError("verification_config_malformed", `Unsupported execution profile for ${commandText(check)}.`);
    }
    if (configured === "neutral" && inferred !== "neutral") {
      throw new VerificationError(
        "verification_profile_conflict",
        `Configured neutral profile conflicts with detected backend requirements for ${commandText(check)}.`,
      );
    }
    if (configured === "backend-test" && inferred === "postgresql") {
      throw new VerificationError(
        "verification_profile_conflict",
        `Configured backend-test profile conflicts with detected PostgreSQL requirements for ${commandText(check)}.`,
      );
    }
    return Object.freeze({
      ...check,
      applicable: check.applicable !== false,
      applicabilityReason: check.applicable === false
        ? check.applicabilityReason ?? "Check marked inapplicable."
        : check.applicabilityReason ?? "Selected by trusted repository verification inputs.",
      executionProfile,
      capabilities: Object.freeze({
        backendTest: PROFILE_RANK[executionProfile] >= PROFILE_RANK["backend-test"],
        postgresql: executionProfile === "postgresql",
      }),
      resolvedScripts: Object.freeze([...expansion.names]),
    });
  }));
}

export function buildCheckEnvironment(check, parentEnvironment = process.env) {
  const child = { ...parentEnvironment };
  if (check?.capabilities?.backendTest || ["backend-test", "postgresql"].includes(check?.executionProfile)) {
    child.APP_ENV = "test";
    child.AI_LOCAL_DISABLE_DOTENV = "1";
  }
  return child;
}
