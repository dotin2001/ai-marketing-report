import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const composeArgs = [
  "compose",
  "-p",
  "mkt-rp-assistant",
  "--env-file",
  "/dev/null",
  "-f",
  "infra/compose.yaml",
];

const sanitizedEnvironment = {
  ...process.env,
  POSTGRES_DB: "marketing_reports",
  POSTGRES_USER: "marketing_app",
  POSTGRES_PASSWORD: "local-postgres-test-password",
  POSTGRES_PORT: "55432",
  REDIS_PASSWORD: "local-redis-test-password",
  REDIS_PORT: "56379",
  S3_ACCESS_KEY_ID: "local-seaweedfs-test-user",
  S3_SECRET_ACCESS_KEY: "local-seaweedfs-test-password",
  S3_BUCKET: "marketing-reports-test",
  S3_REGION: "us-east-1",
  S3_API_PORT: "59000",
  S3_CONSOLE_PORT: "59001",
};

function composeConfig(environment, extraArgs = []) {
  return spawnSync("docker", [...composeArgs, "config", ...extraArgs], {
    cwd: repositoryRoot,
    env: environment,
    encoding: "utf8",
  });
}

const rendered = composeConfig(sanitizedEnvironment, ["--format", "json"]);
assert.equal(rendered.status, 0, "Compose configuration must render with sanitized values");

const config = JSON.parse(rendered.stdout);
assert.deepEqual(composeArgs.slice(0, 3), ["compose", "-p", "mkt-rp-assistant"]);
assert.deepEqual(
  Object.keys(config.services).sort(),
  ["object-storage", "object-storage-init", "postgres", "redis"],
);

for (const serviceName of ["postgres", "redis", "object-storage"]) {
  const service = config.services[serviceName];
  assert.ok(service.healthcheck?.test, `${serviceName} must declare a health check`);
  assert.ok(
    service.volumes?.some((volume) => volume.type === "volume"),
    `${serviceName} must use a named volume`,
  );
  assert.notEqual(service.network_mode, "host", `${serviceName} must not use host networking`);
  for (const port of service.ports ?? []) {
    assert.equal(port.host_ip, "127.0.0.1", `${serviceName} ports must bind to loopback`);
  }
  assert.match(service.image, /:[^/]+$/);
  assert.doesNotMatch(service.image, /:latest$/i);
}

assert.match(config.services.redis.command.join(" "), /--requirepass/);
assert.match(config.services["object-storage"].image, /^chrislusf\/seaweedfs:4\.53@sha256:/);
assert.match(config.services["object-storage"].command.join(" "), /\bserver\b/);
assert.match(config.services["object-storage"].command.join(" "), /-s3\b/);
assert.equal(config.services["object-storage"].environment.AWS_ACCESS_KEY_ID, "local-seaweedfs-test-user");
assert.equal(
  config.services["object-storage"].environment.AWS_SECRET_ACCESS_KEY,
  "local-seaweedfs-test-password",
);
assert.equal(config.services["object-storage-init"].depends_on["object-storage"].condition, "service_healthy");
const initializerCommand = config.services["object-storage-init"].command.join(" ");
assert.match(initializerCommand, /s3\.bucket\.list/);
assert.match(initializerCommand, /s3\.bucket\.create/);
assert.match(initializerCommand, /if ! list_buckets/);
assert.doesNotMatch(initializerCommand, /anonymous|public|download|upload/i);

assert.deepEqual(
  Object.values(config.volumes)
    .map((volume) => volume.name)
    .sort(),
  [
    "mkt-rp-assistant-object-storage-data",
    "mkt-rp-assistant-postgres-data",
    "mkt-rp-assistant-redis-data",
  ],
);

const missingEnvironment = {
  PATH: process.env.PATH,
  HOME: process.env.HOME,
};
const missing = composeConfig(missingEnvironment, ["--quiet"]);
assert.notEqual(missing.status, 0, "Missing required settings must fail before container creation");
assert.match(
  `${missing.stdout}\n${missing.stderr}`,
  /(POSTGRES|REDIS|S3)_[A-Z0-9_]+/,
  "Failure must identify a missing setting",
);
assert.doesNotMatch(
  `${missing.stdout}\n${missing.stderr}`,
  /local-(postgres|redis|seaweedfs)-test-(password|user)/,
  "Validation output must not disclose other configured values",
);

console.log("Compose contract verified with loopback bindings, health checks, private storage, and named volumes.");
