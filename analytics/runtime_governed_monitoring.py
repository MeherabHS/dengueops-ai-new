"""Publish immutable B9.D evidence for the exact current assignment and forecast."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import shutil
import statistics
import uuid
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from governed_monitoring import (
    calculate_confidence,
    canonical_sha256,
    evaluate_feature_drift,
    evaluate_performance_drift,
    evaluate_ranking_instability,
    load_monitoring_policy,
    reassessment_recommendation,
)
from runtime_active_model import resolve_active_model_p2_v2
from runtime_context import ROOT, require_absolute_directory
from runtime_model_degradation_source import ModelDegradationSourceError, verify_model_degradation_source


class RuntimeGovernedMonitoringError(ValueError):
    pass


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_file(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _json_bytes(path: Path) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink() or not path.is_file():
        raise RuntimeGovernedMonitoringError("Monitoring authority evidence is missing or unsafe.")
    try:
        raw = path.read_bytes(); value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeGovernedMonitoringError("Monitoring authority evidence is invalid JSON.") from exc
    if not isinstance(value, dict):
        raise RuntimeGovernedMonitoringError("Monitoring authority evidence must be an object.")
    return value, raw


def _validate(value: Mapping[str, Any], schema_name: str) -> None:
    schema = json.loads((ROOT / "config" / schema_name).read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value), key=lambda item: list(item.path))
    if errors:
        raise RuntimeGovernedMonitoringError(f"Monitoring evidence failed {schema_name}: {errors[0].message}")


def _contained(root: Path, candidate: Path) -> Path:
    root = root.resolve(); resolved = candidate.resolve(strict=False)
    if resolved != root and root not in resolved.parents:
        raise RuntimeGovernedMonitoringError("Monitoring path escaped the runtime root.")
    return resolved


def _rows(path: Path, features: list[str]) -> list[dict[str, float]]:
    if path.is_symlink() or not path.is_file():
        raise RuntimeGovernedMonitoringError("A governed feature matrix is missing or unsafe.")
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or any(feature not in reader.fieldnames for feature in features):
            raise RuntimeGovernedMonitoringError("The governed feature matrix is incompatible.")
        rows = []
        for record in reader:
            row = {feature: float(record[feature]) for feature in features}
            if any(not math.isfinite(value) for value in row.values()):
                raise RuntimeGovernedMonitoringError("The governed feature matrix contains nonfinite values.")
            rows.append(row)
    return rows


def _candidate_order(comparison: Mapping[str, Any]) -> list[str]:
    eligible = set(comparison.get("selectionEligibleCandidateIds", []))
    candidates = [item for item in comparison.get("candidates", []) if isinstance(item, Mapping) and item.get("modelId") in eligible]
    def key(item: Mapping[str, Any]) -> tuple[Any, ...]:
        metrics = item.get("metrics", {})
        values = []
        for name in ("mae", "rmse", "wape", "medianAbsoluteError", "maximumAbsoluteError"):
            value = metrics.get(name) if isinstance(metrics, Mapping) else None
            values.append(float(value) if isinstance(value, (int, float)) and math.isfinite(float(value)) else math.inf)
        return (*values, int(item.get("selectionComplexityRank", 10**9)), str(item.get("modelId", "")))
    return [str(item["modelId"]) for item in sorted(candidates, key=key)]


def _verified_assessment(root: Path, assessment_id: str, expected_commit_sha: str | None = None) -> dict[str, Any]:
    assessment_root = _contained(root, root / "assessments" / assessment_id)
    commit, commit_bytes = _json_bytes(assessment_root / "metadata/commit.json")
    _validate(commit, "runtime_assessment_commit.schema.json")
    if expected_commit_sha not in (None, _sha_bytes(commit_bytes)) or commit.get("assessmentId") != assessment_id or commit.get("status") != "committed":
        raise RuntimeGovernedMonitoringError("Source assessment commit identity mismatch.")
    artifacts = commit.get("artifactHashes", {})
    required = {"model_features.csv", "candidate_model_comparison.json", "rolling_validation.json"}
    if not required.issubset(artifacts):
        raise RuntimeGovernedMonitoringError("Source assessment evidence is incomplete.")
    for name in required:
        if _sha_file(assessment_root / "artifacts" / name) != artifacts[name]:
            raise RuntimeGovernedMonitoringError("Source assessment artifact hash mismatch.")
    comparison, _ = _json_bytes(assessment_root / "artifacts/candidate_model_comparison.json")
    rolling, _ = _json_bytes(assessment_root / "artifacts/rolling_validation.json")
    _validate(comparison, "runtime_candidate_comparison.schema.json")
    _validate(rolling, "runtime_rolling_validation.schema.json")
    return {"root": assessment_root, "commit": commit, "commitSha256": _sha_bytes(commit_bytes),
        "featuresSha256": artifacts["model_features.csv"], "comparison": comparison, "rolling": rolling}


def _latest_reassessment(root: Path, source: Mapping[str, Any]) -> dict[str, Any] | None:
    assessments = root / "assessments"
    if not assessments.is_dir() or assessments.is_symlink():
        return None
    candidates = []
    for path in assessments.iterdir():
        if not path.is_dir() or path.is_symlink() or path.name == source["commit"]["assessmentId"]:
            continue
        try:
            verified = _verified_assessment(root, path.name)
        except RuntimeGovernedMonitoringError:
            continue
        if str(verified["commit"].get("committedAt", "")) > str(source["commit"].get("committedAt", "")):
            candidates.append(verified)
    return max(candidates, key=lambda item: (str(item["commit"].get("committedAt", "")), item["commitSha256"])) if candidates else None


def _performance_evidence(root: Path, assignment: Mapping[str, Any], baseline: Mapping[str, float], policy: Mapping[str, Any]) -> tuple[dict[str, Any], str | None]:
    latest_path = root / "deployments/dhaka_south/monitoring/latest.json"
    if not latest_path.is_file():
        return evaluate_performance_drift([], baseline, policy), None
    latest, latest_bytes = _json_bytes(latest_path)
    version = str(latest.get("policyVersion", ""))
    try:
        source = verify_model_degradation_source(root, monitoring_policy_version=version)
    except ModelDegradationSourceError:
        return {"status": "identity_mismatch", "matureOutcomeCount": 0, "metrics": None,
            "referenceMetrics": dict(baseline), "ratios": None}, _sha_bytes(latest_bytes)
    pairs = []
    for outcome in source["outcomes"]:
        provenance = outcome.get("sourceEvidence", {}).get("assignmentProvenance", {})
        if provenance.get("assignmentId") != assignment["assignmentId"]:
            continue
        identity_valid = (
            provenance.get("assignmentCommitSha256") == assignment["assignmentCommitSha256"]
            and outcome.get("modelId") == assignment["modelId"]
            and outcome.get("featureOrderSha256") == assignment["featureOrderSha256"]
            and outcome.get("forecastHorizonWeeks") == int(policy["performance_drift"]["horizon_weeks"])
        )
        pairs.append({"mature": True, "identityValid": identity_valid,
            "pointForecast": outcome.get("forecastRaw"), "actualOutcome": outcome.get("observedRaw"),
            "forecastOrigin": outcome.get("forecastOriginPeriod"), "targetPeriod": outcome.get("forecastTargetPeriod")})
    return evaluate_performance_drift(pairs, baseline, policy), _sha_bytes(latest_bytes)


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False, allow_nan=False); handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
    os.replace(temporary, path)


def _make_immutable(root: Path) -> None:
    if os.name == "nt": return
    for item in sorted(root.rglob("*"), reverse=True): item.chmod(0o555 if item.is_dir() else 0o444)
    root.chmod(0o555)


def _verify_existing(path: Path, authority_sha: str, policy_sha: str) -> dict[str, Any] | None:
    if not path.exists(): return None
    evidence, evidence_bytes = _json_bytes(path / "artifacts/governed_monitoring.json")
    commit, commit_bytes = _json_bytes(path / "metadata/governed_monitoring_commit.json")
    _validate(evidence, "runtime_governed_monitoring_evidence.schema.json"); _validate(commit, "runtime_governed_monitoring_commit.schema.json")
    if evidence.get("authority", {}).get("authoritySnapshotSha256") != authority_sha or evidence.get("policy", {}).get("policySha256") != policy_sha or commit.get("evidenceSha256") != _sha_bytes(evidence_bytes):
        raise RuntimeGovernedMonitoringError("Existing monitoring evidence does not reconcile.")
    return {"evidence": evidence, "evidenceSha256": _sha_bytes(evidence_bytes), "commit": commit, "commitSha256": _sha_bytes(commit_bytes)}


def publish_current_monitoring(runtime_root: str | Path, expected_run_id: str | None = None) -> dict[str, Any]:
    root = require_absolute_directory(runtime_root, "runtime root")
    policy, policy_sha = load_monitoring_policy()
    latest_path = root / "deployments/dhaka_south/latest.json"
    latest, latest_bytes = _json_bytes(latest_path)
    if latest.get("workflowMode") != "quick_forecast" or expected_run_id not in (None, latest.get("runId")):
        raise RuntimeGovernedMonitoringError("Monitoring requires the exact current operational forecast.")
    authority = resolve_active_model_p2_v2(repository_root=ROOT, runtime_root=root, deployment_id="dhaka_south")
    assignment_pointer_path = root / "deployments/dhaka_south/model-assignment/latest.json"
    assignment_pointer_bytes = assignment_pointer_path.read_bytes()
    if _sha_bytes(assignment_pointer_bytes) != authority["authoritySnapshotSha256"]:
        raise RuntimeGovernedMonitoringError("Current assignment pointer changed during monitoring.")
    assignment_root = _contained(root, root / "model-assignments" / authority["assignmentId"])
    assignment_record, assignment_record_bytes = _json_bytes(assignment_root / "artifacts/assignment_record.json")
    assignment_commit, assignment_commit_bytes = _json_bytes(assignment_root / "metadata/commit.json")
    _validate(assignment_record, "runtime_model_assignment.schema.json"); _validate(assignment_commit, "runtime_model_assignment_commit.schema.json")
    if _sha_bytes(assignment_commit_bytes) != authority["assignmentCommitSha256"] or assignment_commit.get("assignmentRecordSha256") != _sha_bytes(assignment_record_bytes):
        raise RuntimeGovernedMonitoringError("Current assignment commit does not reconcile.")
    source_assessment_id = assignment_record.get("sourceAssessmentId")
    if not isinstance(source_assessment_id, str):
        raise RuntimeGovernedMonitoringError("Current assignment has no exact source assessment.")
    source = _verified_assessment(root, source_assessment_id)

    run_id = str(latest["runId"]); run_root = _contained(root, root / "runs" / run_id)
    forecast_commit, forecast_commit_bytes = _json_bytes(run_root / "metadata/commit.json")
    _validate(forecast_commit, "runtime_commit.schema.json")
    if _sha_bytes(forecast_commit_bytes) != latest.get("commitRecordSha256") or forecast_commit.get("datasetId") != latest.get("datasetId"):
        raise RuntimeGovernedMonitoringError("Current forecast commit does not reconcile.")
    artifact_hashes = forecast_commit.get("artifactHashes", {})
    for name in ("model_features.csv", "input_manifest.json", "forecast_output.json", "forecast_uncertainty.json", "forecast_calibration.json"):
        if name not in artifact_hashes or _sha_file(run_root / "artifacts" / name) != artifact_hashes[name]:
            raise RuntimeGovernedMonitoringError("Current forecast artifact hash mismatch.")
    run_record, _ = _json_bytes(run_root / "metadata/run.json")
    if run_record.get("assignmentId") != authority["assignmentId"] or run_record.get("assignmentCommitSha256") != authority["assignmentCommitSha256"] or run_record.get("activeModelId") != authority["modelId"]:
        raise RuntimeGovernedMonitoringError("Current forecast is not bound to the current assignment.")
    manifest, _ = _json_bytes(run_root / "artifacts/input_manifest.json")
    validation, validation_bytes = _json_bytes(run_root / "metadata/validation.json")
    if manifest.get("validationRecordSha256") != _sha_bytes(validation_bytes) or validation.get("status") != "ready":
        raise RuntimeGovernedMonitoringError("Current validation evidence is not authoritative.")
    errors = [item for item in validation.get("issues", []) if isinstance(item, Mapping) and item.get("severity") == "error"]
    data_quality = {"verified": not errors, "score": 1.0 if not errors else 0.0,
        "schemaValid": True, "temporalContinuityValid": not errors, "canonicalHashIntegrity": True,
        "featureAvailabilityValid": validation.get("datasetIdentity", {}).get("featureOrderSha256") == authority["featureOrderSha256"],
        "errorCount": len(errors), "warningCount": sum(item.get("severity") == "warning" for item in validation.get("issues", []) if isinstance(item, Mapping))}
    data_quality["verified"] = bool(data_quality["verified"] and data_quality["featureAvailabilityValid"])

    features = list(policy["feature_authority"]["features"])
    feature_compatible = (authority["featureOrderSha256"] == policy["feature_authority"]["feature_order_sha256"]
        and assignment_record.get("featureOrderSha256") == authority["featureOrderSha256"]
        and source["comparison"].get("candidateRegistrySha256") == authority["candidateRegistrySha256"])
    feature_drift = evaluate_feature_drift(
        _rows(source["root"] / "artifacts/model_features.csv", features),
        _rows(run_root / "artifacts/model_features.csv", features), features, policy,
        feature_authority_compatible=feature_compatible,
    )
    source_candidate = next((item for item in source["comparison"].get("candidates", []) if item.get("modelId") == authority["modelId"]), None)
    if not isinstance(source_candidate, Mapping):
        raise RuntimeGovernedMonitoringError("Assigned candidate is absent from its source assessment.")
    source_metrics = source_candidate.get("metrics", {})
    baseline = {name: float(source_metrics[name]) for name in ("mae", "rmse", "wape") if source_metrics.get(name) is not None}
    performance, monitoring_latest_sha = _performance_evidence(root, authority, baseline, policy)
    latest_assessment = _latest_reassessment(root, source)
    ranking = evaluate_ranking_instability(
        source["comparison"].get("technicalWinnerModelId"), None if latest_assessment is None else latest_assessment["comparison"].get("technicalWinnerModelId"),
        authority["modelId"], _candidate_order(source["comparison"]), None if latest_assessment is None else _candidate_order(latest_assessment["comparison"]),
    )
    if latest_assessment is not None:
        ranking["latestAssessmentId"] = latest_assessment["commit"]["assessmentId"]
        ranking["latestAssessmentCommitSha256"] = latest_assessment["commitSha256"]
    recommendation = reassessment_recommendation(feature_drift, performance, ranking)
    calibration, _ = _json_bytes(run_root / "artifacts/forecast_calibration.json")
    uncertainty, _ = _json_bytes(run_root / "artifacts/forecast_uncertainty.json")
    calibration_status = calibration.get("calibrationStatus")
    residuals = calibration.get("assessmentOofResiduals", [])
    scale = max(float(policy["confidence"]["minimum_reference_outcome_scale"]), statistics.median(float(item["actualTarget"]) for item in residuals)) if residuals else None
    calibration_input = {"status": calibration_status, "reason": calibration.get("uncertaintyReasonCode"),
        "sampleCount": calibration.get("residualCount", 0), "minimumRequired": calibration.get("requiredResidualCount", 1),
        "historicalCoverage": calibration.get("historicalCoverage"), "nominalCoverage": calibration.get("nominalCoverage")}
    interval_input = {"status": uncertainty.get("calibrationStatus"), "lowerRaw": uncertainty.get("lowerRaw"),
        "upperRaw": uncertainty.get("upperRaw"), "referenceOutcomeScale": scale}
    confidence = calculate_confidence(calibration=calibration_input, interval=interval_input, feature_drift=feature_drift,
        data_quality=data_quality, performance=performance, policy=policy)
    confidence["policy"] = {"policyId": policy["policy_id"], "policyVersion": policy["policy_version"], "policySha256": policy_sha}
    confidence["dataQualityEvidence"] = data_quality

    authority_fields = {
        "assignmentId": authority["assignmentId"], "assignmentPointerSha256": authority["authoritySnapshotSha256"],
        "assignmentCommitSha256": authority["assignmentCommitSha256"], "sourceAssessmentId": source_assessment_id,
        "sourceAssessmentCommitSha256": source["commitSha256"], "sourceFeatureMatrixSha256": source["featuresSha256"],
        "forecastRunId": run_id, "forecastLatestSha256": _sha_bytes(latest_bytes), "forecastCommitSha256": _sha_bytes(forecast_commit_bytes),
        "currentFeatureMatrixSha256": artifact_hashes["model_features.csv"], "datasetId": latest["datasetId"],
        "featureOrderSha256": authority["featureOrderSha256"], "calibrationSha256": artifact_hashes["forecast_calibration.json"],
        "uncertaintySha256": artifact_hashes["forecast_uncertainty.json"], "outcomeMonitoringLatestSha256": monitoring_latest_sha,
        "latestReassessmentCommitSha256": None if latest_assessment is None else latest_assessment["commitSha256"],
        "policySha256": policy_sha,
    }
    authority_sha = canonical_sha256(authority_fields)
    authority_public = {key: value for key, value in authority_fields.items() if key != "policySha256"}
    authority_public["authoritySnapshotSha256"] = authority_sha
    monitoring_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"dengueops:b9.d-v1:{authority_sha}"))
    generated = str(forecast_commit["committedAt"])
    evidence = {"schemaVersion": "1.0", "monitoringId": monitoring_id, "deploymentId": "dhaka_south",
        "policy": {"policyId": policy["policy_id"], "policyVersion": policy["policy_version"], "policySha256": policy_sha},
        "authority": authority_public, "featureDrift": feature_drift, "performanceDrift": performance,
        "rankingInstability": ranking, "recommendation": recommendation, "confidence": confidence,
        "invariants": {"confidenceScoreChangesModelSelection": False, "confidenceAffectsForecastPoint": False,
            "confidenceAffectsPredictionInterval": False, "confidenceAffectsPreparedness": False,
            "reassessmentAutoStarted": False, "modelAutoReassigned": False}, "generatedAt": generated}
    _validate(evidence, "runtime_governed_monitoring_evidence.schema.json")

    committed_root = root / "degradation-evidence" / monitoring_id
    existing = _verify_existing(committed_root, authority_sha, policy_sha)
    recovered = existing is not None
    if existing is None:
        staging = root / "degradation-staging" / monitoring_id
        if staging.exists(): shutil.rmtree(staging)
        (staging / "artifacts").mkdir(parents=True); (staging / "metadata").mkdir()
        _atomic_json(staging / "artifacts/governed_monitoring.json", evidence)
        evidence_sha = _sha_file(staging / "artifacts/governed_monitoring.json")
        commit = {"schemaVersion": "1.0", "monitoringId": monitoring_id, "deploymentId": "dhaka_south",
            "policyId": policy["policy_id"], "policyVersion": policy["policy_version"], "policySha256": policy_sha,
            "authoritySnapshotSha256": authority_sha, "evidenceSha256": evidence_sha, "status": "committed", "committedAt": generated,
            "assignmentModified": False, "forecastModified": False, "preparednessModified": False}
        _validate(commit, "runtime_governed_monitoring_commit.schema.json")
        _atomic_json(staging / "metadata/governed_monitoring_commit.json", commit)
        committed_root.parent.mkdir(parents=True, exist_ok=True); os.replace(staging, committed_root); _make_immutable(committed_root)
        existing = {"evidence": evidence, "evidenceSha256": evidence_sha, "commit": commit,
            "commitSha256": _sha_file(committed_root / "metadata/governed_monitoring_commit.json")}
    pointer = {"schemaVersion": "1.0", "deploymentId": "dhaka_south", "monitoringId": monitoring_id,
        "policyId": policy["policy_id"], "policyVersion": policy["policy_version"], "policySha256": policy_sha,
        "authoritySnapshotSha256": authority_sha, "assignmentId": authority["assignmentId"],
        "assignmentPointerSha256": authority["authoritySnapshotSha256"], "forecastRunId": run_id,
        "forecastLatestSha256": _sha_bytes(latest_bytes), "datasetId": latest["datasetId"],
        "evidencePath": f"degradation-evidence/{monitoring_id}/artifacts/governed_monitoring.json",
        "evidenceSha256": existing["evidenceSha256"], "commitPath": f"degradation-evidence/{monitoring_id}/metadata/governed_monitoring_commit.json",
        "commitSha256": existing["commitSha256"], "publishedAt": generated}
    _validate(pointer, "runtime_governed_monitoring_latest.schema.json")
    pointer_root = root / "deployments/dhaka_south/degradation"; pointer_root.mkdir(parents=True, exist_ok=True)
    _atomic_json(pointer_root / "latest_b9-d-v1.json", pointer)
    return {"monitoringId": monitoring_id, "recovered": recovered, "pointer": pointer, "evidence": existing["evidence"]}
