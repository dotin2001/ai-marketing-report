import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { createHash, createHmac } from "node:crypto";
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const composeArgs = [
  "compose",
  "-p",
  "mkt-rp-assistant",
  "--env-file",
  "infra/.env",
  "-f",
  "infra/compose.yaml",
];
const services = ["postgres", "redis", "object-storage"];
const dependencyNames = {
  postgres: "postgresql",
  redis: "redis",
  "object-storage": "object_storage",
};
const timeoutMilliseconds = 90_000;

function parseEnvironment(filePath) {
  if (!fs.existsSync(filePath)) {
    throw new Error(`${path.relative(repositoryRoot, filePath)} is required; copy its example first`);
  }
  return Object.fromEntries(
    fs
      .readFileSync(filePath, "utf8")
      .split(/\r?\n/u)
      .map((line) => line.trim())
      .filter((line) => line && !line.startsWith("#"))
      .map((line) => {
        const separator = line.indexOf("=");
        return [line.slice(0, separator), line.slice(separator + 1)];
      }),
  );
}

const infraEnvironment = parseEnvironment(path.join(repositoryRoot, "infra/.env"));
const backendEnvironment = {
  APP_ENV: "local",
  APP_HOST: "127.0.0.1",
  APP_PORT: "8017",
  HEALTH_CHECK_TIMEOUT_SECONDS: "2",
  LOG_LEVEL: "INFO",
  POSTGRES_DB: infraEnvironment.POSTGRES_DB,
  POSTGRES_USER: infraEnvironment.POSTGRES_USER,
  POSTGRES_PASSWORD: infraEnvironment.POSTGRES_PASSWORD,
  DATABASE_URL:
    `postgresql+psycopg://${encodeURIComponent(infraEnvironment.POSTGRES_USER)}:` +
    `${encodeURIComponent(infraEnvironment.POSTGRES_PASSWORD)}@127.0.0.1:` +
    `${infraEnvironment.POSTGRES_PORT}/${encodeURIComponent(infraEnvironment.POSTGRES_DB)}`,
  REDIS_PASSWORD: infraEnvironment.REDIS_PASSWORD,
  REDIS_URL:
    `redis://:${encodeURIComponent(infraEnvironment.REDIS_PASSWORD)}@127.0.0.1:` +
    `${infraEnvironment.REDIS_PORT}/0`,
  S3_ENDPOINT_URL: `http://127.0.0.1:${infraEnvironment.S3_API_PORT}`,
  S3_REGION: infraEnvironment.S3_REGION,
  S3_ACCESS_KEY_ID: infraEnvironment.S3_ACCESS_KEY_ID,
  S3_SECRET_ACCESS_KEY: infraEnvironment.S3_SECRET_ACCESS_KEY,
  S3_BUCKET: infraEnvironment.S3_BUCKET,
  S3_USE_SSL: "false",
};
const processEnvironment = { ...process.env, ...infraEnvironment };

function redact(value) {
  return [
    infraEnvironment.POSTGRES_PASSWORD,
    infraEnvironment.REDIS_PASSWORD,
    infraEnvironment.S3_SECRET_ACCESS_KEY,
    backendEnvironment.DATABASE_URL,
    backendEnvironment.REDIS_URL,
  ].reduce((safe, secret) => (secret ? safe.replaceAll(secret, "[REDACTED]") : safe), value);
}

function run(command, args, { allowFailure = false } = {}) {
  const result = spawnSync(command, args, {
    cwd: repositoryRoot,
    encoding: "utf8",
    env: processEnvironment,
    stdio: ["ignore", "pipe", "pipe"],
  });
  if (!allowFailure && result.status !== 0) {
    throw new Error(redact(`${command} ${args.join(" ")} failed\n${result.stdout}\n${result.stderr}`).trim());
  }
  return result;
}

function compose(args, options) {
  return run("docker", [...composeArgs, ...args], options);
}

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function containerState(service, includeStopped = false) {
  const args = ["ps"];
  if (includeStopped) args.push("-a");
  args.push("-q", service);
  const identifier = compose(args).stdout.trim();
  if (!identifier) return null;
  const inspected = run("docker", ["inspect", "--format", "{{json .State}}", identifier]);
  return JSON.parse(inspected.stdout);
}

async function waitForStack() {
  const deadline = Date.now() + timeoutMilliseconds;
  while (Date.now() < deadline) {
    const states = Object.fromEntries(services.map((service) => [service, containerState(service)]));
    const initializer = containerState("object-storage-init", true);
    for (const [service, state] of Object.entries(states)) {
      if (state && (state.Status === "exited" || state.Health?.Status === "unhealthy")) {
        throw new Error(`Local stack service failed: ${service}`);
      }
    }
    if (initializer?.Status === "exited" && initializer.ExitCode !== 0) {
      throw new Error("Local stack service failed: object-storage-init");
    }
    const healthy = Object.values(states).every(
      (state) => state?.Status === "running" && state.Health?.Status === "healthy",
    );
    if (healthy && initializer?.Status === "exited" && initializer.ExitCode === 0) return;
    await sleep(1_000);
  }
  throw new Error("Timed out waiting for the project-scoped local stack");
}

async function waitForService(service) {
  const deadline = Date.now() + timeoutMilliseconds;
  while (Date.now() < deadline) {
    const state = containerState(service);
    if (state?.Status === "running" && state.Health?.Status === "healthy") return;
    if (state?.Health?.Status === "unhealthy") throw new Error(`Restored service is unhealthy: ${service}`);
    await sleep(1_000);
  }
  throw new Error(`Timed out restoring local stack service: ${service}`);
}

async function requestJson(url) {
  const response = await fetch(url);
  return { body: await response.json(), status: response.status };
}

async function waitForHealth(url, expectedStatus, predicate, description) {
  const deadline = Date.now() + timeoutMilliseconds;
  let last;
  while (Date.now() < deadline) {
    try {
      last = await requestJson(url);
      if (last.status === expectedStatus && predicate(last.body)) return last.body;
    } catch {
      // Startup and dependency recovery are expected to have a short connection gap.
    }
    await sleep(500);
  }
  throw new Error(`Timed out waiting for ${description}; last status was ${last?.status ?? "unreachable"}`);
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function hmac(key, value, encoding) {
  return createHmac("sha256", key).update(value).digest(encoding);
}

async function listObjectKeys() {
  const endpoint = new URL(backendEnvironment.S3_ENDPOINT_URL);
  const pathname = `/${backendEnvironment.S3_BUCKET}`;
  const canonicalQuery = "list-type=2";
  const amzDate = new Date().toISOString().replace(/[:-]|\.\d{3}/gu, "");
  const dateStamp = amzDate.slice(0, 8);
  const payloadHash = sha256("");
  const canonicalHeaders = `host:${endpoint.host}\nx-amz-content-sha256:${payloadHash}\nx-amz-date:${amzDate}\n`;
  const signedHeaders = "host;x-amz-content-sha256;x-amz-date";
  const canonicalRequest = [
    "GET",
    pathname,
    canonicalQuery,
    canonicalHeaders,
    signedHeaders,
    payloadHash,
  ].join("\n");
  const scope = `${dateStamp}/${backendEnvironment.S3_REGION}/s3/aws4_request`;
  const stringToSign = ["AWS4-HMAC-SHA256", amzDate, scope, sha256(canonicalRequest)].join("\n");
  const dateKey = hmac(`AWS4${backendEnvironment.S3_SECRET_ACCESS_KEY}`, dateStamp);
  const regionKey = hmac(dateKey, backendEnvironment.S3_REGION);
  const serviceKey = hmac(regionKey, "s3");
  const signingKey = hmac(serviceKey, "aws4_request");
  const signature = hmac(signingKey, stringToSign, "hex");
  const authorization =
    `AWS4-HMAC-SHA256 Credential=${backendEnvironment.S3_ACCESS_KEY_ID}/${scope}, ` +
    `SignedHeaders=${signedHeaders}, Signature=${signature}`;
  const response = await fetch(`${endpoint.origin}${pathname}?${canonicalQuery}`, {
    headers: {
      Authorization: authorization,
      "x-amz-content-sha256": payloadHash,
      "x-amz-date": amzDate,
    },
  });
  assert.equal(response.status, 200, "Authenticated object listing must succeed");
  const xml = await response.text();
  return [...xml.matchAll(/<Key>([^<]*)<\/Key>/gu)].map((match) => match[1]).sort();
}

function listProductTables() {
  const query =
    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name";
  const result = compose([
    "exec",
    "-T",
    "postgres",
    "psql",
    "-U",
    infraEnvironment.POSTGRES_USER,
    "-d",
    infraEnvironment.POSTGRES_DB,
    "-Atc",
    query,
  ]);
  return result.stdout.trim().split(/\r?\n/u).filter(Boolean);
}

const backendPython = path.join(repositoryRoot, "backend/.venv/bin/python");
assert.ok(fs.existsSync(backendPython), "backend environment is missing; run npm run backend:sync");

let backendProcess;
try {
  compose(["up", "-d"]);
  await waitForStack();
  const initialTables = listProductTables();
  const initialObjects = await listObjectKeys();

  backendProcess = spawn(
    backendPython,
    [
      "-m",
      "uvicorn",
      "app.main:create_app",
      "--factory",
      "--host",
      backendEnvironment.APP_HOST,
      "--port",
      backendEnvironment.APP_PORT,
    ],
    {
      cwd: path.join(repositoryRoot, "backend"),
      env: { ...process.env, ...backendEnvironment },
      stdio: "ignore",
    },
  );

  const backendBaseUrl = `http://${backendEnvironment.APP_HOST}:${backendEnvironment.APP_PORT}`;
  await waitForHealth(
    `${backendBaseUrl}/health/live`,
    200,
    (body) => body.status === "ok",
    "backend liveness",
  );
  await waitForHealth(
    `${backendBaseUrl}/health/ready`,
    200,
    (body) =>
      body.status === "ready" &&
      services.every((service) => body.dependencies[dependencyNames[service]] === "ready"),
    "backend readiness",
  );

  for (const service of services) {
    compose(["stop", service]);
    const unavailable = dependencyNames[service];
    await waitForHealth(
      `${backendBaseUrl}/health/ready`,
      503,
      (body) =>
        body.status === "not_ready" &&
        body.dependencies[unavailable] === "unavailable" &&
        Object.entries(body.dependencies).every(
          ([name, state]) => name === unavailable || state === "ready",
        ),
      `${unavailable} readiness failure`,
    );
    const live = await requestJson(`${backendBaseUrl}/health/live`);
    assert.deepEqual(live, { body: { status: "ok" }, status: 200 });
    compose(["start", service]);
    await waitForService(service);
    await waitForHealth(
      `${backendBaseUrl}/health/ready`,
      200,
      (body) => body.status === "ready",
      `${unavailable} readiness recovery`,
    );
  }

  assert.deepEqual(listProductTables(), initialTables, "Health checks must not create product tables");
  assert.deepEqual(await listObjectKeys(), initialObjects, "Health checks must not create objects");
  console.log(
    "Foundation live check passed healthy, unavailable, recovered, and read-only health states for all dependencies.",
  );
} finally {
  if (backendProcess && backendProcess.exitCode === null) {
    backendProcess.kill("SIGTERM");
    await Promise.race([
      new Promise((resolve) => backendProcess.once("exit", resolve)),
      sleep(5_000),
    ]);
    if (backendProcess.exitCode === null) backendProcess.kill("SIGKILL");
  }
  compose(["start", ...services], { allowFailure: true });
  compose(["down"], { allowFailure: true });
}
