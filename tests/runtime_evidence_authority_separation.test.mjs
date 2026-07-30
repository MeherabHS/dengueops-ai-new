import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const read = (value) => readFile(new URL(`../${value}`, import.meta.url), "utf8");

test("Evidence page declares four non-overlapping evidence families", async () => {
  const [page, tabs] = await Promise.all([
    read("app/validation/page.tsx"),
    read("components/evidence/EvidenceTabs.tsx"),
  ]);
  for (const heading of [
    "Current runtime authority",
    "Uploaded assessment evidence",
    "Historical benchmark evidence",
    "Historical compatibility evidence",
  ]) assert.match(`${page}\n${tabs}`, new RegExp(heading));
});

test("bundled benchmark projection cannot claim current or active model authority", async () => {
  const sources = await Promise.all([
    read("components/evidence/EvidenceTabs.tsx"),
    read("components/validation/ModelSummaryCards.tsx"),
    read("components/validation/ModelComparisonTable.tsx"),
  ]);
  const bundled = sources.join("\n");
  assert.match(bundled, /Historical benchmark winner/);
  assert.match(bundled, /Benchmark evidence only/);
  for (const prohibited of [
    /Active model/i,
    /Active forecast model/i,
    /Selected model adopted/i,
    /Random Forest is active/i,
    /deployment-wide model/i,
  ]) assert.doesNotMatch(bundled, prohibited);
});

test("historical Gradient Boosting is distinct and raw phase values stay in Technical evidence", async () => {
  const tabs = await read("components/evidence/EvidenceTabs.tsx");
  assert.match(tabs, /Historical Gradient Boosting validation evidence/);
  assert.match(tabs, /not Histogram gradient boosting/);
  assert.match(tabs, /<details[\s\S]*Technical evidence[\s\S]*P1\.1[\s\S]*<\/details>/);
  assert.doesNotMatch(tabs, /Historical P1\.1 Gradient Boosting/);
});

test("operator terminology is friendly while raw policy values remain in Technical evidence", async () => {
  const design = await read("components/validation/ValidationDesignSection.tsx");
  assert.match(design, /Only outcomes available by each forecast date were used/);
  assert.match(design, /Benchmark comparison completed/);
  assert.match(design, /<details[\s\S]*Technical evidence[\s\S]*P1\.4[\s\S]*label_availability_policy/s);
  assert.doesNotMatch(design, /Label policy:\s*\{rv\.label_availability_policy\}/);
});

test("qualification evidence cannot populate current dashboard authority", async () => {
  const workflow = await read("components/validation/RuntimeAssessmentWorkflow.tsx");
  assert.doesNotMatch(workflow, /getLatestDashboard|sessionStorage|dengueops-latest-dashboard/);
  assert.match(workflow, /Qualification evidence committed/);
  assert.match(workflow, /does not populate current dashboard authority/);
});

test("historical projection omits legacy current-model fields", async () => {
  const source = await read("lib/demo-data.ts");
  const start = source.indexOf("export const historicalBenchmarkEvidence");
  const projection = source.slice(start, source.indexOf("const activeAlerts", start));
  assert.match(projection, /winnerModelId/);
  assert.doesNotMatch(projection, /current_forecast_model|current_approved_model_label/);
});

test("historical compatibility copy never describes benchmark residuals as active",async()=>{
  const panel=await read("components/validation/ErrorComparisonPanel.tsx");
  assert.match(panel,/Historical Random Forest residual evidence/);
  assert.match(panel,/benchmark compatibility evidence only/);
  assert.doesNotMatch(panel,/active uncertainty|current uncertainty/i);
});
