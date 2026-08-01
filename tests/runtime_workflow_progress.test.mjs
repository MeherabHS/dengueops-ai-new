import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { require as tsxRequire } from "tsx/cjs/api";

const root = path.resolve(new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
const read = (file) => readFile(path.join(root, file), "utf8");

function runProgressLabels() {
  return execFileSync(process.execPath, [
    "--import=tsx",
    "--eval",
    "const imported=await import('./lib/status-labels.ts');const m=imported.default||imported;console.log(m.assessmentRunningLabel());console.log(m.assessmentRunningLabel(11));console.log(m.primaryCandidateStatusLabel('naive_baseline','baseline_only','complete'));console.log(m.primaryCandidateStatusLabel('learned_model','eligible_non_winner','complete'));console.log(m.primaryCandidateStatusLabel('learned_model','ineligible','ineligible'));",
  ], { cwd: root, encoding: "utf8" }).trim().split(/\r?\n/);
}

test("Strict Mode-safe polling effects re-arm mounted refs", async () => {
  const workflow = await read("components/forecast/ForecastRunWorkflow.tsx");
  const qualification = await read("components/forecast/ApprovedForecastPanel.tsx");
  for (const source of [workflow, qualification]) {
    assert.match(source, /useEffect\(\(\) => \{\s*mounted\.current = true;/);
    assert.match(source, /return \(\) => \{\s*mounted\.current = false;/);
    assert.doesNotMatch(source, /useEffect\(\(\) => \(\) => \{\s*mounted\.current = false/);
  }
  assert.match(workflow, /while \(mounted\.current\)/);
  assert.match(qualification, /while \(mounted\.current\)/);
});

test("asynchronous status presents spinner, elapsed time, and delayed guidance without fake percentages", async () => {
  const indicator = await read("components/forecast/AsyncStatusIndicator.tsx");
  assert.match(indicator, /LoaderCircle/);
  assert.match(indicator, /animate-spin/);
  assert.match(indicator, /elapsed/);
  assert.match(indicator, /taking longer than usual/);
  assert.doesNotMatch(indicator, /progressbar|aria-valuenow|% complete/);
});

test("assessment status refresh is read-only and duplicate mutation controls remain guarded", async () => {
  const workflow = await read("components/forecast/ForecastRunWorkflow.tsx");
  const check = workflow.slice(workflow.indexOf("const checkAssessmentStatus"), workflow.indexOf("useEffect(() => {\n    if (recoveryStarted"));
  assert.match(check, /getRuntimeJob\(state\.assessmentJobId\)/);
  assert.doesNotMatch(check, /startDatasetAssessment|recordAssessmentDecision|fetch\([^)]*POST/);
  assert.match(workflow, /assessmentAction\.current/);
  assert.match(workflow, /disabled=\{!assessmentReady \|\| assessmentAction\.current\}/);
});

test("assessment running status uses a trusted optional count without hardcoding registry size", async () => {
  assert.deepEqual(runProgressLabels(), [
    "Evaluating governed candidates",
    "Evaluating 11 governed candidates",
    "Baseline",
    "Eligible",
    "Candidate ineligible",
  ]);
  const workflow = await read("components/forecast/ForecastRunWorkflow.tsx");
  const processing = await read("components/forecast/ProcessingState.tsx");
  assert.match(workflow, /candidateSetStatus === "complete_candidate_set"/);
  assert.match(workflow, /Object\.keys\(state\.serverValidation\.response\.eligibility\.assessDataset\.candidateEligibility\)\.length/);
  assert.match(workflow, /candidateCount=\{assessmentCandidateCount\}/);
  assert.match(workflow, /validationCandidateCount \?\? recoveredJobCandidateCount/);
  assert.match(workflow, /state\.job\.verifiedCandidateCount/);
  assert.match(processing, /assessmentRunningLabel\(candidateCount\)/);
  assert.doesNotMatch(`${workflow}\n${processing}`, /candidateCount\s*=\s*11/);
  const dynamicFixtureCount = 3;
  const labels = tsxRequire("../lib/status-labels.ts", import.meta.url);
  assert.equal(labels.assessmentRunningLabel(dynamicFixtureCount), "Evaluating 3 governed candidates");
});

test("qualification pre-POST presentation includes real spinner, elapsed time, and a disabled control", async () => {
  const qualification = await read("components/forecast/ApprovedForecastPanel.tsx");
  const indicatorModule = tsxRequire("../components/forecast/AsyncStatusIndicator.tsx", import.meta.url);
  const AsyncStatusIndicator = indicatorModule.default ?? indicatorModule;
  const html = renderToStaticMarkup(createElement(AsyncStatusIndicator, { label: "Starting qualification run…" }));
  assert.match(html, /Starting qualification run…/);
  assert.match(html, /animate-spin/);
  assert.match(html, /0s elapsed/);
  assert.match(qualification, /isStartingQualification[\s\S]*<Button disabled>Starting qualification run…<\/Button>/);
  assert.match(qualification, /runQualificationStartOnce/);
  assert.doesNotMatch(qualification, /setTimeout\([^)]*Starting qualification|sleep/i);
});

test("active steps expose spinner, completion check, failure, and conflict icons", async () => {
  const stepper = await read("components/forecast/ForecastRunStepper.tsx");
  assert.match(stepper, /LoaderCircle/);
  assert.match(stepper, /animate-spin/);
  assert.match(stepper, /<Check /);
  assert.match(stepper, /<CircleX /);
  assert.match(stepper, /<AlertTriangle /);
});

test("governed mutation panels show operation-specific progress labels", async () => {
  const sources = await Promise.all([
    read("components/forecast/ApprovalPanel.tsx"),
    read("components/forecast/ApprovedForecastPanel.tsx"),
    read("components/forecast/ModelAssignmentPanel.tsx"),
    read("components/forecast/QuickForecastRunPanel.tsx"),
  ]);
  const combined = sources.join("\n");
  for (const label of [
    "Recording governed decision",
    "Starting qualification run…",
    "Waiting for qualification worker",
    "Executing selected candidate for assignment evidence",
    "Publishing governed assignment",
    "Verifying current model authority",
    "Waiting for forecasting worker",
    "Generating forecast with the current assigned model",
    "Verifying the completed run as the current forecast",
  ]) assert.match(combined, new RegExp(label));
});
