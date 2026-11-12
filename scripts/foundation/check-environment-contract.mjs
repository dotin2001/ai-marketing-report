import assert from "node:assert/strict";
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const secretNamePattern = /(PASSWORD|SECRET|ACCESS_KEY|API_KEY|DATABASE_URL|REDIS_URL)/u;

function environmentKeys(contents) {
  return new Set(
    contents
      .split(/\r?\n/u)
      .map((line) => line.match(/^([A-Z][A-Z0-9_]*)=/u)?.[1])
      .filter(Boolean),
  );
}

function backendAliases(contents) {
  return new Set([...contents.matchAll(/validation_alias="([A-Z][A-Z0-9_]*)"/gu)].map((match) => match[1]));
}

function composeVariables(contents) {
  return new Set([...contents.matchAll(/\$\{([A-Z][A-Z0-9_]*)(?=[:}])/gu)].map((match) => match[1]));
}

function assertContainsAll(actual, expected, location) {
  for (const key of expected) {
    assert.ok(actual.has(key), `${location} is missing ${key}`);
  }
}

export function validateContractTexts({ backendConfig, backendExample, compose, docs, frontendExample, infraExample }) {
  const backendKeys = backendAliases(backendConfig);
  const backendExampleKeys = environmentKeys(backendExample);
  assert.deepEqual(
    [...backendExampleKeys].sort(),
    [...backendKeys].sort(),
    "backend/.env.example must match typed backend settings exactly",
  );

  const composeKeys = composeVariables(compose);
  const infraExampleKeys = environmentKeys(infraExample);
  assert.deepEqual(
    [...infraExampleKeys].sort(),
    [...composeKeys].sort(),
    "infra/.env.example must match Compose interpolation exactly",
  );

  const frontendKeys = environmentKeys(frontendExample);
  assert.deepEqual(
    [...frontendKeys],
    ["NEXT_PUBLIC_API_BASE_URL"],
    "frontend may expose only NEXT_PUBLIC_API_BASE_URL",
  );
  for (const key of frontendKeys) {
    assert.doesNotMatch(key, secretNamePattern, `frontend example exposes server secret ${key}`);
  }

  assertContainsAll(new Set(docs.match(/[A-Z][A-Z0-9_]+/gu) ?? []), backendKeys, "local setup guide");
  assertContainsAll(new Set(docs.match(/[A-Z][A-Z0-9_]+/gu) ?? []), composeKeys, "local setup guide");
  assertContainsAll(new Set(docs.match(/[A-Z][A-Z0-9_]+/gu) ?? []), frontendKeys, "local setup guide");
}

function read(relativePath) {
  return fs.readFileSync(path.join(repositoryRoot, relativePath), "utf8");
}

export function verifyEnvironmentContract() {
  validateContractTexts({
    backendConfig: read("backend/app/core/config.py"),
    backendExample: read("backend/.env.example"),
    compose: read("infra/compose.yaml"),
    docs: read("docs/local-development.md"),
    frontendExample: read("frontend/.env.local.example"),
    infraExample: read("infra/.env.example"),
  });
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  verifyEnvironmentContract();
  console.log("Environment contract matches typed settings, examples, Compose, browser scope, and docs.");
}
