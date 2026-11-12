import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createHash, createHmac } from "node:crypto";
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const envPath = path.join(repositoryRoot, "infra/.env");
const composeArgs = [
  "compose",
  "-p",
  "mkt-rp-assistant",
  "--env-file",
  "infra/.env",
  "-f",
  "infra/compose.yaml",
];
const requiredServices = ["postgres", "redis", "object-storage"];
const timeoutMilliseconds = 90_000;

function parseEnvironment(contents) {
  return Object.fromEntries(
    contents
      .split(/\r?\n/u)
      .map((line) => line.trim())
      .filter((line) => line && !line.startsWith("#"))
      .map((line) => {
        const separator = line.indexOf("=");
        return [line.slice(0, separator), line.slice(separator + 1)];
      }),
  );
}

function run(command, args, { allowFailure = false, quiet = false } = {}) {
  const result = spawnSync(command, args, {
    cwd: repositoryRoot,
    encoding: "utf8",
    env: { ...process.env, ...localEnvironment },
    stdio: quiet ? "pipe" : ["ignore", "pipe", "pipe"],
  });
  if (!allowFailure && result.status !== 0) {
    const safeOutput = `${result.stdout ?? ""}\n${result.stderr ?? ""}`
      .replaceAll(localEnvironment.POSTGRES_PASSWORD, "[REDACTED]")
      .replaceAll(localEnvironment.REDIS_PASSWORD, "[REDACTED]")
      .replaceAll(localEnvironment.S3_SECRET_ACCESS_KEY, "[REDACTED]");
    throw new Error(`${command} ${args.join(" ")} failed\n${safeOutput.trim()}`);
  }
  return result;
}

function compose(args, options) {
  return run("docker", [...composeArgs, ...args], options);
}

function sleep(milliseconds) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, milliseconds);
}

function containerState(service, includeStopped = false) {
  const psArguments = ["ps"];
  if (includeStopped) psArguments.push("-a");
  psArguments.push("-q", service);
  const identifier = compose(psArguments, { quiet: true }).stdout.trim();
  if (!identifier) return null;
  const inspected = run(
    "docker",
    ["inspect", "--format", "{{json .State}}", identifier],
    { quiet: true },
  );
  return JSON.parse(inspected.stdout);
}

function waitForStack() {
  const deadline = Date.now() + timeoutMilliseconds;
  while (Date.now() < deadline) {
    const states = Object.fromEntries(requiredServices.map((service) => [service, containerState(service)]));
    const initializer = containerState("object-storage-init", true);
    const failedService = Object.entries(states).find(
      ([, state]) => state && (state.Status === "exited" || state.Health?.Status === "unhealthy"),
    );
    if (failedService) {
      throw new Error(`Local stack service failed: ${failedService[0]}`);
    }
    if (initializer?.Status === "exited" && initializer.ExitCode !== 0) {
      throw new Error("Local stack service failed: object-storage-init");
    }
    const dependenciesHealthy = Object.values(states).every(
      (state) => state?.Status === "running" && state.Health?.Status === "healthy",
    );
    const initializerComplete = initializer?.Status === "exited" && initializer.ExitCode === 0;
    if (dependenciesHealthy && initializerComplete) return;
    sleep(1_000);
  }
  const summary = [...requiredServices, "object-storage-init"]
    .map((service) => `${service}=${JSON.stringify(containerState(service, true))}`)
    .join(", ");
  throw new Error(`Timed out waiting for local stack: ${summary}`);
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function hmac(key, value, encoding) {
  return createHmac("sha256", key).update(value).digest(encoding);
}

function encodeQueryComponent(value) {
  return encodeURIComponent(value).replace(/[!'()*]/gu, (character) =>
    `%${character.codePointAt(0).toString(16).toUpperCase()}`,
  );
}

async function s3Request(pathname, { method = "GET", query = {}, body = "" } = {}) {
  const endpoint = new URL(`http://127.0.0.1:${localEnvironment.S3_API_PORT}`);
  const requestDate = new Date();
  const amzDate = requestDate.toISOString().replace(/[:-]|\.\d{3}/gu, "");
  const dateStamp = amzDate.slice(0, 8);
  const payload = Buffer.from(body);
  const payloadHash = sha256(payload);
  const canonicalQuery = Object.entries(query)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, value]) => `${encodeQueryComponent(key)}=${encodeQueryComponent(value)}`)
    .join("&");
  const canonicalHeaders = `host:${endpoint.host}\nx-amz-content-sha256:${payloadHash}\nx-amz-date:${amzDate}\n`;
  const signedHeaders = "host;x-amz-content-sha256;x-amz-date";
  const canonicalRequest = [
    method,
    pathname,
    canonicalQuery,
    canonicalHeaders,
    signedHeaders,
    payloadHash,
  ].join("\n");
  const scope = `${dateStamp}/${localEnvironment.S3_REGION}/s3/aws4_request`;
  const stringToSign = ["AWS4-HMAC-SHA256", amzDate, scope, sha256(canonicalRequest)].join("\n");
  const dateKey = hmac(`AWS4${localEnvironment.S3_SECRET_ACCESS_KEY}`, dateStamp);
  const regionKey = hmac(dateKey, localEnvironment.S3_REGION);
  const serviceKey = hmac(regionKey, "s3");
  const signingKey = hmac(serviceKey, "aws4_request");
  const signature = hmac(signingKey, stringToSign, "hex");
  const authorization =
    `AWS4-HMAC-SHA256 Credential=${localEnvironment.S3_ACCESS_KEY_ID}/${scope}, ` +
    `SignedHeaders=${signedHeaders}, Signature=${signature}`;
  const querySuffix = canonicalQuery ? `?${canonicalQuery}` : "";
  const response = await fetch(`${endpoint.origin}${pathname}${querySuffix}`, {
    method,
    headers: {
      Authorization: authorization,
      "x-amz-content-sha256": payloadHash,
      "x-amz-date": amzDate,
    },
    body: method === "GET" || method === "HEAD" ? undefined : payload,
  });
  return {
    body: method === "HEAD" ? "" : await response.text(),
    headers: response.headers,
    status: response.status,
  };
}

function xmlValues(xml, elementName) {
  const values = [];
  const pattern = new RegExp(`<${elementName}>([^<]*)</${elementName}>`, "gu");
  for (const match of xml.matchAll(pattern)) values.push(match[1]);
  return values;
}

function s3Outcome(response) {
  return {
    code: xmlValues(response.body, "Code")[0] ?? null,
    status: response.status,
  };
}

async function verifyPrivateBucket() {
  const listing = await s3Request("/");
  assert.equal(listing.status, 200, `Authenticated bucket listing failed: ${listing.status}`);
  assert.deepEqual(xmlValues(listing.body, "Name"), [localEnvironment.S3_BUCKET]);

  const anonymous = await fetch(`http://127.0.0.1:${localEnvironment.S3_API_PORT}/`);
  assert.ok(
    anonymous.status === 401 || anonymous.status === 403,
    `Anonymous bucket listing must be denied, received ${anonymous.status}`,
  );

  const policy = await s3Request(`/${localEnvironment.S3_BUCKET}`, {
    query: { policy: "" },
  });
  assert.notEqual(policy.status, 200, "The local bucket must not have a public bucket policy");
  const versioning = await s3Request(`/${localEnvironment.S3_BUCKET}`, {
    query: { versioning: "" },
  });
  assert.equal(versioning.status, 200, "Bucket metadata must be readable with authenticated S3");
  return {
    policy: s3Outcome(policy),
    versioning: versioning.body,
  };
}

function redisCommand(...arguments_) {
  return compose(
    [
      "exec",
      "-T",
      "redis",
      "redis-cli",
      "--no-auth-warning",
      "-a",
      localEnvironment.REDIS_PASSWORD,
      ...arguments_,
    ],
    { quiet: true },
  ).stdout.trim();
}

if (!fs.existsSync(envPath)) {
  throw new Error("infra/.env is required; copy infra/.env.example and replace placeholders first");
}
const localEnvironment = parseEnvironment(fs.readFileSync(envPath, "utf8"));

try {
  compose(["up", "-d"]);
  waitForStack();
  const firstBucketState = await verifyPrivateBucket();
  const objectPath = `/${localEnvironment.S3_BUCKET}/foundation-persistence.txt`;
  const objectContents = "foundation object storage persistence verified\n";
  const putObject = await s3Request(objectPath, { method: "PUT", body: objectContents });
  assert.ok(putObject.status === 200 || putObject.status === 201, "Test object upload must succeed");
  assert.equal(redisCommand("SET", "foundation:persistence", "verified"), "OK");

  compose(["down"]);
  compose(["up", "-d"]);
  waitForStack();
  const secondBucketState = await verifyPrivateBucket();
  assert.deepEqual(secondBucketState, firstBucketState, "Initializer must preserve bucket policy and metadata");
  const getObject = await s3Request(objectPath);
  assert.equal(getObject.status, 200, "Object storage data must survive container recreation");
  assert.equal(getObject.body, objectContents);
  assert.equal(redisCommand("GET", "foundation:persistence"), "verified");
  const deleteObject = await s3Request(objectPath, { method: "DELETE" });
  assert.ok(deleteObject.status === 200 || deleteObject.status === 204, "Test object cleanup must succeed");

  console.log(
    "Local stack passed two start cycles; private SeaweedFS bucket, object data, and Redis persistence verified.",
  );
} finally {
  compose(["down"], { allowFailure: true });
}
