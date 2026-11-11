import path from "node:path";

import { ProcessError } from "./errors.mjs";

const PROHIBITED_EXECUTABLES = new Set(["rm", "rmdir", "shutdown", "reboot"]);
const PROHIBITED_GIT_ACTIONS = new Set([
  "commit", "push", "merge", "checkout", "switch", "reset", "clean", "rebase", "cherry-pick", "tag",
]);
const PROHIBITED_NPM_ACTIONS = new Set(["publish", "deploy"]);

function deny(description) {
  throw new ProcessError(`Workflow policy prohibits ${description}.`, { policy: "ai-local-no-publish-or-destructive-actions" });
}

export function assertAllowedWorkflowCommand(command, args = []) {
  const executable = path.basename(String(command));
  if (PROHIBITED_EXECUTABLES.has(executable)) deny(`the ${executable} executable`);
  if (executable === "git" && PROHIBITED_GIT_ACTIONS.has(args[0])) deny(`git ${args[0]}`);
  if ((executable === "npm" || executable === "pnpm" || executable === "yarn")
      && args.some((arg) => PROHIBITED_NPM_ACTIONS.has(String(arg).toLowerCase()))) {
    deny(`${executable} publishing or deployment`);
  }
  if (executable === "npm" && args[0] === "run" && args[1] === "ai:local") {
    deny("a nested ai:local workflow");
  }
  if (executable === "gh") {
    const joined = args.map(String).join(" ").toLowerCase();
    if (/\bissue\s+close\b/.test(joined)) deny("issue closure");
    if (/\bpr\s+(?:merge|close)\b/.test(joined)) deny("pull-request merge or closure");
  }
  if (executable === "openspec" && ["apply", "archive"].includes(String(args[0]).toLowerCase())) {
    deny(`openspec ${args[0]}`);
  }
}

export function createPolicyTransport(runCommand) {
  return async (command, args, options) => {
    assertAllowedWorkflowCommand(command, args);
    return runCommand(command, args, options);
  };
}

export function assertAllowedGraphQL(query) {
  const text = String(query);
  if (!/\bmutation\b/.test(text)) return;
  const updates = [...text.matchAll(/\bupdateProjectV2ItemFieldValue\s*\(/g)];
  if (updates.length !== 1) deny("a GraphQL mutation other than one Project item field update");
  if (/\b(?:closeIssue|updateIssue|deleteProjectV2Item|addProjectV2ItemById|clearProjectV2ItemFieldValue)\s*\(/.test(text)) {
    deny("issue closure or a non-selected Project mutation");
  }
}
