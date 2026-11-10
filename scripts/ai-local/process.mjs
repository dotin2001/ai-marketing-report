import { spawn } from "node:child_process";

import { ProcessError } from "./errors.mjs";

const SECRET_PATTERNS = [
  /\bgh[pousr]_[A-Za-z0-9_]{8,}\b/g,
  /\bgithub_pat_[A-Za-z0-9_]{8,}\b/g,
  /\bsk-[A-Za-z0-9_-]{8,}\b/g,
  /\bBearer\s+[^\s]+/gi,
];
const QUERY_SECRET_PATTERN = /([?&](?:access_)?token=)[^&\s]+/gi;

export function redact(value, secrets = []) {
  let result = String(value ?? "");
  for (const secret of secrets) {
    if (typeof secret === "string" && secret.length >= 4) {
      result = result.split(secret).join("[REDACTED]");
    }
  }
  for (const pattern of SECRET_PATTERNS) {
    result = result.replace(pattern, "[REDACTED]");
  }
  result = result.replace(QUERY_SECRET_PATTERN, "$1[REDACTED]");
  return result;
}

function appendBounded(current, chunk, limit) {
  if (current.length >= limit) return current;
  const available = limit - current.length;
  return current + chunk.slice(0, available);
}

export function runProcess(command, args, options = {}) {
  if (typeof command !== "string" || command.length === 0) {
    throw new ProcessError("Process command must be a non-empty string.");
  }
  if (!Array.isArray(args) || args.some((argument) => typeof argument !== "string")) {
    throw new ProcessError("Process arguments must be a string array.");
  }

  const timeoutMs = options.timeoutMs ?? 30_000;
  const maxOutputBytes = options.maxOutputBytes ?? 64 * 1024;
  const startedAt = Date.now();

  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: options.cwd,
      env: options.env ?? process.env,
      shell: false,
      stdio: ["pipe", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    let timedOut = false;
    let spawnError;

    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => {
      stdout = appendBounded(stdout, chunk, maxOutputBytes);
      options.onStdout?.(redact(chunk, options.secrets));
    });
    child.stderr.on("data", (chunk) => {
      stderr = appendBounded(stderr, chunk, maxOutputBytes);
      options.onStderr?.(redact(chunk, options.secrets));
    });
    child.on("error", (error) => {
      spawnError = error;
    });

    const timer = setTimeout(() => {
      timedOut = true;
      child.kill("SIGTERM");
      setTimeout(() => child.kill("SIGKILL"), 500).unref();
    }, timeoutMs);
    timer.unref();

    child.on("close", (exitCode, signal) => {
      clearTimeout(timer);
      if (spawnError) {
        reject(
          new ProcessError(`Unable to start ${command}.`, {
            command,
            causeCode: spawnError.code,
          }),
        );
        return;
      }
      resolve({
        command,
        args: args.map((argument) => redact(argument, options.secrets)),
        exitCode: exitCode ?? 1,
        signal,
        timedOut,
        durationMs: Date.now() - startedAt,
        stdout: redact(stdout, options.secrets),
        stderr: redact(stderr, options.secrets),
        outputTruncated: stdout.length >= maxOutputBytes || stderr.length >= maxOutputBytes,
      });
    });

    if (options.stdin !== undefined) {
      child.stdin.end(options.stdin);
    } else {
      child.stdin.end();
    }
  });
}
