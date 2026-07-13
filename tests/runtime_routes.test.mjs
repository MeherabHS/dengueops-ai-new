import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const route = await readFile(new URL("../app/api/runtime/validate/route.ts", import.meta.url), "utf8");
const uploads = await readFile(new URL("../lib/runtime/uploads.ts", import.meta.url), "utf8");
const workflow = await readFile(new URL("../components/forecast/ForecastRunWorkflow.tsx", import.meta.url), "utf8");

test("validation route is Node-only, multipart, bounded, and shell-free", () => {
  assert.match(route, /export const runtime = "nodejs"/);
  assert.match(route, /request\.formData\(\)/);
  assert.match(route, /getAll\(name\)/);
  assert.match(route, /shell: false/);
  assert.match(route, /validationTimeoutMs/);
});

test("CSV upload inspection rejects unsafe input classes", () => {
  for (const marker of ["invalid_file_extension", "upload_too_large", "nul_byte_detected", "invalid_utf8", "duplicate_csv_header", "inconsistent_csv_width"]) {
    assert.match(uploads, new RegExp(marker));
  }
  assert.match(uploads, /path\.basename\(name\)/);
  assert.match(uploads, /safeOriginalName/);
});

test("frontend starts only eligible Quick Forecast and refreshes only after commit", () => {
  assert.match(workflow, /validateRuntimeDatasets/);
  assert.match(workflow, /Start Quick Forecast/);
  assert.match(workflow, /job\.status === "completed"/);
  assert.match(workflow, /latest\.runId !== job\.committedRunId/);
  assert.doesNotMatch(workflow, /setInterval|run_pipeline|EventSource|WebSocket/);
});
