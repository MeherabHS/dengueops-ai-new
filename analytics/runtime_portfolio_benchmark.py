"""Verify one durable assessment and publish an immutable portfolio benchmark."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

ANALYTICS_DIR = Path(__file__).resolve().parent
ROOT = ANALYTICS_DIR.parent
if str(ANALYTICS_DIR) not in sys.path:
    sys.path.insert(0, str(ANALYTICS_DIR))

from portfolio_benchmark_evidence import (  # noqa: E402
    PortfolioBenchmarkEvidenceError,
    build_benchmark,
    canonical_sha256,
)
from runtime_assessment_evidence import fold_plan_sha256  # noqa: E402


POLICY_PATH = ROOT / "config" / "portfolio_benchmark_policy.json"
REGISTRY_PATH = ROOT / "config" / "candidate_models.json"
ARTIFACT_SCHEMA_PATH = ROOT / "config" / "runtime_portfolio_benchmark.schema.json"
COMMIT_SCHEMA_PATH = ROOT / "config" / "runtime_portfolio_benchmark_commit.schema.json"
SOURCE_SCHEMAS = {
    "artifacts/rolling_validation.json": "runtime_rolling_validation.schema.json",
    "artifacts/candidate_model_comparison.json": "runtime_candidate_comparison.schema.json",
    "artifacts/recommendation.json": "runtime_recommendation.schema.json",
    "artifacts/assessment_summary.json": "runtime_assessment_summary.schema.json",
    "metadata/assessment.json": "runtime_assessment.schema.json",
    "metadata/commit.json": "runtime_assessment_commit.schema.json",
}
SOURCE_ARTIFACTS = (
    "assessment_summary.json",
    "candidate_model_comparison.json",
    "input_manifest.json",
    "model_features.csv",
    "recommendation.json",
    "rolling_validation.json",
)
SOURCE_METADATA = ("assessment.json", "commit.json", "policy.json", "validation.json")
UUID4 = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
SHA256 = re.compile(r"^[0-9a-f]{64}$")
POLICY_KEYS = {
    "policyId", "policyVersion", "policyStatus", "policySha256", "policyHashMethod",
    "acceptedSourceAssessment", "acceptedCandidateRegistry", "target", "horizonWeeks",
    "evidenceScopes", "primaryComparisonCohort", "metrics", "tieTolerance",
    "correlationMethod", "correlationStatuses", "descriptiveStrata", "rankingStability",
    "rationalization", "prohibitedActions",
}


class RuntimePortfolioBenchmarkError(RuntimeError):
    """Raised when a portfolio benchmark cannot be verified or published."""


def _reject_constant(value: str) -> None:
    raise ValueError(f"Non-standard JSON numeric constant: {value}.")


def _json_bytes(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimePortfolioBenchmarkError(f"{label} is not strict UTF-8 JSON.") from exc
    if not isinstance(value, dict):
        raise RuntimePortfolioBenchmarkError(f"{label} must contain a JSON object.")
    return value


def _json(path: Path, label: str | None = None) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise RuntimePortfolioBenchmarkError(f"Missing or unreadable {label or path.name}.") from exc
    return _json_bytes(raw, label or path.name)


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical_policy_sha256(policy: Mapping[str, Any]) -> str:
    content = dict(policy)
    content.pop("policySha256", None)
    return canonical_sha256(content)


def _schema(path: Path) -> dict[str, Any]:
    return _json(path, path.name)


def _validate_schema(value: Any, schema_path: Path, label: str) -> None:
    errors = sorted(
        Draft202012Validator(
            _schema(schema_path), format_checker=FormatChecker()
        ).iter_errors(value),
        key=lambda error: list(error.path),
    )
    if errors:
        raise RuntimePortfolioBenchmarkError(
            f"{label} failed schema validation: {errors[0].message}"
        )


def _load_policy() -> tuple[dict[str, Any], str]:
    raw = POLICY_PATH.read_bytes()
    policy = _json_bytes(raw, "portfolio benchmark policy")
    if set(policy) != POLICY_KEYS:
        raise RuntimePortfolioBenchmarkError("Portfolio benchmark policy has unexpected or missing fields.")
    canonical = _canonical_policy_sha256(policy)
    if policy["policySha256"] != canonical or policy["policyStatus"] != "active":
        raise RuntimePortfolioBenchmarkError("Portfolio benchmark policy identity is invalid.")
    if policy["rationalization"] != {
        "allowedCategories": [
            "KEEP_CORE", "KEEP_SPECIALIST", "KEEP_PENDING_MORE_DATA",
            "REDUNDANCY_CANDIDATE", "RETIREMENT_CANDIDATE", "INSUFFICIENT_EVIDENCE",
        ],
        "syntheticQualificationAllowedCategories": [
            "KEEP_CORE", "KEEP_SPECIALIST", "KEEP_PENDING_MORE_DATA", "INSUFFICIENT_EVIDENCE",
        ],
        "retirementThresholdStatus": "not_governed",
        "redundancyThresholdStatus": "not_governed",
        "automaticCandidateRemovalAllowed": False,
        "automaticRegistryMutationAllowed": False,
        "automaticAssignmentMutationAllowed": False,
        "automaticPolicyMutationAllowed": False,
    }:
        raise RuntimePortfolioBenchmarkError("Portfolio rationalization restrictions are invalid.")
    return policy, _sha256_bytes(raw)


def _reject_temporary(path: Path, label: str) -> None:
    lowered = [part.lower() for part in path.resolve().parts]
    if any(part in {"tmp", "temp", "tests", "test"} or "fixture" in part for part in lowered):
        raise RuntimePortfolioBenchmarkError(f"{label} cannot use tmp, test, or fixture storage.")


def _exact_source_files(assessment_dir: Path) -> None:
    artifacts = assessment_dir / "artifacts"
    metadata = assessment_dir / "metadata"
    if not artifacts.is_dir() or not metadata.is_dir():
        raise RuntimePortfolioBenchmarkError("Assessment package directories are missing.")
    artifact_names = sorted(path.name for path in artifacts.iterdir() if path.is_file())
    metadata_names = sorted(path.name for path in metadata.iterdir() if path.is_file())
    if artifact_names != sorted(SOURCE_ARTIFACTS) or metadata_names != sorted(SOURCE_METADATA):
        raise RuntimePortfolioBenchmarkError("Assessment package has missing or unexpected files.")


def verify_source_assessment(assessment_dir: str | Path) -> dict[str, Any]:
    source = Path(assessment_dir)
    if not source.is_absolute():
        raise RuntimePortfolioBenchmarkError("Assessment directory must be an explicit absolute path.")
    source = source.resolve()
    _reject_temporary(source, "Assessment source")
    if not UUID4.fullmatch(source.name) or source.parent.name != "assessments":
        raise RuntimePortfolioBenchmarkError("Assessment source must be an explicit assessments/<assessmentId> package.")
    _exact_source_files(source)

    values: dict[str, dict[str, Any]] = {}
    for relative, schema_name in SOURCE_SCHEMAS.items():
        path = source / relative
        value = _json(path, relative)
        _validate_schema(value, ROOT / "config" / schema_name, relative)
        values[relative] = value
    rolling = values["artifacts/rolling_validation.json"]
    comparison = values["artifacts/candidate_model_comparison.json"]
    summary = values["artifacts/assessment_summary.json"]
    assessment = values["metadata/assessment.json"]
    commit = values["metadata/commit.json"]
    policy_snapshot = _json(source / "metadata/policy.json", "metadata/policy.json")
    validation = _json(source / "metadata/validation.json", "metadata/validation.json")
    manifest = _json(source / "artifacts/input_manifest.json", "artifacts/input_manifest.json")

    identities = {
        str(value.get("assessmentId"))
        for value in (rolling, comparison, summary, assessment, commit, manifest)
    }
    if identities != {source.name}:
        raise RuntimePortfolioBenchmarkError("Assessment ID reconciliation failed.")
    deployments = {
        str(value.get("deploymentId"))
        for value in (rolling, comparison, summary, assessment, commit, manifest, validation)
    }
    if deployments != {"dhaka_south"}:
        raise RuntimePortfolioBenchmarkError("Assessment deployment reconciliation failed.")

    policy, policy_raw_sha = _load_policy()
    accepted_assessment = policy["acceptedSourceAssessment"]
    actual_policy = {
        "schemaVersion": commit["schemaVersion"],
        "policyId": commit["assessmentPolicyId"],
        "policyVersion": commit["assessmentPolicyVersion"],
        "policySha256": commit["assessmentPolicySha256"],
    }
    if actual_policy != accepted_assessment:
        raise RuntimePortfolioBenchmarkError("Assessment policy authority mismatch.")
    if (
        policy_snapshot.get("policy_id") != accepted_assessment["policyId"]
        or policy_snapshot.get("policy_version") != accepted_assessment["policyVersion"]
        or policy_snapshot.get("policy_sha256") != accepted_assessment["policySha256"]
    ):
        raise RuntimePortfolioBenchmarkError("Assessment policy snapshot mismatch.")

    registry_raw = REGISTRY_PATH.read_bytes()
    registry = _json_bytes(registry_raw, "candidate registry")
    registry_sha = _sha256_bytes(registry_raw)
    accepted_registry = policy["acceptedCandidateRegistry"]
    if (
        registry.get("candidate_registry_version") != accepted_registry["version"]
        or registry_sha != accepted_registry["sha256"]
        or commit["candidateRegistrySha256"] != registry_sha
    ):
        raise RuntimePortfolioBenchmarkError("Candidate registry authority mismatch.")
    candidate_order = [str(candidate["model_id"]) for candidate in registry["candidates"]]
    if (
        rolling["candidateIds"] != candidate_order
        or [candidate["modelId"] for candidate in comparison["candidates"]] != candidate_order
        or [candidate["modelId"] for candidate in summary["candidates"]] != candidate_order
    ):
        raise RuntimePortfolioBenchmarkError("Assessment candidate order mismatch.")
    if rolling["target"] != policy["target"] or rolling["horizonWeeks"] != policy["horizonWeeks"]:
        raise RuntimePortfolioBenchmarkError("Assessment target or horizon mismatch.")

    artifact_hashes = commit["artifactHashes"]
    actual_hashes = {
        name: _sha256_file(source / "artifacts" / name) for name in SOURCE_ARTIFACTS
    }
    if artifact_hashes != actual_hashes:
        raise RuntimePortfolioBenchmarkError("Assessment artifact hash verification failed.")
    if (
        comparison["rollingValidationSha256"] != actual_hashes["rolling_validation.json"]
        or summary["evidenceHashes"]["rollingValidationSha256"] != actual_hashes["rolling_validation.json"]
        or summary["evidenceHashes"]["candidateComparisonSha256"] != actual_hashes["candidate_model_comparison.json"]
        or summary["evidenceHashes"]["recommendationSha256"] != actual_hashes["recommendation.json"]
    ):
        raise RuntimePortfolioBenchmarkError("Assessment evidence hash chain mismatch.")
    if fold_plan_sha256(rolling["folds"]) != rolling["foldPlanSha256"] or commit["foldPlanSha256"] != rolling["foldPlanSha256"]:
        raise RuntimePortfolioBenchmarkError("Assessment fold-plan identity mismatch.")

    fold_ids: set[str] = set()
    for fold in rolling["folds"]:
        fold_id = str(fold["foldId"])
        if fold_id in fold_ids:
            raise RuntimePortfolioBenchmarkError("Assessment contains a duplicate fold.")
        fold_ids.add(fold_id)
        predictions = fold["predictions"]
        ids = [str(record["modelId"]) for record in predictions]
        if ids != candidate_order or len(ids) != len(set(ids)):
            raise RuntimePortfolioBenchmarkError("Assessment contains duplicate or misordered predictions.")
    if len(rolling["folds"]) != rolling["plannedFoldCount"]:
        raise RuntimePortfolioBenchmarkError("Assessment publication is partial.")
    if (
        manifest["datasetId"] != rolling["datasetId"]
        or validation["datasetId"] != rolling["datasetId"]
        or manifest["validationRecordSha256"] != commit["validationRecordSha256"]
        or _sha256_file(source / "metadata/validation.json") != commit["validationRecordSha256"]
    ):
        raise RuntimePortfolioBenchmarkError("Assessment dataset or validation identity mismatch.")

    source_types = policy_snapshot.get("source_scope", {})
    if accepted_assessment["policyVersion"] == "p2-v3" and (
        source_types.get("cases", {}).get("allowed_source_types") != ["synthetic_benchmark"]
        or source_types.get("climate", {}).get("allowed_source_types") != ["synthetic_benchmark"]
    ):
        raise RuntimePortfolioBenchmarkError("Assessment evidence scope cannot be established.")
    commit_bytes = (source / "metadata/commit.json").read_bytes()
    return {
        "assessmentPath": str(source),
        "assessmentCommitBytes": commit_bytes,
        "assessmentCommitSha256": _sha256_bytes(commit_bytes),
        "commit": commit,
        "rolling": rolling,
        "comparison": comparison,
        "summary": summary,
        "assessment": assessment,
        "validation": validation,
        "manifest": manifest,
        "artifactHashes": actual_hashes,
        "candidateOrder": candidate_order,
        "registryVersion": accepted_registry["version"],
        "registrySha256": registry_sha,
        "assessmentPolicy": {
            "policyId": accepted_assessment["policyId"],
            "policyVersion": accepted_assessment["policyVersion"],
            "policySha256": accepted_assessment["policySha256"],
        },
        "policy": policy,
        "policyRawSha256": policy_raw_sha,
    }


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    payload = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _make_immutable(root: Path) -> None:
    if os.name == "nt":
        for path in root.rglob("*"):
            if path.is_file():
                path.chmod(stat.S_IREAD)
        return
    for path in sorted(root.rglob("*"), reverse=True):
        path.chmod(0o555 if path.is_dir() else 0o444)
    root.chmod(0o555)


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def publish_benchmark(
    *,
    assessment_dir: str | Path,
    output_root: str | Path,
    evidence_scope: str,
    benchmark_id: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    source = verify_source_assessment(assessment_dir)
    policy = source["policy"]
    if evidence_scope not in policy["evidenceScopes"]:
        raise RuntimePortfolioBenchmarkError("Unsupported benchmark evidence scope.")
    if evidence_scope != "synthetic_qualification":
        raise RuntimePortfolioBenchmarkError("The accepted p2-v3 source is synthetic qualification evidence.")
    output = Path(output_root)
    if not output.is_absolute():
        raise RuntimePortfolioBenchmarkError("Benchmark output root must be an explicit absolute path.")
    output = output.resolve()
    _reject_temporary(output, "Benchmark output")
    identifier = benchmark_id or str(uuid.uuid4())
    if not UUID4.fullmatch(identifier):
        raise RuntimePortfolioBenchmarkError("Benchmark ID must be a UUIDv4.")
    created = generated_at or _timestamp()
    committed = output / identifier
    staging_collection = output.parent / "portfolio-benchmark-staging"
    staging = staging_collection / identifier
    if committed.exists() or staging.exists():
        raise RuntimePortfolioBenchmarkError("Benchmark ID already exists.")

    policy_identity = {
        "policyId": policy["policyId"],
        "policyVersion": policy["policyVersion"],
        "policySha256": policy["policySha256"],
        "policyRawSha256": source["policyRawSha256"],
    }
    benchmark = build_benchmark(
        benchmark_id=identifier,
        generated_at=created,
        evidence_scope=evidence_scope,
        policy_identity=policy_identity,
        source=source,
        candidate_order=source["candidateOrder"],
        candidate_registry_version=source["registryVersion"],
        candidate_registry_sha256=source["registrySha256"],
        assessment_policy_identity=source["assessmentPolicy"],
        tolerance=float(policy["tieTolerance"]),
    )
    _validate_schema(benchmark, ARTIFACT_SCHEMA_PATH, "portfolio benchmark")
    try:
        (staging / "artifacts").mkdir(parents=True)
        (staging / "metadata").mkdir()
        _atomic_json(staging / "artifacts/portfolio_benchmark.json", benchmark)
        snapshot = staging / "artifacts/source_assessment_commit.json"
        with snapshot.open("xb") as handle:
            handle.write(source["assessmentCommitBytes"])
            handle.flush()
            os.fsync(handle.fileno())
        commit = {
            "schemaVersion": "1.0",
            "benchmarkId": identifier,
            "generatedAt": created,
            "evidenceScope": evidence_scope,
            "operationalDhakaValidation": False,
            "benchmarkArtifactPath": "artifacts/portfolio_benchmark.json",
            "benchmarkArtifactSha256": _sha256_file(staging / "artifacts/portfolio_benchmark.json"),
            "sourceAssessmentCommitSnapshotPath": "artifacts/source_assessment_commit.json",
            "sourceAssessmentCommitSnapshotSha256": _sha256_file(snapshot),
            "sourceAssessmentId": source["rolling"]["assessmentId"],
            "sourceAssessmentPath": source["assessmentPath"],
            "sourceAssessmentCommitSha256": source["assessmentCommitSha256"],
            "sourceArtifactHashes": source["artifactHashes"],
            "benchmarkPolicy": policy_identity,
            "candidateRegistryVersion": source["registryVersion"],
            "candidateRegistrySha256": source["registrySha256"],
            "assessmentPolicy": source["assessmentPolicy"],
            "foldPlanSha256": source["rolling"]["foldPlanSha256"],
            "commonFoldSetSha256": benchmark["primaryCohort"]["commonFoldSetSha256"],
            "status": "committed",
            "automaticModelRemovalAllowed": False,
        }
        _validate_schema(commit, COMMIT_SCHEMA_PATH, "portfolio benchmark commit")
        _atomic_json(staging / "metadata/commit.json", commit)
        output.mkdir(parents=True, exist_ok=True)
        staging_collection.mkdir(parents=True, exist_ok=True)
        os.replace(staging, committed)
        _fsync_directory(output)
        _make_immutable(committed)
        verified = verify_benchmark_dir(committed)
        return {"benchmarkId": identifier, "benchmarkPath": str(committed), "commit": verified["commit"]}
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def verify_benchmark_dir(benchmark_dir: str | Path) -> dict[str, Any]:
    root = Path(benchmark_dir)
    if not root.is_absolute():
        raise RuntimePortfolioBenchmarkError("Benchmark directory must be an explicit absolute path.")
    root = root.resolve()
    _reject_temporary(root, "Benchmark package")
    if not UUID4.fullmatch(root.name) or root.parent.name != "portfolio-benchmarks":
        raise RuntimePortfolioBenchmarkError("Benchmark package path is invalid.")
    expected = {
        "artifacts/portfolio_benchmark.json",
        "artifacts/source_assessment_commit.json",
        "metadata/commit.json",
    }
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }
    if actual != expected:
        raise RuntimePortfolioBenchmarkError("Benchmark package is partial or has unexpected files.")
    benchmark = _json(root / "artifacts/portfolio_benchmark.json")
    commit = _json(root / "metadata/commit.json")
    _validate_schema(benchmark, ARTIFACT_SCHEMA_PATH, "portfolio benchmark")
    _validate_schema(commit, COMMIT_SCHEMA_PATH, "portfolio benchmark commit")
    if benchmark["benchmarkId"] != root.name or commit["benchmarkId"] != root.name:
        raise RuntimePortfolioBenchmarkError("Benchmark ID reconciliation failed.")
    if _sha256_file(root / commit["benchmarkArtifactPath"]) != commit["benchmarkArtifactSha256"]:
        raise RuntimePortfolioBenchmarkError("Benchmark artifact hash mismatch.")
    snapshot_path = root / commit["sourceAssessmentCommitSnapshotPath"]
    if _sha256_file(snapshot_path) != commit["sourceAssessmentCommitSnapshotSha256"]:
        raise RuntimePortfolioBenchmarkError("Source assessment commit snapshot hash mismatch.")
    source = verify_source_assessment(Path(commit["sourceAssessmentPath"]))
    if (
        snapshot_path.read_bytes() != source["assessmentCommitBytes"]
        or commit["sourceAssessmentCommitSha256"] != source["assessmentCommitSha256"]
        or commit["sourceArtifactHashes"] != source["artifactHashes"]
        or commit["benchmarkPolicy"]["policySha256"] != source["policy"]["policySha256"]
        or commit["benchmarkPolicy"]["policyRawSha256"] != source["policyRawSha256"]
        or commit["commonFoldSetSha256"] != benchmark["primaryCohort"]["commonFoldSetSha256"]
    ):
        raise RuntimePortfolioBenchmarkError("Benchmark source authority reconciliation failed.")
    return {"benchmark": benchmark, "commit": commit, "source": source}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assessment-dir", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--evidence-scope", required=True)
    parser.add_argument("--benchmark-id")
    parser.add_argument("--verify-benchmark-dir")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.verify_benchmark_dir:
            result = verify_benchmark_dir(Path(args.verify_benchmark_dir).resolve())
            output = {"ok": True, "benchmarkId": result["commit"]["benchmarkId"], "verified": True}
        else:
            result = publish_benchmark(
                assessment_dir=Path(args.assessment_dir).resolve(),
                output_root=Path(args.output_root).resolve(),
                evidence_scope=args.evidence_scope,
                benchmark_id=args.benchmark_id,
            )
            output = {"ok": True, **result}
        print(json.dumps(output, separators=(",", ":")))
        return 0
    except (RuntimePortfolioBenchmarkError, PortfolioBenchmarkEvidenceError, OSError) as exc:
        print(json.dumps({"ok": False, "code": "portfolio_benchmark_failed", "message": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
