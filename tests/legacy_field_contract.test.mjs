import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "..");
const read = (relative) => fs.readFileSync(path.join(root, relative), "utf8");

const activeSources = [
  "lib/types.ts",
  "lib/risk-utils.ts",
  "lib/surgeScenarios.ts",
  "components/home/PrototypePreviewSection.tsx",
  "components/methodology/OperationalLogicSection.tsx",
  "components/methodology/PipelineOverview.tsx",
  "components/dashboard/DirectiveTable.tsx",
  "components/dashboard/FacilityReadinessView.tsx",
  "components/dashboard/FacilityReadinessTable.tsx",
];

test("active bundled contracts and UI do not consume legacy fields", () => {
  for (const relative of activeSources) {
    const source = read(relative);
    if (relative === "lib/types.ts") {
      assert.doesNotMatch(source, /\b(?:risk_level|risk_score|recommendations)\b/, relative);
    } else {
      assert.doesNotMatch(source, /(?:\.|\[["'`])(?:risk_level|risk_score|recommendations)(?:["'`\]])?/, relative);
    }
    assert.doesNotMatch(source, /["'`]Risk (?:Level|Score)["'`]/, relative);
  }
});

test("bundled data normalization rejects aliases and has no fallback", () => {
  const source = read("lib/demo-data.ts");
  assert.match(source, /rejectLegacyAliases/);
  assert.match(source, /requireCanonicalForecastFields/);
  assert.doesNotMatch(source, /experimental_growth_score\s*\?\?/);
});

test("active API routes do not expose legacy response keys", () => {
  const apiRoot = path.join(root, "app", "api");
  const routes = [];
  const visit = (directory) => {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const full = path.join(directory, entry.name);
      if (entry.isDirectory()) visit(full);
      else if (/route\.(?:ts|tsx)$/.test(entry.name)) routes.push(full);
    }
  };
  visit(apiRoot);
  for (const route of routes) {
    assert.doesNotMatch(fs.readFileSync(route, "utf8"), /\b(?:risk_level|risk_score|recommendations)\s*:/, route);
  }
});

test("canonical terminology includes the required prototype limitations", () => {
  const copy = [
    read("components/home/PrototypePreviewSection.tsx"),
    read("components/methodology/OperationalLogicSection.tsx"),
  ].join("\n");
  assert.match(copy, /Experimental growth score/i);
  assert.match(copy, /provisional/i);
  assert.match(copy, /not (?:a )?probability/i);
  assert.match(copy, /validated risk score/i);
  assert.doesNotMatch(copy, /institution-approved recommendations/i);
});
