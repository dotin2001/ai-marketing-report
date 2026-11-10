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
