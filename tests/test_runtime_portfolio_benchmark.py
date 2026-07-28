from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))

from portfolio_benchmark_evidence import canonical_sha256
from runtime_portfolio_benchmark import (
    ARTIFACT_SCHEMA_PATH,
    COMMIT_SCHEMA_PATH,
    RuntimePortfolioBenchmarkError,
    _load_policy,
    publish_benchmark,
    verify_benchmark_dir,
    verify_source_assessment,
)
from tests.test_portfolio_benchmark_evidence import IDS, source_fixture


def runtime_source(base: Path):
    source = source_fixture()
    assessment_id = source["rolling"]["assessmentId"]
    assessment = (base / "runtime" / "assessments" / assessment_id).resolve()
    commit_bytes = (json.dumps({"assessmentId": assessment_id}, indent=2) + "\n").encode()
    source.update({
        "assessmentPath": str(assessment),
        "assessmentCommitBytes": commit_bytes,
        "assessmentCommitSha256": hashlib.sha256(commit_bytes).hexdigest(),
        "artifactHashes": {
            "assessment_summary.json": "1" * 64,
            "candidate_model_comparison.json": "2" * 64,
            "input_manifest.json": "3" * 64,
            "model_features.csv": "4" * 64,
            "recommendation.json": "5" * 64,
            "rolling_validation.json": "6" * 64,
        },
        "candidateOrder": list(IDS),
        "registryVersion": "p2-v2",
        "registrySha256": "7" * 64,
        "assessmentPolicy": {
            "policyId": "RUNTIME.DATASET_ASSESSMENT.GOVERNANCE",
            "policyVersion": "p2-v3", "policySha256": "8" * 64,
        },
    })
    policy, raw_sha = _load_policy()
    source["policy"] = policy
    source["policyRawSha256"] = raw_sha
    return source


class RuntimePortfolioBenchmarkTests(unittest.TestCase):
    def test_policy_and_schemas_are_strict(self):
        policy, raw_sha = _load_policy()
        self.assertEqual(policy["policySha256"], canonical_sha256({
            key: value for key, value in policy.items() if key != "policySha256"
        }))
        self.assertRegex(raw_sha, r"^[0-9a-f]{64}$")
        for path in (ARTIFACT_SCHEMA_PATH, COMMIT_SCHEMA_PATH):
            schema = json.loads(path.read_text())
            Draft202012Validator.check_schema(schema)
            self.assertFalse(schema["additionalProperties"])

    def test_production_source_rejects_tmp_test_and_missing_packages(self):
        with self.assertRaisesRegex(RuntimePortfolioBenchmarkError, "tmp, test, or fixture"):
            verify_source_assessment((ROOT / "tmp/assessments/11111111-1111-4111-8111-111111111111").resolve())
        with self.assertRaisesRegex(RuntimePortfolioBenchmarkError, "package directories"):
            with tempfile.TemporaryDirectory(dir=ROOT) as directory:
                source = Path(directory) / "runtime/assessments/11111111-1111-4111-8111-111111111111"
                source.mkdir(parents=True)
                verify_source_assessment(source.resolve())

    def test_atomic_publication_snapshot_and_later_verification(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            base = Path(directory)
            source = runtime_source(base)
            output = (base / "runtime/portfolio-benchmarks").resolve()
            benchmark_id = "22222222-2222-4222-8222-222222222222"
            with patch("runtime_portfolio_benchmark.verify_source_assessment", return_value=source):
                result = publish_benchmark(
                    assessment_dir=source["assessmentPath"], output_root=output,
                    evidence_scope="synthetic_qualification", benchmark_id=benchmark_id,
                    generated_at="2026-01-01T00:00:00Z",
                )
                verified = verify_benchmark_dir(Path(result["benchmarkPath"]))
            root = Path(result["benchmarkPath"])
            self.assertEqual(
                (root / "artifacts/source_assessment_commit.json").read_bytes(),
                source["assessmentCommitBytes"],
            )
            self.assertEqual(verified["commit"]["sourceArtifactHashes"], source["artifactHashes"])
            self.assertFalse((output.parent / "portfolio-benchmark-staging" / benchmark_id).exists())

    def test_existing_id_and_tamper_fail_closed(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            base = Path(directory)
            source = runtime_source(base)
            output = (base / "runtime/portfolio-benchmarks").resolve()
            benchmark_id = "22222222-2222-4222-8222-222222222222"
            with patch("runtime_portfolio_benchmark.verify_source_assessment", return_value=source):
                result = publish_benchmark(
                    assessment_dir=source["assessmentPath"], output_root=output,
                    evidence_scope="synthetic_qualification", benchmark_id=benchmark_id,
                    generated_at="2026-01-01T00:00:00Z",
                )
                with self.assertRaisesRegex(RuntimePortfolioBenchmarkError, "already exists"):
                    publish_benchmark(
                        assessment_dir=source["assessmentPath"], output_root=output,
                        evidence_scope="synthetic_qualification", benchmark_id=benchmark_id,
                    )
                artifact = Path(result["benchmarkPath"]) / "artifacts/portfolio_benchmark.json"
                artifact.chmod(stat.S_IWRITE | stat.S_IREAD)
                artifact.write_bytes(artifact.read_bytes() + b" ")
                with self.assertRaisesRegex(RuntimePortfolioBenchmarkError, "hash mismatch"):
                    verify_benchmark_dir(Path(result["benchmarkPath"]))

    def test_wrong_scope_fails_and_no_authority_files_are_written(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            base = Path(directory)
            source = runtime_source(base)
            output = (base / "runtime/portfolio-benchmarks").resolve()
            registry_before = (ROOT / "config/candidate_models.json").read_bytes()
            with patch("runtime_portfolio_benchmark.verify_source_assessment", return_value=source):
                with self.assertRaisesRegex(RuntimePortfolioBenchmarkError, "synthetic qualification"):
                    publish_benchmark(
                        assessment_dir=source["assessmentPath"], output_root=output,
                        evidence_scope="real_dhaka",
                    )
            self.assertEqual((ROOT / "config/candidate_models.json").read_bytes(), registry_before)
            self.assertFalse(output.exists())

    def test_commit_snapshot_tamper_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            base = Path(directory)
            source = runtime_source(base)
            output = (base / "runtime/portfolio-benchmarks").resolve()
            with patch("runtime_portfolio_benchmark.verify_source_assessment", return_value=source):
                result = publish_benchmark(
                    assessment_dir=source["assessmentPath"], output_root=output,
                    evidence_scope="synthetic_qualification",
                    benchmark_id="22222222-2222-4222-8222-222222222222",
                    generated_at="2026-01-01T00:00:00Z",
                )
                snapshot = Path(result["benchmarkPath"]) / "artifacts/source_assessment_commit.json"
                snapshot.chmod(stat.S_IWRITE | stat.S_IREAD)
                snapshot.write_bytes(snapshot.read_bytes() + b" ")
                with self.assertRaisesRegex(RuntimePortfolioBenchmarkError, "snapshot hash mismatch"):
                    verify_benchmark_dir(Path(result["benchmarkPath"]))


if __name__ == "__main__":
    unittest.main()
