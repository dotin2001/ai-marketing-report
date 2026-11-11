import { spawnSync } from "node:child_process";
import { readdirSync } from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const moduleRoot = path.dirname(fileURLToPath(import.meta.url));
const scriptsRoot = path.dirname(moduleRoot);

function collectModules(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const target = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      return collectModules(target);
    }
    return entry.isFile() && entry.name.endsWith(".mjs") ? [target] : [];
  });
}

const modules = [path.join(scriptsRoot, "ai-local.mjs"), ...collectModules(moduleRoot)];
for (const modulePath of modules) {
  const result = spawnSync(process.execPath, ["--check", modulePath], {
    encoding: "utf8",
    stdio: "pipe",
  });
  if (result.status !== 0) {
    process.stderr.write(result.stderr);
    process.exitCode = 1;
    break;
  }
}

if (!process.exitCode) {
  process.stdout.write(`Syntax checked ${modules.length} modules.\n`);
}
