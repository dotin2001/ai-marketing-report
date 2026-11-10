import assert from "node:assert/strict";
import { test } from "node:test";

import { HELP_TEXT, main } from "../cli.mjs";

test("help describes planning and synchronization without side effects", async () => {
  let written = "";
  const outcome = await main(["--help"], {
    output: { write: (value) => (written += value) },
  });

  assert.deepEqual(outcome, { kind: "help", exitCode: 0 });
  assert.equal(written, HELP_TEXT);
  assert.match(written, /--sync-task/);
  assert.match(written, /never applies a change/);
});
