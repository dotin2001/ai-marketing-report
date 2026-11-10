import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

import { HELP_TEXT } from "../cli.mjs";

const repositoryRoot = path.resolve(import.meta.dirname, "../../..");

test("documented workflow commands match CLI help and referenced files exist", async () => {
  const [readme, guide] = await Promise.all([
    readFile(path.join(repositoryRoot, "README.md"), "utf8"),
    readFile(path.join(repositoryRoot, "docs", "ai-local-workflow.md"), "utf8"),
  ]);
  for (const command of [
    "npm run ai:local",
    "npm run ai:local -- --sync-task",
    "npm run ai:local -- --sync-task --change <change-id>",
    "npm run ai:local -- --help",
  ]) {
    assert.match(guide, new RegExp(command.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
  assert.match(HELP_TEXT, /npm run ai:local -- --sync-task \[--change <change-id>\]/);
  assert.match(guide, /\$openspec-apply-change <change-id>/);
  assert.match(guide, /issue remains open/i);
  assert.match(readme, /docs\/ai-local-workflow\.md/);
  await Promise.all([
    access(path.join(repositoryRoot, "ai-local.config.json")),
    access(path.join(repositoryRoot, "package.json")),
    access(path.join(repositoryRoot, "scripts", "ai-local.mjs")),
  ]);
});
