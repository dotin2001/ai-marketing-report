import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";
import path from "node:path";

const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");

test("focused storage commands are discoverable and keep live checks explicit", async () => {
  const manifest = JSON.parse(await readFile(path.join(repositoryRoot, "package.json"), "utf8"));
  assert.match(manifest.scripts["backend:test:storage"], /tests\/unit\/storage/u);
  assert.match(manifest.scripts["database:test:storage"], /test_storage_assets\.py/u);
  assert.match(manifest.scripts["storage:test:live"], /storage_live/u);
  assert.match(manifest.scripts["storage:test:live"], /infra:up/u);
  assert.match(manifest.scripts["infra:up"], /env -u S3_BUCKET/u);
  assert.match(manifest.scripts["backend:test"], /not storage_live/u);
  assert.doesNotMatch(manifest.scripts["backend:check"], /storage:test:live/u);
});
