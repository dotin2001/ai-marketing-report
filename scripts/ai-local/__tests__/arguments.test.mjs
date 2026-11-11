import assert from "node:assert/strict";
import { test } from "node:test";

import { main, parseArguments } from "../cli.mjs";
import { UsageError } from "../errors.mjs";

test("argument parser accepts every supported form", () => {
  assert.deepEqual(parseArguments([]), { mode: "planning" });
  assert.deepEqual(parseArguments(["--help"]), { mode: "help" });
  assert.deepEqual(parseArguments(["-h"]), { mode: "help" });
  assert.deepEqual(parseArguments(["--sync-task"]), {
    mode: "sync",
    changeId: undefined,
  });
  assert.deepEqual(parseArguments(["--sync-task", "--change", "gh-42-example"]), {
    mode: "sync",
    changeId: "gh-42-example",
  });
  assert.deepEqual(parseArguments(["--change", "gh-42-example", "--sync-task"]), {
    mode: "sync",
    changeId: "gh-42-example",
  });
  assert.deepEqual(
    parseArguments(["--issue", "https://github.com/dotin2001/ai-marketing-report/issues/2"]),
    {
      mode: "planning",
      issueUrl: "https://github.com/dotin2001/ai-marketing-report/issues/2",
      issueTarget: {
        url: "https://github.com/dotin2001/ai-marketing-report/issues/2",
        repository: "dotin2001/ai-marketing-report",
        issueNumber: 2,
      },
    },
  );
});

for (const [name, args, message] of [
  ["unknown option", ["--wat"], /Unknown argument/],
  ["missing change value", ["--sync-task", "--change"], /requires/],
  ["option used as change value", ["--sync-task", "--change", "--help"], /requires/],
  ["change without sync", ["--change", "gh-1-test"], /only with/],
  ["invalid change id", ["--sync-task", "--change", "../escape"], /Invalid/],
  ["help conflict", ["--help", "--sync-task"], /cannot be combined/],
  ["duplicate sync", ["--sync-task", "--sync-task"], /only once/],
  ["duplicate change", ["--sync-task", "--change", "a", "--change", "b"], /only once/],
  ["missing issue URL", ["--issue"], /requires/],
  ["option used as issue URL", ["--issue", "--help"], /requires/],
  [
    "duplicate issue",
    ["--issue", "https://github.com/o/r/issues/1", "--issue", "https://github.com/o/r/issues/2"],
    /only once/,
  ],
  ["issue with sync", ["--issue", "https://github.com/o/r/issues/1", "--sync-task"], /cannot be combined/],
  [
    "issue with change",
    ["--issue", "https://github.com/o/r/issues/1", "--sync-task", "--change", "gh-1-test"],
    /cannot be combined/,
  ],
  ["issue with help", ["--issue", "https://github.com/o/r/issues/1", "--help"], /cannot be combined/],
  ["misspelled issue option", ["--issue--", "https://github.com/o/r/issues/1"], /Unknown argument/],
]) {
  test(`argument parser rejects ${name}`, () => {
    assert.throws(() => parseArguments(args), UsageError);
    assert.throws(() => parseArguments(args), message);
  });
}

test("invalid arguments return a typed outcome without running a workflow", async () => {
  let called = false;
  let errorText = "";
  const outcome = await main(["--change", "gh-1-test"], {
    errorOutput: { write: (value) => (errorText += value) },
    output: { write: () => {} },
    runPlanning: async () => {
      called = true;
    },
    runSync: async () => {
      called = true;
    },
  });

  assert.equal(called, false);
  assert.deepEqual(outcome, {
    kind: "error",
    code: "invalid_arguments",
    exitCode: 2,
  });
  assert.match(errorText, /invalid_arguments/);
});

test("invalid explicit issue URL stops before running a workflow", async () => {
  let called = false;
  const outcome = await main(["--issue", "not-a-github-issue-url"], {
    errorOutput: { write: () => {} },
    output: { write: () => {} },
    runPlanning: async () => {
      called = true;
    },
  });
  assert.equal(called, false);
  assert.equal(outcome.code, "invalid_arguments");
});
