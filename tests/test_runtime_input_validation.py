import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "analytics" / "runtime_validate.py"


def run_validation(root: Path, dengue: bytes, climate: bytes, deployment: str = "dhaka_south"):
    workspace = root / "11111111-1111-4111-8111-111111111111"
    original = workspace / "inputs" / "original"
    canonical = workspace / "inputs" / "canonical"
    metadata = workspace / "metadata"
    original.mkdir(parents=True)
    canonical.mkdir(parents=True)
    metadata.mkdir(parents=True)
    (original / "dengue.csv").write_bytes(dengue)
    (original / "climate.csv").write_bytes(climate)
    output = metadata / "validation.json"
    result = subprocess.run([
        sys.executable, str(VALIDATOR),
        "--workspace-root", str(workspace.resolve()),
        "--workspace-id", "11111111-1111-4111-8111-111111111111",
        "--created-at", "2026-07-13T00:00:00Z",
        "--dengue-input", str((original / "dengue.csv").resolve()),
        "--climate-input", str((original / "climate.csv").resolve()),
        "--canonical-dengue-output", str((canonical / "dengue_cases.csv").resolve()),
        "--canonical-climate-output", str((canonical / "climate_data.csv").resolve()),
        "--validation-output", str(output.resolve()),
        "--deployment-id", deployment,
        "--workflow-mode", "assess_dataset",
    ], cwd=ROOT, capture_output=True, text=True, timeout=30)
    return result, json.loads(output.read_text(encoding="utf-8"))


class RuntimeInputValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dengue = (ROOT / "data" / "dengue_cases.csv").read_bytes()
        cls.climate = (ROOT / "data" / "climate_data.csv").read_bytes()

    def test_valid_canonical_inputs_are_normalized_and_assessment_eligible(self):
        with tempfile.TemporaryDirectory() as directory:
            result, value = run_validation(Path(directory), self.dengue, self.climate)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(value["schemaVersion"], "1.0")
        self.assertEqual(value["workflowMode"], "assess_dataset")
        self.assertEqual(value["status"], "ready")
        self.assertEqual(value["counts"], {"caseRows": 180, "climateRows": 180, "overlapWeeks": 180, "labelledRows": 173})
        self.assertEqual(value["acceptedPeriod"], {"start": "2021-W01", "end": "2024-W24"})
        quick = value["eligibility"]["quickForecast"]
        self.assertTrue(quick["eligible"])
        self.assertEqual(quick["approvedModelId"], "random_forest")
        self.assertEqual(quick["uncertaintyStatus"], "pending_dataset_specific_calibration")
        self.assertEqual(quick["preparednessStatus"], "unavailable_missing_planning_policy")
        self.assertEqual(quick["policyId"], "RUNTIME.QUICK_FORECAST.COMPATIBILITY")
        self.assertTrue(value["eligibility"]["assessDataset"]["eligible"])
        self.assertEqual(value["eligibility"]["assessDataset"]["availableFoldCount"], 67)
        self.assertEqual(value["eligibility"]["assessDataset"]["plannedFoldCount"], 67)
        self.assertEqual(value["eligibility"]["assessDataset"]["minimumFoldCount"], 52)
        self.assertEqual(value["eligibility"]["assessDataset"]["maximumFoldCount"], 68)
        self.assertFalse(value["eligibility"]["assessDataset"]["foldCapApplied"])
        self.assertEqual(value["eligibility"]["assessDataset"]["selectedValidationStartIndex"], 106)
        self.assertEqual(value["eligibility"]["assessDataset"]["selectedValidationEndIndex"], 172)
        self.assertEqual(value["eligibility"]["assessDataset"]["policyVersion"], "p2-v3")
        self.assertEqual(
            value["eligibility"]["assessDataset"]["decisionCompatibilityStatus"],
            "phase2_decision_policy_not_yet_available",
        )
        self.assertEqual(value["eligibility"]["assessDataset"]["assessmentStatus"], "full_assessment_eligible")
        self.assertEqual(value["eligibility"]["assessDataset"]["foldPlan"]["targetPurgeRows"], 2)
        self.assertEqual(value["temporalValidation"]["policyVersion"], "b9.l-v1")
        self.assertEqual(value["temporalValidation"]["purgeGapWeeks"], 2)
        self.assertEqual(value["temporalValidation"]["datasetSnapshotClassification"], "retrospective_latest_revision")
        self.assertFalse(value["temporalValidation"]["trueHistoricalVintageDataAvailable"])
        serialized = json.dumps(value).lower()
        self.assertNotIn("53–187", serialized)
        self.assertNotIn("87/120/153", serialized)

    def test_current_quick_workspace_schema_requires_assignment_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            result, value = run_validation(Path(directory), self.dengue, self.climate)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        policy = json.loads(
            (ROOT / "config" / "deployments" / "dhaka_south" / "quick_forecast_policy.json").read_text(encoding="utf-8")
        )
        lifecycle = json.loads(
            (ROOT / "config" / "deployments" / "dhaka_south" / "model_lifecycle_policy.json").read_text(encoding="utf-8")
        )
        value["schemaVersion"] = "1.1"
        quick = value["eligibility"]["quickForecast"]
        quick.pop("approvedModelId")
        quick["assignedCandidateId"] = "poisson_gam"
        quick["policyVersion"] = policy["policyVersion"]
        quick["policySha256"] = policy["policySha256"]
        value["workflowMode"] = "quick_forecast"
        value["activeModelAuthority"] = {
            "authoritySource": "committed_assignment",
            "assignmentId": "11111111-1111-4111-8111-111111111111",
            "assignmentCommitSha256": "1" * 64,
            "authoritySnapshotSha256": "2" * 64,
            "assignedCandidateId": "poisson_gam",
            "candidateRegistrySha256": policy["candidateRegistrySha256"],
            "featureOrderSha256": policy["featureOrderSha256"],
            "lifecyclePolicyId": lifecycle["policyId"],
            "lifecyclePolicyVersion": lifecycle["policyVersion"],
            "lifecyclePolicySha256": lifecycle["policySha256"],
            "operationalPolicyId": policy["policyId"],
            "operationalPolicyVersion": policy["policyVersion"],
            "operationalPolicySha256": policy["policySha256"],
        }
        schema = json.loads((ROOT / "config" / "runtime_workspace.schema.json").read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
        validator.validate(value)
        for mutate in (
            lambda artifact: artifact.pop("activeModelAuthority"),
            lambda artifact: artifact["eligibility"]["quickForecast"].pop("assignedCandidateId"),
            lambda artifact: artifact["eligibility"]["quickForecast"].update(approvedModelId="random_forest"),
            lambda artifact: artifact.update(schemaVersion="1.0"),
        ):
            invalid = copy.deepcopy(value)
            mutate(invalid)
            with self.subTest(mutation=mutate):
                with self.assertRaises(jsonschema.ValidationError):
                    validator.validate(invalid)

    def test_assessment_workspace_schema_preserves_legacy_identity_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            result, value = run_validation(Path(directory), self.dengue, self.climate)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        schema = json.loads((ROOT / "config" / "runtime_workspace.schema.json").read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
        validator.validate(value)
        self.assertEqual(value["schemaVersion"], "1.0")
        self.assertEqual(value["workflowMode"], "assess_dataset")
        self.assertEqual(value["eligibility"]["quickForecast"]["approvedModelId"], "random_forest")
        self.assertNotIn("assignedCandidateId", value["eligibility"]["quickForecast"])
        self.assertNotIn("activeModelAuthority", value)

        missing_legacy = copy.deepcopy(value)
        missing_legacy["eligibility"]["quickForecast"].pop("approvedModelId")
        quick_replacement = copy.deepcopy(value)
        quick_replacement["eligibility"]["quickForecast"].pop("approvedModelId")
        quick_replacement["eligibility"]["quickForecast"]["assignedCandidateId"] = "poisson_gam"
        wrong_version = copy.deepcopy(value)
        wrong_version["schemaVersion"] = "1.1"
        for invalid in (missing_legacy, quick_replacement, wrong_version):
            with self.assertRaises(jsonschema.ValidationError):
                validator.validate(invalid)

    def test_missing_required_column_is_structured_user_invalidity(self):
        malformed = self.dengue.replace(b",cases,", b",case_count,", 1)
        with tempfile.TemporaryDirectory() as directory:
            result, value = run_validation(Path(directory), malformed, self.climate)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(value["status"], "invalid")
        self.assertIn("case_missing_required_column", {item["code"] for item in value["issues"]})

    def test_invalid_week_and_geography_mismatch_are_reported(self):
        invalid_week = self.dengue.replace(b"2021,1,", b"2021,53,", 1)
        different_geography = self.climate.replace(b"BGD-DHAKA-SOUTH", b"BGD-OTHER", 1)
        with tempfile.TemporaryDirectory() as directory:
            result, value = run_validation(Path(directory), invalid_week, different_geography)
        self.assertEqual(result.returncode, 0)
        codes = {item["code"] for item in value["issues"]}
        self.assertIn("case_epi_week_above_maximum", codes)
        self.assertTrue("climate_inconsistent_geography_id" in codes or "geography_mismatch" in codes)

    def test_non_contiguous_and_non_chronological_data_are_rejected(self):
        lines = self.dengue.decode("utf-8").splitlines()
        reordered = "\n".join([lines[0], lines[2], lines[1], *lines[3:]]) + "\n"
        with tempfile.TemporaryDirectory() as directory:
            result, value = run_validation(Path(directory), reordered.encode(), self.climate)
        self.assertEqual(result.returncode, 0)
        codes = {item["code"] for item in value["issues"]}
        self.assertIn("case_not_chronological", codes)

    def test_policy_rejects_consistent_but_out_of_scope_geography(self):
        dengue = self.dengue.replace(b"BGD-DHAKA-SOUTH", b"BGD-OTHER").replace(b"Dhaka South", b"Other City")
        climate = self.climate.replace(b"BGD-DHAKA-SOUTH", b"BGD-OTHER").replace(b"Dhaka South", b"Other City")
        with tempfile.TemporaryDirectory() as directory:
            result, value = run_validation(Path(directory), dengue, climate)
        self.assertEqual(result.returncode, 0)
        self.assertFalse(value["eligibility"]["quickForecast"]["eligible"])
        self.assertIn("geography_mismatch", value["eligibility"]["quickForecast"]["reasonCodes"])

    def test_policy_rejects_source_aggregation_and_short_history(self):
        unsupported_source = self.dengue.replace(b"synthetic_benchmark", b"uploaded_real")
        unsupported_aggregation = self.climate.replace(b"simulated_weekly_benchmark", b"daily_mean")
        with tempfile.TemporaryDirectory() as directory:
            result, value = run_validation(Path(directory), unsupported_source, unsupported_aggregation)
        self.assertEqual(result.returncode, 0)
        codes = value["eligibility"]["quickForecast"]["reasonCodes"]
        self.assertIn("source_type_not_approved", codes)
        self.assertIn("aggregation_not_approved", codes)

        dengue_lines = self.dengue.splitlines(keepends=True)[:111]
        climate_lines = self.climate.splitlines(keepends=True)[:111]
        with tempfile.TemporaryDirectory() as directory:
            result, value = run_validation(Path(directory), b"".join(dengue_lines), b"".join(climate_lines))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(value["counts"]["overlapWeeks"], 110)
        self.assertIn("insufficient_quick_history", value["eligibility"]["quickForecast"]["reasonCodes"])

    def test_runtime_schema_rejects_unknown_properties(self):
        with tempfile.TemporaryDirectory() as directory:
            result, value = run_validation(Path(directory), self.dengue, self.climate)
        self.assertEqual(result.returncode, 0)
        value["unexpected"] = True
        schema = json.loads((ROOT / "config" / "runtime_workspace.schema.json").read_text(encoding="utf-8"))
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.Draft202012Validator(schema).validate(value)


if __name__ == "__main__":
    unittest.main()
