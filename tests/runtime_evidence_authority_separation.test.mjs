import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { require as tsxRequire } from "tsx/cjs/api";

const read = (value) => readFile(new URL(`../${value}`, import.meta.url), "utf8");
const imported = (value) => {
  const loaded = tsxRequire(`../${value}`, import.meta.url);
  return loaded.default ?? loaded;
};

test("immutable historical candidate projection and table preserve complete evidence", async () => {
  const immutable = JSON.parse(await read("data/candidate_model_comparison.json"));
  const dashboard = JSON.parse(await read("data/dashboard_summary.json"));
  const demo = imported("lib/demo-data.ts");
  const ModelComparisonTable = imported("components/validation/ModelComparisonTable.tsx");
  const labels = imported("lib/status-labels.ts");
  const sourceCount = immutable.candidates.length;
  assert.ok(sourceCount > 0);
  assert.equal(demo.historicalBenchmarkEvidence.comparison.candidates.length, sourceCount);
  const html = renderToStaticMarkup(createElement(ModelComparisonTable));
  const body = html.match(/<tbody[\s\S]*?<\/tbody>/)?.[0] ?? "";
  assert.equal((body.match(/<tr/g) ?? []).length, sourceCount);
  for (const candidate of immutable.candidates) {
    const metric = dashboard.candidate_model_comparison.aggregate_metrics[candidate.model_id];
    assert.ok(metric, `missing metrics for ${candidate.model_id}`);
    assert.match(body, new RegExp(labels.modelLabel(candidate.model_id).replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
    for (const value of [metric.mae, metric.rmse, metric.wape]) assert.match(body, new RegExp(value.toFixed(2).replace(".", "\\.")));
    assert.match(body, new RegExp(`${metric.successful_folds} \/ ${metric.failed_folds}`));
    assert.equal(typeof dashboard.candidate_model_comparison.selection_eligibility[candidate.model_id], "boolean");
  }
  const projectionSource = await read("lib/demo-data.ts");
  const projection = projectionSource.slice(projectionSource.indexOf("export const historicalBenchmarkEvidence"), projectionSource.indexOf("const activeAlerts"));
  assert.match(projectionSource, /@\/data\/candidate_model_comparison\.json/);
  assert.doesNotMatch(projection, /config\/candidate_models|current assignment|current assessment/i);
});

test("historical limitations separate operator copy from raw technical evidence", async () => {
  const ValidationLimitations = imported("components/validation/ValidationLimitations.tsx");
  const html = renderToStaticMarkup(createElement(ValidationLimitations));
  const technicalIndex = html.indexOf("<details");
  assert.notEqual(technicalIndex, -1);
  const normal = html.slice(0, technicalIndex);
  const technical = html.slice(technicalIndex);
  assert.match(normal, /Limitations of the Historical Benchmark/);
  assert.match(normal, /these historical results are based on/);
  assert.match(normal, /Permutation stability was not evaluated because each validation fold contains one row/);
  assert.match(normal, /The historical benchmark selected Random forest under its declared benchmark rule/);
  assert.match(normal, /Historical benchmark selection was recorded successfully/);
  for (const prohibited of [/random_forest/i, /adopted_p1\.2b/i, /P[012]\./, /active model/i]) assert.doesNotMatch(normal, prohibited);
  for (const retained of [/random_forest/i, /adopted_p1\.2b/i, /P0\.4/, /not_evaluated_single_row_folds/]) assert.match(technical, retained);
});

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

test("normal Provenance uses evidence classification and keeps identities in Technical evidence", async () => {
  const tabs = await read("components/evidence/EvidenceTabs.tsx");
  const provenance = tabs.slice(tabs.indexOf("function Provenance"), tabs.indexOf("function HistoricalCompatibilityEvidence"));
  const technicalIndex = provenance.indexOf("<details");
  const normal = provenance.slice(0, technicalIndex);
  const technical = provenance.slice(technicalIndex);
  assert.match(normal, /Historical run status/);
  assert.match(normal, /Historical benchmark winner/);
  assert.match(normal, /Evidence classification/);
  assert.match(normal, /Benchmark evidence only/);
  for (const prohibited of [/random_forest/i, /adopted_p1\.2b/i, /P[012]\./, /active_model_id/i, /SHA-256/]) assert.doesNotMatch(normal, prohibited);
  for (const retained of [/Historical run ID/, /Manifest SHA-256/, /Formula registry SHA-256/, /Forecasting scope configuration SHA-256/]) assert.match(technical, retained);
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
