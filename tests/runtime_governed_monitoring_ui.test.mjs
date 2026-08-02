import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import path from "node:path";
import test from "node:test";

const root=path.resolve(new URL("..",import.meta.url).pathname.replace(/^\/([A-Za-z]:)/,"$1"));
const read=(name)=>readFile(path.join(root,name),"utf8");

test("dashboard presents confidence as evidence rather than probability",async()=>{
  const [page,chart]=await Promise.all([read("app/dashboard/page.tsx"),read("components/overview/ForecastTrendChart.tsx")]);
  assert.match(page,/Forecast confidence/);assert.match(page,/not a probability/);assert.match(page,/forecast_evidence_confidence/);
  assert.match(chart,/Forecast confidence:/);assert.match(chart,/Input drift:/);assert.match(chart,/\{rangeAvailable\?<Scatter/);
  assert.doesNotMatch(`${page}\n${chart}`,/Accuracy \d|chance of being correct|Model certainty/);
});

test("dashboard preserves the manual reassessment route and does not automate it",async()=>{
  const page=await read("app/dashboard/page.tsx");
  assert.match(page,/Model reassessment recommended/);assert.match(page,/href="\/forecast\?intent=reassess"/);
  assert.doesNotMatch(page,/startDatasetAssessment|startModelAssignment/);
});

test("monitoring reader rejects stale assignment forecast and hash evidence",async()=>{
  const reader=await read("lib/runtime/governed-monitoring-reader.ts");
  for(const evidence of ["pointer.forecastRunId!==verified.pointer.runId","pointer.datasetId!==verified.pointer.datasetId","pointer.forecastLatestSha256!==verified.pointerSha256","pointer.assignmentPointerSha256!==sha(assignmentPointerBytes)","sha(evidenceBytes)!==pointer.evidenceSha256","sha(commitBytes)!==pointer.commitSha256"]){assert.match(reader,new RegExp(evidence.replace(/[.*+?^${}()|[\]\\]/g,"\\$&")))}
  assert.match(reader,/confidenceAffectsPreparedness!==false/);assert.match(reader,/modelAutoReassigned!==false/);
});
