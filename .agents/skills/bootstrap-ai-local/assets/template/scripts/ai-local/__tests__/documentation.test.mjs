import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

import { HELP_TEXT } from "../cli.mjs";

const repositoryRoot = path.resolve(import.meta.dirname, "../../..");

test("documented workflow commands match CLI help and referenced files exist", async () => {
  const [guide, configText] = await Promise.all([
    readFile(path.join(repositoryRoot, "docs", "ai-local-workflow.md"), "utf8"),
    readFile(path.join(repositoryRoot, "ai-local.config.json"), "utf8"),
  ]);
  const packageManager = JSON.parse(configText).packageManager;
  const { todoOption } = JSON.parse(configText).github;
  const run = `${packageManager} run ai:local`;
  for (const command of [
    run,
    `${run} -- --issue <github-issue-url>`,
    `${run} -- --sync-task`,
    `${run} -- --sync-task --change <change-id>`,
    `${run} -- --help`,
  ]) {
    assert.match(guide, new RegExp(command.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
  assert.match(HELP_TEXT, /node scripts\/ai-local\.mjs --sync-task \[--change <change-id>\]/);
  assert.match(HELP_TEXT, /node scripts\/ai-local\.mjs --issue <github-issue-url>/);
  assert.match(guide, new RegExp(`standalone .--. tells ${packageManager} to forward`));
  assert.match(guide, new RegExp(`exact .${todoOption}. option`));
  assert.match(guide, /duplicate-link detection/);
  assert.match(guide, /\$openspec-apply-change <change-id>/);
  assert.match(guide, /issue remains open/i);
  await Promise.all([
    access(path.join(repositoryRoot, "ai-local.config.json")),
    access(path.join(repositoryRoot, "package.json")),
    access(path.join(repositoryRoot, "scripts", "ai-local.mjs")),
  ]);
});
