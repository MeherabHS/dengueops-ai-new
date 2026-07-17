"""Independent read-only verification of monitoring inputs for degradation evidence."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from model_degradation_metrics import canonical_sha256, ordered_outcome_set_hash
from runtime_commit import sha256_file
from runtime_context import ROOT, require_absolute_directory
from runtime_forecast_outcome_source import ForecastSourceError, verify_forecast_source

MONITORING_SHA = "c73461e211e334733309232806fa2d41c2e5fdce7aa5e096d065e13e7525eaab"


class ModelDegradationSourceError(RuntimeError):
    pass


def _json(path: Path) -> dict[str, Any]:
    try: value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc: raise ModelDegradationSourceError(f"Invalid JSON evidence: {path.name}.") from exc
    if not isinstance(value, dict): raise ModelDegradationSourceError(f"{path.name} must be an object.")
    return value


def _schema(value: Mapping[str, Any], name: str) -> None:
    schema = _json(ROOT / "config" / name)
    errors = sorted(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value), key=lambda error:list(error.path))
    if errors: raise ModelDegradationSourceError(f"Evidence failed {name}: {errors[0].message}")


def _assessment_reference(runtime_root: Path, outcome: Mapping[str, Any]) -> dict[str, Any]:
    evidence = outcome.get("sourceEvidence")
    if not isinstance(evidence, Mapping): raise ModelDegradationSourceError("Approved outcome lacks assessment evidence.")
    assessment_id = str(evidence.get("assessmentId", "")); root = runtime_root / "assessments" / assessment_id
    commit_path = root / "metadata/commit.json"; comparison_path = root / "artifacts/candidate_model_comparison.json"; rolling_path = root / "artifacts/rolling_validation.json"; summary_path = root / "artifacts/assessment_summary.json"
    for path in (commit_path, comparison_path, rolling_path, summary_path):
        if not path.is_file(): raise ModelDegradationSourceError("Assessment reference evidence is missing.")
    commit, comparison, rolling, summary = _json(commit_path), _json(comparison_path), _json(rolling_path), _json(summary_path)
    _schema(commit,"runtime_assessment_commit.schema.json"); _schema(comparison,"runtime_candidate_comparison.schema.json"); _schema(rolling,"runtime_rolling_validation.schema.json"); _schema(summary,"runtime_assessment_summary.schema.json")
    hashes = commit.get("artifactHashes", {})
    expected = {"candidate_model_comparison.json":comparison_path,"rolling_validation.json":rolling_path,"assessment_summary.json":summary_path}
    if any(hashes.get(name) != sha256_file(path) for name, path in expected.items()): raise ModelDegradationSourceError("Assessment artifact hash mismatch.")
    commit_sha, comparison_sha = sha256_file(commit_path), sha256_file(comparison_path)
    if commit_sha != evidence.get("assessmentCommitSha256") or comparison.get("rollingValidationSha256") != sha256_file(rolling_path): raise ModelDegradationSourceError("Assessment reference binding mismatch.")
    model_id, family, parameter = outcome.get("modelId"), outcome.get("modelFamily"), outcome.get("modelParametersSha256")
    candidates = [value for value in comparison.get("candidates", []) if value.get("modelId") == model_id and value.get("parametersSha256") == parameter]
    if len(candidates) != 1: raise ModelDegradationSourceError("Exact selected assessment candidate was not found.")
    candidate = candidates[0]; planned = comparison.get("plannedFoldCount"); folds = rolling.get("folds", [])
    if outcome.get("sourceFamily") == "approved_forecast_p1":
        if planned != 68 or len(folds) != 68: raise ModelDegradationSourceError("Phase 1 assessment fold evidence changed.")
    elif not isinstance(planned, int) or not 52 <= planned <= 68 or len(folds) != planned:
        raise ModelDegradationSourceError("Phase 2 assessment fold evidence is invalid.")
    selected: list[tuple[Mapping[str, Any], float]] = []
    for fold in folds:
        matches = [value for value in fold.get("predictions", []) if value.get("modelId") == model_id]
        if len(matches) != 1: raise ModelDegradationSourceError("Selected candidate fold evidence is incomplete.")
        selected.append((matches[0], float(fold.get("actualTarget"))))
    successful = [value for value in selected if value[0].get("foldStatus") in {"success","warning"}]; failed = len(selected)-len(successful)
    if len(successful) != planned or failed != 0 or candidate.get("successfulFolds") != planned or candidate.get("failedFolds") != 0:
        raise ModelDegradationSourceError("Selected candidate did not complete the committed fold plan.")
    absolute: list[float] = []; squared: list[float] = []; clipping = 0
    for value, actual in successful:
        prediction = float(value.get("publishedPrediction"))
        if not math.isfinite(prediction) or not math.isfinite(actual): raise ModelDegradationSourceError("Assessment prediction is nonfinite.")
        error = prediction-actual; absolute.append(abs(error)); squared.append(error*error); clipping += bool(value.get("clippingApplied"))
    mae = math.fsum(absolute)/planned; rmse = math.sqrt(math.fsum(squared)/planned); metrics = candidate.get("metrics", {})
    if not math.isclose(mae,float(metrics.get("mae")),rel_tol=1e-12,abs_tol=1e-12) or not math.isclose(rmse,float(metrics.get("rmse")),rel_tol=1e-12,abs_tol=1e-12) or clipping != metrics.get("clippingCount"):
        raise ModelDegradationSourceError("Assessment reference metrics do not reconcile.")
    selected_period = comparison.get("selectedEvaluationPeriod") or {"start":folds[0]["targetPeriod"],"end":folds[-1]["targetPeriod"]}
    policy = evidence.get("assessmentPolicy")
    if not isinstance(policy, Mapping) or policy.get("policySha256") != commit.get("assessmentPolicySha256"): raise ModelDegradationSourceError("Assessment policy binding mismatch.")
    return {"assessmentId":assessment_id,"assessmentCommitSha256":commit_sha,"candidateComparisonSha256":comparison_sha,"assessmentPolicy":dict(policy),"modelId":model_id,"modelFamily":family,"parameterSha256":parameter,"foldPlanSha256":comparison.get("foldPlanSha256"),"selectedEvaluationPeriod":selected_period,"plannedFoldCount":planned,"successfulFolds":planned,"failedFolds":0,"assessmentMAE":mae,"assessmentRMSE":rmse,"clippingCount":clipping}


def verify_model_degradation_source(runtime_root: str | Path, expected_latest_sha256: str | None = None, expected_summary_sha256: str | None = None, expected_outcome_set_sha256: str | None = None) -> dict[str, Any]:
    root = require_absolute_directory(runtime_root,"runtime root"); latest_path = root / "deployments/dhaka_south/monitoring/latest.json"
    if not latest_path.is_file(): raise ModelDegradationSourceError("A p2 monitoring latest pointer is required.")
    latest = _json(latest_path); _schema(latest,"runtime_monitoring_latest.schema.json"); latest_sha = sha256_file(latest_path)
    if latest.get("schemaVersion") != "2.0" or (latest.get("policyId"),latest.get("policyVersion"),latest.get("policySha256")) != ("RUNTIME.FORECAST_OUTCOME.MONITORING","p2-v1",MONITORING_SHA): raise ModelDegradationSourceError("Standalone p1 or unknown monitoring input is not accepted.")
    if expected_latest_sha256 not in (None, latest_sha): raise ModelDegradationSourceError("Monitoring latest pointer hash mismatch.")
    summary_path = root / str(latest.get("monitoringSummaryPath")); summary = _json(summary_path); _schema(summary,"runtime_monitoring_summary.schema.json"); summary_sha = sha256_file(summary_path)
    if summary.get("schemaVersion") != "2.0" or summary.get("policySha256") != MONITORING_SHA or latest.get("monitoringSummarySha256") != summary_sha: raise ModelDegradationSourceError("Monitoring summary identity mismatch.")
    if expected_summary_sha256 not in (None, summary_sha) or expected_outcome_set_sha256 not in (None, summary.get("outcomeSetSha256")): raise ModelDegradationSourceError("Monitoring summary input hash mismatch.")
    records: list[dict[str, Any]] = []; included_commits: list[dict[str, str]] = []; references: dict[str, dict[str, Any]] = {}
    for included in summary.get("includedOutcomes", []):
        outcome_id = str(included.get("outcomeId", "")); outcome_root = root / "forecast-outcomes" / outcome_id; commit_path = outcome_root / "metadata/commit.json"; evaluation_path = outcome_root / "artifacts/outcome_evaluation.json"
        commit, outcome = _json(commit_path), _json(evaluation_path); _schema(commit,"runtime_forecast_outcome_commit.schema.json"); _schema(outcome,"runtime_forecast_outcome.schema.json")
        commit_sha, evidence_sha = sha256_file(commit_path), sha256_file(evaluation_path)
        if commit.get("artifactHashes",{}).get("outcome_evaluation.json") != evidence_sha or included.get("outcomeEvidenceSha256") != evidence_sha or commit.get("outcomeId") != outcome_id or outcome.get("outcomeId") != outcome_id: raise ModelDegradationSourceError("Included outcome hash mismatch.")
        for name, digest in commit.get("artifactHashes", {}).items():
            if sha256_file(outcome_root/"artifacts"/name) != digest: raise ModelDegradationSourceError("Outcome artifact hash mismatch.")
        source_run = str(outcome.get("sourceForecastRunId", outcome.get("forecastRunId", ""))); source_sha = str(outcome.get("sourceForecastCommitSha256", outcome.get("forecastCommitSha256", "")))
        try: bundle = verify_forecast_source(root,source_run,source_sha,{"quick_forecast_p1","approved_forecast_p1","approved_forecast_p2"})
        except ForecastSourceError as exc: raise ModelDegradationSourceError(str(exc)) from exc
        source_family = str(outcome.get("sourceFamily", "quick_forecast_p1" if outcome.get("schemaVersion") == "1.0" else ""))
        if bundle["sourceFamily"] != source_family or commit.get("forecastCommitSha256") != source_sha: raise ModelDegradationSourceError("Outcome source-family binding mismatch.")
        record = dict(outcome); record["sourceFamily"] = source_family; record["outcomeEvidenceSha256"] = evidence_sha; record["outcomeCommitSha256"] = commit_sha; records.append(record)
        included_commits.append({"outcomeId":outcome_id,"outcomeCommitSha256":commit_sha,"outcomeEvidenceSha256":evidence_sha})
        if source_family != "quick_forecast_p1":
            reference = _assessment_reference(root,record); references[reference["assessmentId"]] = reference
    if len(records) != summary.get("evaluatedForecastCount") or ordered_outcome_set_hash(records) != summary.get("outcomeSetSha256"):
        raise ModelDegradationSourceError("Monitoring included-outcome set does not reconcile.")
    return {"latest":latest,"latestSha256":latest_sha,"latestPath":"deployments/dhaka_south/monitoring/latest.json","summary":summary,"summarySha256":summary_sha,"summaryPath":str(latest["monitoringSummaryPath"]),"outcomes":records,"includedOutcomes":sorted(included_commits,key=lambda value:value["outcomeId"]),"assessmentReferences":references}
