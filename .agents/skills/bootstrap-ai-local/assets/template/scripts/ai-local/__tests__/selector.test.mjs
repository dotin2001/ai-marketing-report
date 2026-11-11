import assert from "node:assert/strict";
import { test } from "node:test";

import { selectIssue } from "../selector.mjs";

const items = [
  { issueNumber: 7, title: "First issue", url: "https://example.test/issues/7", projectItemId: "ITEM-7" },
  { issueNumber: 9, title: "Second issue", url: "https://example.test/issues/9", projectItemId: "ITEM-9" },
];

function fixture(answers) {
  let text = "";
  let index = 0;
  return {
    output: { write: (value) => (text += value) },
    prompt: { ask: async () => answers[index++] },
    get text() {
      return text;
    },
  };
}

test("selector shows issue number, title, and URL and returns one item", async () => {
  const io = fixture(["2"]);
  const result = await selectIssue(items, io);
  assert.equal(result.kind, "selected");
  assert.equal(result.item.projectItemId, "ITEM-9");
  assert.match(io.text, /#7 First issue — https:\/\/example\.test\/issues\/7/);
  assert.match(io.text, /#9 Second issue/);
});

test("selector retries invalid selections", async () => {
  const io = fixture(["nope", "0", "3", "1"]);
  const result = await selectIssue(items, io);
  assert.equal(result.item.projectItemId, "ITEM-7");
  assert.equal(io.text.match(/Invalid selection/g).length, 3);
});

for (const answer of ["q", "cancel", "", null]) {
  test(`selector safely cancels for ${String(answer)}`, async () => {
    const io = fixture([answer]);
    const result = await selectIssue(items, io);
    assert.deepEqual(result, { kind: "cancelled", exitCode: 0 });
    assert.match(io.text, /cancelled/i);
  });
}

test("no eligible items exits successfully without invoking prompt or side effects", async () => {
  let promptCalled = false;
  let mutationCalled = false;
  let fileCalled = false;
  let text = "";
  const result = await selectIssue([], {
    prompt: { ask: async () => (promptCalled = true) },
    output: { write: (value) => (text += value) },
    mutate: () => (mutationCalled = true),
    writeFile: () => (fileCalled = true),
  });

  assert.deepEqual(result, { kind: "no_items", exitCode: 0 });
  assert.equal(promptCalled, false);
  assert.equal(mutationCalled, false);
  assert.equal(fileCalled, false);
  assert.match(text, /No eligible Todo issues/);
});
