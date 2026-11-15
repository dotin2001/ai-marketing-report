import assert from "node:assert/strict";
import test from "node:test";

import {
  classifyPostgresFailure,
  runPostgresPreflight,
  validatePostgresEnvironment,
} from "../postgres-preflight.mjs";

const secretTest = "postgresql+psycopg://test_user:recognizable_password@localhost:5432/workflow_test";
const secretMigration = "postgresql+psycopg://migration_user:other_password@localhost:5432/workflow_test";

function environment(overrides = {}) {
  return {
    TEST_DATABASE_URL: secretTest,
    MIGRATION_DATABASE_URL: secretMigration,
    DATABASE_URL: "postgresql+psycopg://app:password@localhost:5432/application",
    ...overrides,
  };
}

test("validates matching isolated PostgreSQL targets without exposing their credentials", () => {
  const result = validatePostgresEnvironment(environment(), ["localhost"]);
  assert.equal(result.passed, true);
  assert.equal(result.test.target.databaseName, "workflow_test");
});

for (const [name, overrides, expectedSetting] of [
  ["missing test URL", { TEST_DATABASE_URL: undefined }, "TEST_DATABASE_URL"],
  ["missing migration URL", { MIGRATION_DATABASE_URL: undefined }, "MIGRATION_DATABASE_URL"],
  ["literal newline", { TEST_DATABASE_URL: `${secretTest}\n` }, "TEST_DATABASE_URL"],
  ["decoded whitespace", { TEST_DATABASE_URL: secretTest.replace("workflow_test", "workflow%20_test") }, "TEST_DATABASE_URL"],
  ["unsupported scheme", { TEST_DATABASE_URL: secretTest.replace("postgresql+psycopg", "mysql") }, "TEST_DATABASE_URL"],
  ["unapproved host", { TEST_DATABASE_URL: secretTest.replace("localhost", "db.example.test") }, "TEST_DATABASE_URL"],
  ["non-test target", { TEST_DATABASE_URL: secretTest.replace("workflow_test", "production") }, "TEST_DATABASE_URL"],
  ["ordinary database equality", { DATABASE_URL: secretTest }, "DATABASE_URL"],
  ["ordinary database target equality with another role", {
    DATABASE_URL: "postgresql://application:another_password@localhost:5432/workflow_test",
  }, "DATABASE_URL"],
  ["decoded database delimiter", {
    TEST_DATABASE_URL: secretTest.replace("workflow_test", "nested%2Fworkflow_test"),
  }, "TEST_DATABASE_URL"],
  ["mismatched target", { MIGRATION_DATABASE_URL: secretMigration.replace("workflow_test", "other_test") }, "MIGRATION_DATABASE_URL"],
]) {
  test(`rejects ${name} with a variable-specific, secret-free result`, () => {
    const result = validatePostgresEnvironment(environment(overrides), ["localhost"]);
    assert.equal(result.passed, false);
    assert.equal(result.code, "postgres_preflight_invalid");
    assert.match(result.message, new RegExp(expectedSetting));
    for (const secret of ["test_user", "migration_user", "recognizable_password", "other_password", secretTest, secretMigration]) {
      assert.doesNotMatch(JSON.stringify(result), new RegExp(secret.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
    }
  });
}

for (const [name, error, code] of [
  ["permission denial", { code: "EPERM", message: "operation not permitted" }, "postgres_permission_denied"],
  ["unreachable service", { code: "ECONNREFUSED", message: "connection refused" }, "postgres_unreachable"],
  ["server access denial", { message: "password authentication failed for user hidden" }, "postgres_access_denied"],
  ["unknown infrastructure", { message: "driver exploded" }, "postgres_preflight_unknown"],
]) {
  test(`classifies ${name}`, () => {
    const result = classifyPostgresFailure(error, "TEST_DATABASE_URL");
    assert.equal(result.code, code);
    assert.ok(result.message.length < 512);
    assert.doesNotMatch(result.message, /postgresql:|recognizable_password/);
  });
}

test("probes both roles once after validation and returns a stable passing result", async () => {
  const observed = [];
  const result = await runPostgresPreflight({
    environment: environment(),
    approvedHosts: ["localhost"],
    probeDatabase: async ({ settingName, url }) => {
      observed.push({ settingName, url });
      return { passed: true };
    },
  });
  assert.equal(result.code, "postgres_preflight_passed");
  assert.deepEqual(observed.map((entry) => entry.settingName), ["TEST_DATABASE_URL", "MIGRATION_DATABASE_URL"]);
});
