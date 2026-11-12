import assert from "node:assert/strict";
import test from "node:test";

import { validateContractTexts } from "../check-environment-contract.mjs";

const valid = {
  backendConfig: 'value: str = Field(validation_alias="SERVER_SECRET")',
  backendExample: "SERVER_SECRET=CHANGE_ME_PRIVATE_VALUE\n",
  compose: "environment:\n  SERVER_SECRET: ${SERVER_SECRET:?Set SERVER_SECRET}\n",
  docs: "Replace SERVER_SECRET and set NEXT_PUBLIC_API_BASE_URL.",
  frontendExample: "NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000\n",
  infraExample: "SERVER_SECRET=CHANGE_ME_PRIVATE_VALUE\n",
};

test("environment contract accepts aligned keys", () => {
  assert.doesNotThrow(() => validateContractTexts(valid));
});

test("an omitted setting fails with its name and not its value", () => {
  assert.throws(
    () => validateContractTexts({ ...valid, backendExample: "" }),
    (error) => {
      assert.match(error.message, /SERVER_SECRET/u);
      assert.doesNotMatch(error.message, /CHANGE_ME_PRIVATE_VALUE/u);
      return true;
    },
  );
});

test("a browser-exposed secret fails without printing its value", () => {
  assert.throws(
    () =>
      validateContractTexts({
        ...valid,
        frontendExample:
          "NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000\nNEXT_PUBLIC_API_KEY=do-not-print-me\n",
      }),
    (error) => {
      assert.match(error.message, /NEXT_PUBLIC_API_KEY/u);
      assert.doesNotMatch(error.message, /do-not-print-me/u);
      return true;
    },
  );
});
