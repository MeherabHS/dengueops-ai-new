"""Strict, side-effect-free verification of governed runtime forecast sources."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from forecast_outcome_metrics import parse_target_period
from runtime_commit import sha256_file
from runtime_context import ROOT

QUICK_POLICY = ("RUNTIME.QUICK_FORECAST.COMPATIBILITY", "p1.4f-v1", "5e6bcb68e5f29a50f8d377892d7786cc1932b3435e8a0b709a363d6c2e42bb9a")
ASSESSMENT_P1 = ("RUNTIME.DATASET_ASSESSMENT.GOVERNANCE", "p1.4d-1-v1", "dbf9d4cc4713bbb9d114b2dab916d0f20b3004ac14b37ca663c3caecefcea0af")
ASSESSMENT_P2 = ("RUNTIME.DATASET_ASSESSMENT.GOVERNANCE", "p2-v1", "04c620ebe42526a74f1fe7054e3281df36bb587b363c027a3a675a86ee70efff")
DECISION_P1 = ("RUNTIME.INTERNAL_ONE_RUN_MODEL_DECISION", "p1.4d-3-e-v1", "8fece340b85951d3bee8b037c4ac79ae82636ee371a934e9371bcb4a633491a4")
DECISION_P2 = ("RUNTIME.INTERNAL_ONE_RUN_MODEL_DECISION", "p2-v1", "aaef2ed2afd3afe03a0aec91889f144a3274cad21aa8cef8ef772bb90cfdcb4a")
REGISTRY_SHA = "2e627f8a368a7e92cebd4ad62139b1050c7614559affd620e9a41738fd6a25d4"
FEATURE_SHA = "aeccbe517da452e1132f08c02599418523fb003280b11ff9cda66cfb3aa55a85"
MODEL_FAMILIES = {"ridge_regression":"Ridge", "poisson_regression":"PoissonRegressor", "random_forest":"RandomForestRegressor", "gradient_boosting":"GradientBoostingRegressor"}


class ForecastSourceError(RuntimeError):
    def __init__(self, message: str, code: str = "forecast_integrity_error"):
        super().__init__(message); self.code = code


def _json(path: Path) -> dict[str, Any]:
    try: value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc: raise ForecastSourceError(f"Invalid source JSON: {path.name}.") from exc
    if not isinstance(value, dict): raise ForecastSourceError(f"{path.name} must be an object.")
    return value


def _schema(value: Mapping[str, Any], name: str) -> None:
    schema = _json(ROOT / "config" / name)
    errors = sorted(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value), key=lambda e:list(e.path))
    if errors: raise ForecastSourceError(f"Source failed {name}: {errors[0].message}")


def _policy_tuple(value: Mapping[str, Any], camel: bool = False) -> tuple[Any, Any, Any]:
    return (value.get("policyId" if camel else "id"), value.get("policyVersion" if camel else "version"), value.get("policySha256" if camel else "sha256"))


def _advance(origin: str) -> str:
    year, week = parse_target_period(origin)
    target = datetime.fromisocalendar(year, week, 1) + timedelta(weeks=2)
    ty, tw, _ = target.isocalendar()
    if tw == 53: raise ForecastSourceError("Unsupported target week.", "target_period_mismatch")
    return f"{ty}-W{tw:02d}"


def _snapshot_and_commit(root: Path, run_id: str, expected_commit: str) -> tuple[Path, dict[str, str], dict[str, Any]]:
    run = root / "runs" / run_id
    if not run.is_dir(): raise ForecastSourceError("Committed forecast not found.", "forecast_not_found")
    snapshot = {str(p.relative_to(run)).replace("\\", "/"): sha256_file(p) for p in sorted(run.rglob("*")) if p.is_file()}
    if snapshot.get("metadata/commit.json") != expected_commit: raise ForecastSourceError("Forecast commit identity mismatch.", "forecast_commit_mismatch")
    commit = _json(run / "metadata/commit.json")
    for name, digest in commit.get("artifactHashes", {}).items():
        if snapshot.get(f"artifacts/{name}") != digest: raise ForecastSourceError("Committed forecast artifact hash mismatch.")
    return run, snapshot, commit


def _quick(root: Path, run: Path, run_id: str, snapshot: dict[str,str], commit: dict[str,Any]) -> dict[str,Any]:
    _schema(commit, "runtime_commit.schema.json")
    if commit.get("workflowMode") != "quick_forecast" or commit.get("schemaVersion") != "1.0": raise ForecastSourceError("Quick source identity mismatch.", "forecast_not_eligible")
    forecast = _json(run/"artifacts/forecast_output.json"); uncertainty = _json(run/"artifacts/forecast_uncertainty.json")
    calibration = _json(run/"artifacts/forecast_calibration.json"); card = _json(run/"artifacts/model_card.json")
    for value, name in ((forecast,"runtime_forecast_output.schema.json"),(uncertainty,"runtime_forecast_uncertainty.schema.json"),(calibration,"runtime_forecast_calibration.schema.json"),(card,"runtime_model_card.schema.json")): _schema(value,name)
    manifest = _json(run/"artifacts/input_manifest.json"); validation_path=run/"metadata/validation.json"; validation=_json(validation_path)
    if sha256_file(validation_path) != manifest.get("validationRecordSha256"): raise ForecastSourceError("Quick validation evidence changed.")
    if _policy_tuple(forecast.get("policy",{})) != QUICK_POLICY: raise ForecastSourceError("Quick policy mismatch.", "forecast_not_eligible")
    expected=(run_id,commit.get("datasetId"),"dhaka_south")
    if (forecast.get("runId"),forecast.get("datasetId"),forecast.get("deploymentId")) != expected: raise ForecastSourceError("Quick identity mismatch.")
    checks=(forecast.get("activeModelId")=="random_forest", forecast.get("modelFamily")=="RandomForestRegressor", forecast.get("parameterHash")=="ac37d2d2947de2f6004d39ecdfa3290c5d65901b796f1eb1fd248ad658e1b1e0", forecast.get("candidateRegistrySha256")==REGISTRY_SHA, forecast.get("trainingDataIdentity",{}).get("featureOrderSha256")==FEATURE_SHA, forecast.get("target")=="target_cases_next_2w", forecast.get("horizonWeeks")==2)
    if not all(checks): raise ForecastSourceError("Quick governance evidence mismatch.", "forecast_not_eligible")
    origin=validation.get("acceptedPeriod",{}).get("end")
    if _advance(origin) != forecast.get("targetPeriod"): raise ForecastSourceError("Quick target period mismatch.", "target_period_mismatch")
    if uncertainty.get("residualSourceArtifactSha256") not in (None,snapshot.get("artifacts/forecast_calibration.json")): raise ForecastSourceError("Quick calibration binding mismatch.")
    return {"sourceFamily":"quick_forecast_p1","commit":commit,"forecast":forecast,"uncertainty":uncertainty,"calibration":calibration,"card":card,"snapshot":snapshot,"origin":origin,"modelId":forecast["activeModelId"],"modelFamily":forecast["modelFamily"],"parameterHash":forecast["parameterHash"],"candidateRegistrySha256":REGISTRY_SHA,"featureOrderSha256":FEATURE_SHA,"sourcePolicy":{"policyId":QUICK_POLICY[0],"policyVersion":QUICK_POLICY[1],"policySha256":QUICK_POLICY[2]},"lifecycle":{}}


def _approved(root: Path, run: Path, run_id: str, snapshot: dict[str,str], commit: dict[str,Any]) -> dict[str,Any]:
    version=commit.get("schemaVersion")
    if version not in {"1.0","2.0"}: raise ForecastSourceError("Approved source schema is unknown.", "forecast_not_eligible")
    _schema(commit,"runtime_approved_forecast_commit.schema.json")
    forecast=_json(run/"artifacts/forecast_output.json"); card=_json(run/"artifacts/model_card.json"); uncertainty=_json(run/"artifacts/forecast_uncertainty.json")
    _schema(forecast,"runtime_approved_forecast_output.schema.json"); _schema(card,"runtime_approved_forecast_model_card.schema.json"); _schema(uncertainty,"runtime_approved_forecast_uncertainty.schema.json")
    if forecast.get("schemaVersion")!=version or card.get("schemaVersion")!=version or commit.get("workflowMode")!="approved_assessment_forecast": raise ForecastSourceError("Approved source is hybrid.","forecast_not_eligible")
    ids=(commit.get("assessmentId"),commit.get("decisionId"),commit.get("authorizationId"))
    if ids != (forecast.get("assessmentId"),forecast.get("decisionId"),forecast.get("authorizationId")) or ids != (card.get("assessment",{}).get("id"),card.get("decision",{}).get("id"),card.get("authorization",{}).get("id")): raise ForecastSourceError("Approved lifecycle identity mismatch.")
    assessment_id,decision_id,authorization_id=ids
    assessment_commit_path=root/"assessments"/assessment_id/"metadata/commit.json";decision_path=root/"decisions"/decision_id/"decision.json";decision_commit_path=root/"decisions"/decision_id/"commit.json";authorization_path=root/"authorizations"/authorization_id/"authorization.json";authorization_commit_path=root/"authorizations"/authorization_id/"commit.json"
    for path in (assessment_commit_path,decision_path,decision_commit_path,authorization_path,authorization_commit_path):
        if not path.is_file(): raise ForecastSourceError("Approved lifecycle evidence is missing.")
    assessment_commit=_json(assessment_commit_path);decision=_json(decision_path);authorization=_json(authorization_path)
    _schema(assessment_commit,"runtime_assessment_commit.schema.json");_schema(decision,"runtime_decision.schema.json");_schema(authorization,"runtime_forecast_authorization.schema.json")
    lifecycle_hashes={"assessmentCommitSha256":sha256_file(assessment_commit_path),"decisionCommitSha256":sha256_file(decision_commit_path),"authorizationCommitSha256":sha256_file(authorization_commit_path)}
    if lifecycle_hashes["assessmentCommitSha256"]!=commit.get("assessmentCommitSha256") or lifecycle_hashes["decisionCommitSha256"]!=commit.get("decisionCommitSha256"): raise ForecastSourceError("Approved lifecycle commit binding mismatch.")
    if authorization.get("assessmentCommitSha256")!=lifecycle_hashes["assessmentCommitSha256"] or authorization.get("decisionCommitSha256")!=lifecycle_hashes["decisionCommitSha256"]: raise ForecastSourceError("Authorization lifecycle binding mismatch.")
    model_id=commit.get("selectedModelId");family=card.get("model",{}).get("family");parameter=commit.get("selectedModelParameterSha256")
    if MODEL_FAMILIES.get(model_id)!=family or parameter!=forecast.get("selectedModelParameterSha256") or parameter!=card.get("model",{}).get("parameterHash") or authorization.get("selectedModelId")!=model_id or authorization.get("selectedModelParameterSha256")!=parameter: raise ForecastSourceError("Approved selected-model binding mismatch.")
    if card.get("model",{}).get("candidateRegistrySha256")!=REGISTRY_SHA or card.get("features",{}).get("orderSha256")!=FEATURE_SHA: raise ForecastSourceError("Approved registry or feature binding mismatch.")
    if forecast.get("target")!="target_cases_next_2w" or forecast.get("horizonWeeks")!=2 or card.get("target")!="target_cases_next_2w" or card.get("horizonWeeks")!=2: raise ForecastSourceError("Approved target contract mismatch.","forecast_not_eligible")
    training=forecast.get("trainingDataIdentity",{});dashboard=_json(run/"artifacts/dashboard_summary.json");history=dashboard.get("history",[]);origin=(history[-1] if history else {}).get("period")
    if _advance(origin)!=forecast.get("targetPeriod"): raise ForecastSourceError("Approved target period mismatch.","target_period_mismatch")
    if forecast.get("forecastReported")!=int(round(max(0.0,float(forecast.get("forecastRaw"))))): raise ForecastSourceError("Approved reported forecast changed.")
    if uncertainty.get("uncertaintyStatus")!="pending_selected_model_calibration" or any(uncertainty.get(k) is not None for k in ("lowerRaw","upperRaw")): raise ForecastSourceError("Approved uncertainty evidence mismatch.")
    if version=="1.0":
        family_name="approved_forecast_p1"; assessment_policy=ASSESSMENT_P1;decision_policy=DECISION_P1
        assessment_summary=_json(root/"assessments"/assessment_id/"artifacts/assessment_summary.json")
        rolling=_json(root/"assessments"/assessment_id/"artifacts/rolling_validation.json");folds=rolling.get("folds",[])
        planned=assessment_summary.get("foldPolicy",{}).get("plannedFoldCount");selected_period={"start":folds[0]["targetPeriod"],"end":folds[-1]["targetPeriod"]} if folds else None
        labelled=assessment_summary.get("labelledRows")
        if (labelled,planned,training.get("trainingRowCount"),card.get("assessment",{}).get("foldCount"))!=(173,68,173,68): raise ForecastSourceError("Historical approved history changed.")
        if (decision.get("assessmentPolicyId"),decision.get("assessmentPolicyVersion"),decision.get("assessmentPolicySha256"))!=assessment_policy or (decision.get("decisionPolicyId"),decision.get("decisionPolicyVersion"),decision.get("decisionPolicySha256"))!=decision_policy: raise ForecastSourceError("Historical approved policy mismatch.")
        fold_plan=assessment_commit.get("foldPlanSha256");successful=68;failed=0;matrix=training.get("featureMatrixSha256")
    else:
        family_name="approved_forecast_p2";assessment_policy=ASSESSMENT_P2;decision_policy=DECISION_P2
        governance=forecast.get("governanceEvidence",{});labelled=governance.get("assessmentLabelledRows");planned=governance.get("assessmentPlannedFoldCount");selected_period=governance.get("selectedEvaluationPeriod");fold_plan=governance.get("foldPlanSha256");successful=governance.get("successfulFolds");failed=governance.get("failedFolds");matrix=training.get("featureMatrixSha256")
        if not isinstance(labelled,int) or labelled<157 or training.get("trainingRowCount")!=labelled or not isinstance(planned,int) or not 52<=planned<=68 or successful!=planned or failed!=0: raise ForecastSourceError("Phase 2 dynamic evidence mismatch.")
        if _policy_tuple(governance.get("assessmentPolicy",{}),True)!=assessment_policy or _policy_tuple(governance.get("decisionPolicy",{}),True)!=decision_policy: raise ForecastSourceError("Phase 2 policy binding mismatch.")
        expected={**lifecycle_hashes,"candidateRegistrySha256":REGISTRY_SHA,"foldPlanSha256":fold_plan}
        if any(governance.get(k)!=v for k,v in expected.items()) or commit.get("authorizationCommitSha256")!=lifecycle_hashes["authorizationCommitSha256"]: raise ForecastSourceError("Phase 2 governance hash mismatch.")
        if commit.get("technicalWinnerModelId")!=forecast.get("technicalWinnerModelId") or commit.get("technicalWinnerParameterSha256")!=forecast.get("technicalWinnerParameterSha256"): raise ForecastSourceError("Technical-winner evidence mismatch.")
    lifecycle={"assessmentId":assessment_id,"assessmentCommitSha256":lifecycle_hashes["assessmentCommitSha256"],"assessmentPolicy":{"policyId":assessment_policy[0],"policyVersion":assessment_policy[1],"policySha256":assessment_policy[2]},"decisionId":decision_id,"decisionCommitSha256":lifecycle_hashes["decisionCommitSha256"],"decisionPolicy":{"policyId":decision_policy[0],"policyVersion":decision_policy[1],"policySha256":decision_policy[2]},"authorizationId":authorization_id,"authorizationCommitSha256":lifecycle_hashes["authorizationCommitSha256"],"technicalWinnerModelId":commit.get("technicalWinnerModelId",forecast.get("technicalWinnerModelId")),"technicalWinnerParameterSha256":commit.get("technicalWinnerParameterSha256",decision.get("technicalWinnerParameterSha256")),"trainingRowCount":training.get("trainingRowCount"),"trainingPeriod":training.get("trainingPeriod"),"plannedFoldCount":planned,"successfulFolds":successful,"failedFolds":failed,"selectedEvaluationPeriod":selected_period,"foldPlanSha256":fold_plan,"featureMatrixSha256":matrix}
    return {"sourceFamily":family_name,"commit":commit,"forecast":forecast,"uncertainty":uncertainty,"calibration":None,"card":card,"snapshot":snapshot,"origin":origin,"modelId":model_id,"modelFamily":family,"parameterHash":parameter,"candidateRegistrySha256":REGISTRY_SHA,"featureOrderSha256":FEATURE_SHA,"sourcePolicy":{"policyId":decision_policy[0],"policyVersion":decision_policy[1],"policySha256":decision_policy[2]},"lifecycle":lifecycle}


def verify_forecast_source(root: Path, run_id: str, expected_commit: str, allowed_families: set[str] | None = None) -> dict[str,Any]:
    run,snapshot,commit=_snapshot_and_commit(root,run_id,expected_commit)
    workflow=commit.get("workflowMode")
    bundle=_quick(root,run,run_id,snapshot,commit) if workflow=="quick_forecast" else _approved(root,run,run_id,snapshot,commit) if workflow=="approved_assessment_forecast" else None
    if bundle is None or (allowed_families is not None and bundle["sourceFamily"] not in allowed_families): raise ForecastSourceError("Forecast source family is not governed.","forecast_not_eligible")
    return bundle
