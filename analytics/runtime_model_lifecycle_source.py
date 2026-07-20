"""Independent, action-specific immutable-source verification for lifecycle actions."""
from __future__ import annotations

import hashlib
import json
import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from runtime_active_model import FEATURE_SHA, PARAMETER_SHA, REGISTRY_SHA
from runtime_assessment_evidence import fold_plan_sha256
from runtime_assessment_commit import _reconcile as reconcile_assessment
from runtime_assessment_policy import load_and_validate_assessment_policy
from runtime_forecast_outcome_source import verify_forecast_source
from runtime_model_degradation_source import verify_model_degradation_source
from model_degradation_metrics import canonical_sha256

ASSESSMENT_POLICY = ("RUNTIME.DATASET_ASSESSMENT.GOVERNANCE", "p2-v1", "04c620ebe42526a74f1fe7054e3281df36bb587b363c027a3a675a86ee70efff")
DECISION_POLICY = ("RUNTIME.INTERNAL_ONE_RUN_MODEL_DECISION", "p2-v1", "aaef2ed2afd3afe03a0aec91889f144a3274cad21aa8cef8ef772bb90cfdcb4a")
MONITORING_POLICY = ("RUNTIME.FORECAST_OUTCOME.MONITORING", "p2-v1", "c73461e211e334733309232806fa2d41c2e5fdce7aa5e096d065e13e7525eaab")
DEGRADATION_POLICY = ("RUNTIME.MODEL_DEGRADATION.EVIDENCE", "p2-v1", "bb13b8ec1991c0587656bf4f202334dddb115135d3ac055fee21b5f5e44f3321")
QUICK_POLICY = ("RUNTIME.QUICK_FORECAST.COMPATIBILITY", "p1.4f-v1", "5e6bcb68e5f29a50f8d377892d7786cc1932b3435e8a0b709a363d6c2e42bb9a")
MODEL_FAMILIES = {"previous_week_naive":"PreviousWeekNaive","moving_average_4w":"MovingAverage4W","seasonal_naive_52w":"SeasonalNaive52W","ridge_regression":"Ridge","poisson_regression":"PoissonRegressor","random_forest":"RandomForestRegressor","gradient_boosting":"GradientBoostingRegressor"}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("lifecycle_source_missing_or_unsafe")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("lifecycle_source_not_object")
    return value


def _safe_path(root: Path, candidate: Path) -> Path:
    resolved_root=root.resolve(); resolved=candidate.resolve(strict=False)
    try: resolved.relative_to(resolved_root)
    except ValueError as exc: raise ValueError("lifecycle_source_path_escape") from exc
    current=resolved_root
    for part in candidate.absolute().relative_to(root.absolute()).parts:
        current=current/part
        if current.is_symlink(): raise ValueError("lifecycle_source_symlink")
    return candidate


def _artifact(root: Path, relative: str) -> Path:
    if not isinstance(relative,str) or not relative or "\\" in relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError("lifecycle_source_relative_path_invalid")
    path=_safe_path(root,root/relative)
    if path.is_symlink() or not path.is_file(): raise ValueError("lifecycle_source_missing_or_unsafe")
    return path


def _schema(repository_root: Path, value: Mapping[str, Any], name: str) -> None:
    definition = json.loads((repository_root / "config" / name).read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(definition, format_checker=FormatChecker()).iter_errors(value), key=lambda item: list(item.path))
    if errors:
        raise ValueError(f"lifecycle_source_schema_invalid:{name}:{errors[0].message}")


def _find_hash(runtime_root: Path, digest: str) -> Path:
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError("lifecycle_source_hash_invalid")
    matches = []
    for path in runtime_root.rglob("*.json"):
        if path.is_file() and not path.is_symlink():
            _safe_path(runtime_root,path)
            if sha256_file(path)==digest: matches.append(path)
    if len(matches) != 1:
        raise ValueError("lifecycle_source_hash_not_uniquely_resolved")
    return matches[0]


def assignment_pointer_state(runtime_root: Path) -> tuple[str, str | None]:
    path = runtime_root / "deployments/dhaka_south/model-assignment/latest.json"
    if path.is_symlink():
        raise ValueError("unsafe_model_assignment_pointer")
    return ("present", sha256_file(path)) if path.is_file() else ("absent", None)


def verify_expected_pointer(job: Mapping[str, Any], runtime_root: Path) -> tuple[str, str | None]:
    state, digest = assignment_pointer_state(runtime_root)
    if state != job["expectedAssignmentPointerState"] or digest != job.get("expectedAssignmentPointerSha256"):
        raise ValueError("stale_model_assignment_pointer")
    return state, digest


def _policy_tuple(value: Mapping[str, Any], prefix: str) -> tuple[Any, Any, Any]:
    return value.get(f"{prefix}PolicyId"), value.get(f"{prefix}PolicyVersion"), value.get(f"{prefix}PolicySha256")


def _verify_assessment(repository_root: Path, runtime_root: Path, commit_sha: str, model_id: str, family: str, parameter_sha: str) -> dict[str, Any]:
    commit_path = _find_hash(runtime_root, commit_sha)
    if commit_path.name != "commit.json" or commit_path.parent.name != "metadata" or commit_path.parent.parent.parent.name != "assessments":
        raise ValueError("assessment_commit_path_invalid")
    root = commit_path.parent.parent; commit = _json(commit_path)
    _schema(repository_root, commit, "runtime_assessment_commit.schema.json")
    assessment_path=root/"metadata/assessment.json"; assessment=_json(assessment_path); _schema(repository_root,assessment,"runtime_assessment.schema.json")
    if commit_path != runtime_root/"assessments"/str(commit.get("assessmentId"))/"metadata/commit.json" or commit.get("schemaVersion") != "2.0" or _policy_tuple(commit, "assessment") != ASSESSMENT_POLICY:
        raise ValueError("promotion_assessment_identity_invalid")
    artifacts = {
        "input_manifest.json": root / "artifacts/input_manifest.json",
        "model_features.csv": root / "artifacts/model_features.csv",
        "assessment_summary.json": root / "artifacts/assessment_summary.json",
        "rolling_validation.json": root / "artifacts/rolling_validation.json",
        "candidate_model_comparison.json": root / "artifacts/candidate_model_comparison.json",
        "recommendation.json": root / "artifacts/recommendation.json",
    }
    values: dict[str, dict[str, Any]] = {}
    feature_rows: list[dict[str,str]]=[]
    schemas = {"assessment_summary.json":"runtime_assessment_summary.schema.json","rolling_validation.json":"runtime_rolling_validation.schema.json","candidate_model_comparison.json":"runtime_candidate_comparison.schema.json","recommendation.json":"runtime_recommendation.schema.json"}
    for name, path in artifacts.items():
        _safe_path(runtime_root,path)
        if name=="model_features.csv":
            try:
                with path.open("r",encoding="utf-8",newline="") as handle:
                    feature_rows=list(csv.DictReader(handle))
                    if not feature_rows: raise ValueError("assessment_feature_matrix_empty")
            except (OSError,UnicodeDecodeError,csv.Error) as exc: raise ValueError("assessment_feature_matrix_invalid") from exc
        else:
            value = _json(path)
            if name in schemas: _schema(repository_root, value, schemas[name])
            values[name] = value
        if commit.get("artifactHashes", {}).get(name) != sha256_file(path):
            raise ValueError("assessment_artifact_hash_mismatch")
    if set(commit.get("artifactHashes",{}))!=set(artifacts): raise ValueError("assessment_commit_artifact_set_invalid")
    summary, rolling, comparison, recommendation = values["assessment_summary.json"], values["rolling_validation.json"], values["candidate_model_comparison.json"], values["recommendation.json"]
    policy,_=load_and_validate_assessment_policy("dhaka_south","p2-v1",ASSESSMENT_POLICY[2]);reconcile_assessment(rolling,comparison,recommendation,feature_rows,policy)
    identity=(commit.get("assessmentId"),commit.get("jobId"),commit.get("workspaceId"),commit.get("datasetId"),commit.get("deploymentId"))
    for value in (assessment,summary,rolling,comparison,recommendation):
        if tuple(value.get(k) for k in ("assessmentId","jobId","workspaceId","datasetId","deploymentId"))!=identity: raise ValueError("assessment_artifact_identity_mismatch")
    expected_sequence=["input_manifest.json","model_features.csv","rolling_validation.json","candidate_model_comparison.json","recommendation.json","assessment_summary.json"]
    if assessment.get("artifactPublicationSequence")!=expected_sequence: raise ValueError("assessment_publication_sequence_invalid")
    metadata_hash_fields={"input_manifest.json":"inputManifestSha256","model_features.csv":"modelFeaturesSha256","rolling_validation.json":"rollingValidationSha256","candidate_model_comparison.json":"candidateComparisonSha256","recommendation.json":"recommendationSha256","assessment_summary.json":"assessmentSummarySha256"}
    if any(assessment.get("artifactHashes",{}).get(field)!=sha256_file(artifacts[name]) for name,field in metadata_hash_fields.items()): raise ValueError("assessment_metadata_artifact_hash_mismatch")
    planned = comparison.get("plannedFoldCount")
    candidates = [candidate for candidate in comparison.get("candidates", []) if candidate.get("modelId") == model_id and candidate.get("parametersSha256") == parameter_sha]
    if len(candidates) != 1 or MODEL_FAMILIES.get(model_id)!=family or candidates[0].get("modelLabel")!=family or not isinstance(planned, int) or not 52 <= planned <= 68:
        raise ValueError("selected_assessment_candidate_invalid")
    candidate = candidates[0]
    folds=rolling.get("folds",[])
    if candidate.get("successfulFolds") != planned or candidate.get("failedFolds") != 0 or len(folds) != planned or any(len([p for p in fold.get("predictions",[]) if p.get("modelId")==model_id])!=1 for fold in folds):
        raise ValueError("selected_assessment_fold_evidence_invalid")
    fold_hash = fold_plan_sha256(folds)
    if any(value!=fold_hash for value in (assessment.get("foldPlanSha256"),rolling.get("foldPlanSha256"),comparison.get("foldPlanSha256"),recommendation.get("foldPlanSha256"),summary.get("foldPlanSha256"),commit.get("foldPlanSha256"))) or comparison.get("rollingValidationSha256") != sha256_file(artifacts["rolling_validation.json"]):
        raise ValueError("assessment_fold_plan_mismatch")
    period=comparison.get("selectedEvaluationPeriod")
    if any(value!=period for value in (assessment.get("selectedEvaluationPeriod"),rolling.get("selectedEvaluationPeriod"),summary.get("foldPolicy",{}).get("selectedEvaluationPeriod"))) or period!={"start":folds[0].get("forecastOrigin"),"end":folds[-1].get("forecastOrigin")}:
        raise ValueError("assessment_evaluation_period_mismatch")
    if any(value!=planned for value in (assessment.get("plannedFoldCount"),rolling.get("plannedFoldCount"),summary.get("foldPolicy",{}).get("plannedFoldCount"))) or comparison.get("technicalWinnerModelId")!=model_id or comparison.get("winnerParameterSha256")!=parameter_sha or summary.get("technicalWinnerModelId")!=model_id or recommendation.get("technicalWinnerModelId")!=model_id or recommendation.get("winnerParameterSha256")!=parameter_sha:
        raise ValueError("assessment_winner_reconciliation_failed")
    if comparison.get("candidateRegistrySha256") != REGISTRY_SHA or rolling.get("candidateRegistrySha256")!=REGISTRY_SHA or assessment.get("candidateRegistrySha256")!=REGISTRY_SHA or commit.get("candidateRegistrySha256")!=REGISTRY_SHA or summary.get("provenance", {}).get("candidateRegistrySha256") != REGISTRY_SHA or summary.get("provenance", {}).get("featureOrderSha256") != FEATURE_SHA or rolling.get("featureOrderSha256")!=FEATURE_SHA:
        raise ValueError("assessment_registry_or_feature_order_mismatch")
    if rolling.get("target")!="target_cases_next_2w" or rolling.get("horizonWeeks")!=2 or summary.get("candidates")!=comparison.get("candidates"): raise ValueError("assessment_contract_reconciliation_failed")
    return {"assessmentId": commit.get("assessmentId"),"jobId":commit.get("jobId"),"datasetId":commit.get("datasetId"),"commit":commit,"commitSha256":commit_sha,"summary":summary,"summarySha256":sha256_file(artifacts["assessment_summary.json"]),"comparison":comparison,"comparisonSha256":sha256_file(artifacts["candidate_model_comparison.json"]),"recommendationSha256":sha256_file(artifacts["recommendation.json"]),"rolling":rolling,"candidate":candidate,"modelFamily":family,"plannedFolds":planned,"evaluationPeriod":period,"foldPlanSha256":fold_hash}


def _verify_decision(repository_root: Path, runtime_root: Path, commit_sha: str, assessment: Mapping[str, Any], model_id: str, family: str, parameter_sha: str) -> dict[str, Any]:
    commit_path = _find_hash(runtime_root, commit_sha)
    commit = _json(commit_path); _schema(repository_root, commit, "runtime_decision_commit.schema.json")
    if commit_path != runtime_root/"decisions"/str(commit.get("decisionId"))/"commit.json": raise ValueError("promotion_decision_commit_path_invalid")
    decision_path = commit_path.parent / "decision.json"; decision = _json(decision_path); _schema(repository_root, decision, "runtime_decision.schema.json")
    if commit.get("schemaVersion") != "2.0" or commit.get("status") != "committed" or commit.get("decisionSha256") != sha256_file(decision_path):
        raise ValueError("promotion_decision_commit_invalid")
    if decision.get("schemaVersion") != "2.0" or decision.get("decision") != "approve_technical_winner" or decision.get("decisionStatus") != "approved_technical_winner" or decision.get("forecastAuthorized") is not True:
        raise ValueError("promotion_requires_approve_technical_winner")
    expected = (assessment["assessmentId"], assessment["commitSha256"], model_id, parameter_sha, model_id, parameter_sha)
    actual = (decision.get("assessmentId"), decision.get("assessmentCommitSha256"), decision.get("technicalWinnerModelId"), decision.get("technicalWinnerParameterSha256"), decision.get("selectedModelId"), decision.get("selectedModelParameterSha256"))
    if actual != expected or MODEL_FAMILIES.get(model_id)!=family or _policy_tuple(decision, "decision") != DECISION_POLICY or _policy_tuple(decision, "assessment") != ASSESSMENT_POLICY:
        raise ValueError("promotion_decision_reconciliation_failed")
    commit_expected=(decision.get("decisionId"),assessment["assessmentId"],assessment["commitSha256"],sha256_file(decision_path),ASSESSMENT_POLICY,DECISION_POLICY,assessment["foldPlanSha256"],assessment["summary"].get("labelledRows"),assessment["plannedFolds"])
    commit_actual=(commit.get("decisionId"),commit.get("assessmentId"),commit.get("assessmentCommitSha256"),commit.get("decisionSha256"),_policy_tuple(commit,"assessment"),_policy_tuple(commit,"decision"),commit.get("foldPlanSha256"),commit.get("assessmentLabelledRows"),commit.get("assessmentPlannedFoldCount"))
    if commit_actual!=commit_expected or decision.get("candidateRegistrySha256")!=REGISTRY_SHA or decision.get("foldPlanSha256")!=assessment["foldPlanSha256"] or decision.get("selectedEvaluationPeriod")!=assessment["evaluationPeriod"] or decision.get("assessmentSummarySha256")!=assessment["summarySha256"] or decision.get("comparisonSha256")!=assessment["comparisonSha256"] or decision.get("recommendationSha256")!=assessment["recommendationSha256"]:
        raise ValueError("promotion_decision_commit_reconciliation_failed")
    return {"decisionId": decision["decisionId"], "artifactSha256": sha256_file(decision_path), "commitSha256": commit_sha, "decision": decision, "commit": commit}


def verify_reject_assessment_decision(repository_root: Path, runtime_root: Path, job: Mapping[str,Any]) -> dict[str,Any]:
    assessment_commit_path=_find_hash(runtime_root,job["expectedAssessmentCommitSha256"]);root=assessment_commit_path.parent.parent
    comparison=_json(root/"artifacts/candidate_model_comparison.json");_schema(repository_root,comparison,"runtime_candidate_comparison.schema.json")
    model_id=comparison.get("technicalWinnerModelId");parameter=comparison.get("winnerParameterSha256");family=MODEL_FAMILIES.get(str(model_id))
    if not model_id or not parameter or not family: raise ValueError("rejected_assessment_winner_invalid")
    assessment=_verify_assessment(repository_root,runtime_root,job["expectedAssessmentCommitSha256"],str(model_id),family,str(parameter))
    commit_path=_find_hash(runtime_root,job["expectedDecisionCommitSha256"]);commit=_json(commit_path);_schema(repository_root,commit,"runtime_decision_commit.schema.json")
    decision_path=commit_path.parent/"decision.json";decision=_json(decision_path);_schema(repository_root,decision,"runtime_decision.schema.json")
    if commit_path!=runtime_root/"decisions"/str(commit.get("decisionId"))/"commit.json" or commit.get("schemaVersion")!="2.0" or commit.get("status")!="committed" or commit.get("decisionSha256")!=sha256_file(decision_path): raise ValueError("rejected_decision_commit_invalid")
    statuses={"approve_technical_winner":"approved_technical_winner","keep_current_model":"current_model_retained","defer":"deferred","reject_assessment":"assessment_rejected"}
    choice=decision.get("decision")
    if statuses.get(choice)!=decision.get("decisionStatus") or decision.get("assessmentId")!=assessment["assessmentId"] or decision.get("assessmentCommitSha256")!=assessment["commitSha256"] or _policy_tuple(decision,"assessment")!=ASSESSMENT_POLICY or _policy_tuple(decision,"decision")!=DECISION_POLICY or decision.get("candidateRegistrySha256")!=REGISTRY_SHA or decision.get("technicalWinnerModelId")!=model_id or decision.get("technicalWinnerParameterSha256")!=parameter: raise ValueError("rejected_decision_reconciliation_failed")
    if choice=="approve_technical_winner":
        if decision.get("selectedModelId")!=model_id or decision.get("selectedModelParameterSha256")!=parameter or decision.get("forecastAuthorized") is not True: raise ValueError("rejected_approved_decision_binding_invalid")
    elif decision.get("selectedModelId") is not None or decision.get("selectedModelParameterSha256") is not None or decision.get("forecastAuthorized") is not False:
        raise ValueError("rejected_nonapproval_decision_binding_invalid")
    if (commit.get("decisionId"),commit.get("assessmentId"),commit.get("assessmentCommitSha256"),_policy_tuple(commit,"assessment"),_policy_tuple(commit,"decision"),commit.get("foldPlanSha256"))!=(decision.get("decisionId"),assessment["assessmentId"],assessment["commitSha256"],ASSESSMENT_POLICY,DECISION_POLICY,assessment["foldPlanSha256"]): raise ValueError("rejected_decision_commit_reconciliation_failed")
    return {"evidenceContextStatus":"verified_assessment_and_decision","assessmentCommitSha256":assessment["commitSha256"],"decisionCommitSha256":sha256_file(commit_path)}


def _verify_authorization(repository_root: Path, runtime_root: Path, commit_sha: str, assessment: Mapping[str, Any], decision: Mapping[str, Any], run_id: str, run_commit: Mapping[str, Any], model_id: str, parameter_sha: str) -> dict[str, Any]:
    commit_path = _find_hash(runtime_root, commit_sha); commit = _json(commit_path); _schema(repository_root,commit,"runtime_forecast_authorization_commit.schema.json")
    if commit_path != runtime_root/"authorizations"/str(commit.get("authorizationId"))/"commit.json": raise ValueError("authorization_commit_path_invalid")
    record_path = commit_path.parent / "authorization.json"; record = _json(record_path); _schema(repository_root, record, "runtime_forecast_authorization.schema.json")
    if commit.get("status") != "committed" or commit.get("authorizationSha256") != sha256_file(record_path):
        raise ValueError("authorization_commit_invalid")
    expected = (assessment["assessmentId"], assessment["commitSha256"], decision["decisionId"], decision["commitSha256"], model_id, parameter_sha, "one_run")
    actual = (record.get("assessmentId"), record.get("assessmentCommitSha256"), record.get("decisionId"), record.get("decisionCommitSha256"), record.get("selectedModelId"), record.get("selectedModelParameterSha256"), record.get("scope"))
    if actual != expected or record.get("schemaVersion") != "2.0" or record.get("workflowMode")!="approved_assessment_forecast" or record.get("initialStatus")!="available" or _policy_tuple(record, "assessment") != ASSESSMENT_POLICY or _policy_tuple(record, "decision") != DECISION_POLICY:
        raise ValueError("authorization_binding_invalid")
    authorization_id = record["authorizationId"]
    if (commit.get("authorizationId"),commit.get("decisionId"),commit.get("decisionCommitSha256"))!=(authorization_id,decision["decisionId"],decision["commitSha256"]): raise ValueError("authorization_commit_binding_invalid")
    state=runtime_root/"authorization-state"/authorization_id; reservation_path=state/"reservation.json"; consumption_path=state/"consumption.json"
    reservation=_json(reservation_path); consumption = _json(consumption_path)
    _schema(repository_root,reservation,"runtime_authorization_event.schema.json"); _schema(repository_root,consumption,"runtime_authorization_event.schema.json")
    state_json={path.name for path in state.glob("*.json")}
    if state_json!={"reservation.json","consumption.json"}: raise ValueError("authorization_state_event_set_invalid")
    canonical_consumption=(json.dumps(consumption,indent=2,ensure_ascii=False)+"\n").encode("utf-8")
    if consumption_path.read_bytes()!=canonical_consumption:
        raise ValueError("authorization_consumption_not_canonical")
    approved_job_id=run_commit.get("jobId")
    common=(authorization_id,decision["decisionId"],approved_job_id,run_id)
    if (reservation.get("authorizationId"),reservation.get("decisionId"),reservation.get("jobId"),reservation.get("runId"))!=common or reservation.get("eventType")!="reserved" or (consumption.get("authorizationId"),consumption.get("decisionId"),consumption.get("jobId"),consumption.get("runId"))!=common or consumption.get("eventType")!="consumed" or reservation.get("eventId")==consumption.get("eventId"):
        raise ValueError("authorization_not_consumed_by_approved_forecast")
    run_consumptions=[]
    for candidate in (runtime_root/"authorization-state").glob("*/consumption.json"):
        value=_json(candidate);_schema(repository_root,value,"runtime_authorization_event.schema.json")
        if value.get("runId")==run_id: run_consumptions.append(candidate)
    if run_consumptions!=[consumption_path]: raise ValueError("authorization_consumption_not_unique")
    if run_commit.get("authorizationId") != authorization_id or run_commit.get("authorizationCommitSha256") != commit_sha:
        raise ValueError("approved_forecast_authorization_binding_invalid")
    reserved_at=datetime.fromisoformat(str(reservation["createdAt"]).replace("Z","+00:00")); consumed_at = datetime.fromisoformat(str(consumption["createdAt"]).replace("Z", "+00:00")); committed_at = datetime.fromisoformat(str(run_commit["committedAt"]).replace("Z", "+00:00")); created_at=datetime.fromisoformat(str(record["createdAt"]).replace("Z","+00:00")); expires_at=datetime.fromisoformat(str(record["expiresAt"]).replace("Z","+00:00"))
    if not created_at <= reserved_at <= committed_at <= consumed_at <= expires_at:
        raise ValueError("authorization_consumed_before_forecast_commit")
    return {"authorizationId":authorization_id,"record":record,"commit":commit,"recordSha256":sha256_file(record_path),"commitSha256":commit_sha,"reservationSha256":sha256_file(reservation_path),"consumptionSha256":sha256_file(consumption_path),"consumption":consumption}


def _verify_approved_forecast(repository_root: Path, runtime_root: Path, commit_sha: str) -> dict[str,Any]:
    commit_path=_find_hash(runtime_root,commit_sha); commit=_json(commit_path); _schema(repository_root,commit,"runtime_approved_forecast_commit.schema.json")
    run_id=str(commit.get("runId","")); run_root=runtime_root/"runs"/run_id
    if commit_path!=run_root/"metadata/commit.json" or commit.get("schemaVersion")!="2.0" or commit.get("status")!="committed" or commit.get("workflowMode")!="approved_assessment_forecast" or commit.get("sourceType")!="uploaded": raise ValueError("approved_forecast_commit_identity_invalid")
    run_path=run_root/"metadata/run.json"; run=_json(run_path); _schema(repository_root,run,"runtime_approved_forecast_run.schema.json")
    expected_artifacts={"input_manifest.json","model_features.csv","forecast_output.json","forecast_uncertainty.json","dashboard_summary.json","model_card.json","chart_data.json","pipeline_run_summary.json"}
    if set(commit.get("artifactHashes",{}))!=expected_artifacts: raise ValueError("approved_forecast_artifact_set_invalid")
    schema_map={"forecast_output.json":"runtime_approved_forecast_output.schema.json","forecast_uncertainty.json":"runtime_approved_forecast_uncertainty.schema.json","dashboard_summary.json":"runtime_approved_forecast_dashboard.schema.json","model_card.json":"runtime_approved_forecast_model_card.schema.json"}
    values={}
    for name,digest in commit["artifactHashes"].items():
        path=run_root/"artifacts"/name; _safe_path(runtime_root,path)
        if sha256_file(path)!=digest: raise ValueError("approved_forecast_artifact_hash_mismatch")
        if name.endswith(".json"):
            value=_json(path); values[name]=value
            if name in schema_map: _schema(repository_root,value,schema_map[name])
    if commit.get("runRecordSha256")!=sha256_file(run_path) or commit.get("forecastOutputSha256")!=sha256_file(run_root/"artifacts/forecast_output.json") or commit.get("modelCardSha256")!=sha256_file(run_root/"artifacts/model_card.json"): raise ValueError("approved_forecast_named_hash_mismatch")
    bundle=verify_forecast_source(runtime_root,run_id,commit_sha,{"approved_forecast_p2"})
    forecast=values["forecast_output.json"];card=values["model_card.json"]
    common=(run_id,commit.get("jobId"),commit.get("assessmentId"),commit.get("decisionId"),commit.get("authorizationId"),commit.get("selectedModelId"),commit.get("selectedModelParameterSha256"))
    if common!=(run.get("runId"),run.get("jobId"),run.get("assessmentId"),run.get("decisionId"),run.get("authorizationId"),run.get("selectedModelId"),run.get("selectedModelParameterSha256")) or common!=(forecast.get("runId"),forecast.get("jobId"),forecast.get("assessmentId"),forecast.get("decisionId"),forecast.get("authorizationId"),forecast.get("selectedModelId"),forecast.get("selectedModelParameterSha256")) or common[:5]!=(card.get("runId"),card.get("jobId"),card.get("assessment",{}).get("id"),card.get("decision",{}).get("id"),card.get("authorization",{}).get("id")):
        raise ValueError("approved_forecast_artifact_identity_mismatch")
    lifecycle=bundle["lifecycle"]; training=forecast.get("trainingDataIdentity",{})
    expected=(commit.get("assessmentCommitSha256"),commit.get("decisionCommitSha256"),commit.get("authorizationCommitSha256"),commit.get("candidateRegistrySha256"),commit.get("featureOrderSha256"),commit.get("featureMatrixSha256"),commit.get("trainingRowCount"),commit.get("trainingPeriod"),commit.get("assessmentPlannedFoldCount"),commit.get("foldPlanSha256"),commit.get("target"),commit.get("horizonWeeks"))
    actual=(lifecycle.get("assessmentCommitSha256"),lifecycle.get("decisionCommitSha256"),lifecycle.get("authorizationCommitSha256"),bundle.get("candidateRegistrySha256"),bundle.get("featureOrderSha256"),lifecycle.get("featureMatrixSha256"),lifecycle.get("trainingRowCount"),lifecycle.get("trainingPeriod"),lifecycle.get("plannedFoldCount"),lifecycle.get("foldPlanSha256"),forecast.get("target"),forecast.get("horizonWeeks"))
    if actual!=expected or training.get("featureMatrixSha256")!=commit.get("featureMatrixSha256") or commit.get("successfulFolds")!=commit.get("assessmentPlannedFoldCount") or commit.get("failedFolds")!=0 or commit.get("completeReconciliation") is not True:
        raise ValueError("approved_forecast_complete_reconciliation_failed")
    return {"commitPath":commit_path,"commit":commit,"run":run,"bundle":bundle,"runId":run_id,"forecast":forecast,"card":card}


def _verify_outcome(repository_root: Path, runtime_root: Path, commit_sha: str, approved: Mapping[str,Any]) -> dict[str,Any]:
    commit_path=_find_hash(runtime_root,commit_sha); commit=_json(commit_path); _schema(repository_root,commit,"runtime_forecast_outcome_commit.schema.json")
    outcome_id=str(commit.get("outcomeId","")); root=runtime_root/"forecast-outcomes"/outcome_id
    if commit_path!=root/"metadata/commit.json" or commit.get("schemaVersion")!="2.0" or commit.get("status")!="committed" or commit.get("sourceFamily")!="approved_forecast_p2" or (commit.get("policyId"),commit.get("policyVersion"),commit.get("policySha256"))!=MONITORING_POLICY: raise ValueError("forecast_outcome_commit_identity_invalid")
    paths={name:root/"artifacts"/name for name in ("observation.json","outcome_evaluation.json","monitoring_summary.json")}
    if set(commit.get("artifactHashes",{}))!=set(paths): raise ValueError("forecast_outcome_artifact_set_invalid")
    for name,path in paths.items():
        _safe_path(runtime_root,path)
        if sha256_file(path)!=commit["artifactHashes"][name]: raise ValueError("forecast_outcome_artifact_hash_mismatch")
    outcome=_json(paths["outcome_evaluation.json"]); observation=_json(paths["observation.json"]); summary=_json(paths["monitoring_summary.json"])
    _schema(repository_root,outcome,"runtime_forecast_outcome.schema.json");_schema(repository_root,observation,"runtime_forecast_observation.schema.json");_schema(repository_root,summary,"runtime_monitoring_summary.schema.json")
    approved_commit=approved["commit"]; bundle=approved["bundle"]
    expected=(outcome_id,approved["runId"],sha256_file(approved["commitPath"]),bundle["modelId"],bundle["modelFamily"],bundle["parameterHash"],"target_cases_next_2w",2)
    actual=(outcome.get("outcomeId"),outcome.get("sourceForecastRunId"),outcome.get("sourceForecastCommitSha256"),outcome.get("modelId"),outcome.get("modelFamily"),outcome.get("modelParametersSha256"),outcome.get("targetColumn"),outcome.get("forecastHorizonWeeks"))
    if actual!=expected or commit.get("forecastRunId")!=approved["runId"] or commit.get("forecastCommitSha256")!=sha256_file(approved["commitPath"]): raise ValueError("forecast_outcome_promotion_binding_invalid")
    source=outcome.get("sourceEvidence",{})
    expected_source=(approved_commit.get("assessmentId"),approved_commit.get("assessmentCommitSha256"),approved_commit.get("decisionId"),approved_commit.get("decisionCommitSha256"),approved_commit.get("authorizationId"),approved_commit.get("authorizationCommitSha256"),approved_commit.get("technicalWinnerModelId"),approved_commit.get("technicalWinnerParameterSha256"),approved_commit.get("foldPlanSha256"),approved_commit.get("featureMatrixSha256"))
    actual_source=(source.get("assessmentId"),source.get("assessmentCommitSha256"),source.get("decisionId"),source.get("decisionCommitSha256"),source.get("authorizationId"),source.get("authorizationCommitSha256"),source.get("technicalWinnerModelId"),source.get("technicalWinnerParameterSha256"),source.get("foldPlanSha256"),source.get("featureMatrixSha256"))
    if actual_source!=expected_source or outcome.get("monitoringPolicy",{})!={"policyId":MONITORING_POLICY[0],"policyVersion":MONITORING_POLICY[1],"policySha256":MONITORING_POLICY[2]}: raise ValueError("forecast_outcome_lifecycle_evidence_mismatch")
    observation_expected=(outcome_id,commit.get("jobId"),approved["runId"],outcome.get("forecastTargetPeriod"),outcome.get("observedRaw"),"approved_forecast_p2")
    observation_actual=(observation.get("outcomeId"),observation.get("jobId"),observation.get("forecastRunId"),observation.get("forecastTargetPeriod"),observation.get("observedRaw"),observation.get("sourceFamily"))
    if observation_actual!=observation_expected or outcome.get("observationArtifactSha256")!=sha256_file(paths["observation.json"]): raise ValueError("forecast_outcome_observation_mismatch")
    return {"outcomeId":outcome_id,"commit":commit,"commitSha256":commit_sha,"outcome":outcome,"outcomeEvidenceSha256":sha256_file(paths["outcome_evaluation.json"]),"summary":summary}


def _verify_monitoring(repository_root: Path, runtime_root: Path, job: Mapping[str,Any]) -> dict[str,Any]:
    monitoring=verify_model_degradation_source(runtime_root,job["expectedMonitoringLatestSha256"],job["expectedMonitoringSummarySha256"],job["expectedMonitoringIncludedOutcomeSetSha256"])
    latest=monitoring["latest"]; summary=monitoring["summary"]
    expected_summary=f"forecast-outcomes/{latest['outcomeId']}/artifacts/monitoring_summary.json"
    if latest.get("monitoringSummaryPath")!=expected_summary or latest.get("monitoringSummarySha256")!=monitoring["summarySha256"] or (latest.get("policyId"),latest.get("policyVersion"),latest.get("policySha256"))!=MONITORING_POLICY or (summary.get("policyId"),summary.get("policyVersion"),summary.get("policySha256"))!=MONITORING_POLICY: raise ValueError("monitoring_pointer_summary_binding_invalid")
    included=summary.get("includedOutcomes",[])
    verified_members=[{"outcomeId":row["outcomeId"],"outcomeEvidenceSha256":row["outcomeEvidenceSha256"]} for row in monitoring["includedOutcomes"]]
    if len({row.get("outcomeId") for row in included})!=len(included) or sorted(included,key=lambda row:row["outcomeId"])!=sorted(verified_members,key=lambda row:row["outcomeId"]): raise ValueError("monitoring_included_outcome_binding_invalid")
    selected=next((row for row in monitoring["includedOutcomes"] if row["outcomeId"]==latest.get("outcomeId")),None)
    if selected is None or latest.get("outcomeCommitSha256")!=selected["outcomeCommitSha256"]: raise ValueError("monitoring_latest_outcome_commit_binding_invalid")
    for record in monitoring["outcomes"]:
        source=record.get("sourceFamily"); policy=record.get("sourcePolicy",{})
        expected=QUICK_POLICY if source=="quick_forecast_p1" else DECISION_POLICY if source=="approved_forecast_p2" else None
        if expected is None or (policy.get("policyId"),policy.get("policyVersion"),policy.get("policySha256"))!=expected: raise ValueError("monitoring_source_policy_incompatible")
    return monitoring


def _verify_degradation(repository_root: Path, runtime_root: Path, job: Mapping[str, Any], monitoring: Mapping[str, Any], outcome_id: str | None, assessment_id: str | None, assessment_commit_sha: str | None, model_id: str, family: str, parameter_sha: str) -> dict[str, Any]:
    latest_path = runtime_root / "deployments/dhaka_south/degradation/latest.json"; latest = _json(latest_path); _schema(repository_root, latest, "runtime_model_degradation_latest.schema.json")
    if sha256_file(latest_path) != job["expectedDegradationLatestSha256"]:
        raise ValueError("degradation_latest_hash_mismatch")
    evidence_id=str(latest.get("evidenceId","")); expected_root=f"degradation-evidence/{evidence_id}"
    expected_paths={"commitPath":f"{expected_root}/metadata/commit.json","evidencePath":f"{expected_root}/artifacts/degradation_evidence.json","summaryPath":f"{expected_root}/artifacts/degradation_summary.json"}
    if any(latest.get(key)!=value for key,value in expected_paths.items()): raise ValueError("degradation_artifact_path_invalid")
    commit_path = _artifact(runtime_root,latest["commitPath"]); evidence_path = _artifact(runtime_root,latest["evidencePath"]); summary_path = _artifact(runtime_root,latest["summaryPath"])
    commit, evidence, summary = _json(commit_path), _json(evidence_path), _json(summary_path)
    _schema(repository_root, commit, "runtime_model_degradation_commit.schema.json"); _schema(repository_root, evidence, "runtime_model_degradation_evidence.schema.json"); _schema(repository_root, summary, "runtime_model_degradation_summary.schema.json")
    if (sha256_file(commit_path), sha256_file(evidence_path)) != (job["expectedDegradationEvidenceCommitSha256"], job["expectedDegradationEvidenceSha256"]):
        raise ValueError("degradation_artifact_hash_mismatch")
    commit_sha,evidence_sha,summary_sha=sha256_file(commit_path),sha256_file(evidence_path),sha256_file(summary_path)
    if latest.get("commitSha256") != commit_sha or latest.get("evidenceSha256") != evidence_sha or latest.get("summarySha256") != summary_sha:
        raise ValueError("degradation_latest_binding_mismatch")
    if commit.get("artifactHashes")!={"degradation_evidence.json":evidence_sha,"degradation_summary.json":summary_sha} or (commit.get("evidenceId"),evidence.get("evidenceId"),summary.get("evidenceId"))!=(evidence_id,evidence_id,evidence_id): raise ValueError("degradation_commit_artifact_binding_mismatch")
    if (commit.get("policyId"),commit.get("policyVersion"),commit.get("policySha256"))!=DEGRADATION_POLICY or (commit.get("monitoringPolicyId"),commit.get("monitoringPolicyVersion"),commit.get("monitoringPolicySha256"))!=MONITORING_POLICY or (summary.get("policyId"),summary.get("policyVersion"),summary.get("policySha256"))!=DEGRADATION_POLICY or (summary.get("monitoringPolicyId"),summary.get("monitoringPolicyVersion"),summary.get("monitoringPolicySha256"))!=MONITORING_POLICY: raise ValueError("degradation_policy_identity_mismatch")
    if evidence.get("monitoringInput", {}).get("latestSha256") != monitoring["latestSha256"] or evidence.get("monitoringInput", {}).get("summarySha256") != monitoring["summarySha256"] or evidence.get("monitoringInput", {}).get("includedOutcomeSetSha256") != monitoring["summary"].get("outcomeSetSha256"):
        raise ValueError("degradation_monitoring_snapshot_mismatch")
    if (latest.get("monitoringLatestInputSha256"),latest.get("monitoringSummaryInputSha256"),latest.get("includedOutcomeSetSha256"))!=(monitoring["latestSha256"],monitoring["summarySha256"],monitoring["summary"].get("outcomeSetSha256")) or (commit.get("monitoringLatestSha256"),commit.get("monitoringSummarySha256"),commit.get("includedOutcomeSetSha256"))!=(monitoring["latestSha256"],monitoring["summarySha256"],monitoring["summary"].get("outcomeSetSha256")): raise ValueError("degradation_monitoring_commit_binding_mismatch")
    if (evidence.get("evidenceStatus"), evidence.get("materialWorseningStatus"), evidence.get("lifecycleActionStatus")) != ("evidence_only","not_governed","prohibited_not_generated"):
        raise ValueError("degradation_lifecycle_status_invalid")
    statuses=("evidence_only","not_governed","prohibited_not_generated")
    if (latest.get("evidenceStatus"),latest.get("materialWorseningStatus"),latest.get("lifecycleActionStatus"))!=statuses or (summary.get("evidenceStatus"),summary.get("materialWorseningStatus"),summary.get("lifecycleActionStatus"))!=statuses or commit.get("lifecycleActionProduced") is not False: raise ValueError("degradation_status_reconciliation_failed")
    expected_outcomes=sorted(monitoring["includedOutcomes"],key=lambda row:row["outcomeId"])
    if sorted(commit.get("includedOutcomes",[]),key=lambda row:row["outcomeId"])!=expected_outcomes or len({row["outcomeId"] for row in commit.get("includedOutcomes",[])})!=len(expected_outcomes): raise ValueError("degradation_included_outcome_membership_invalid")
    cohort_hash=canonical_sha256([{"cohortId":value["cohortId"],"outcomeSetSha256":value["outcomeSetSha256"]} for value in evidence.get("cohorts",[])])
    if cohort_hash!=evidence.get("includedCohortSetSha256") or cohort_hash!=commit.get("includedCohortSetSha256") or cohort_hash!=summary.get("includedCohortSetSha256"): raise ValueError("degradation_cohort_hash_mismatch")
    cohorts=evidence.get("cohorts",[]); ref_count=sum(len(value.get("assessmentReferences",[])) for value in cohorts)
    def counts(selector):
        result={}
        for value in cohorts:
            key=str(selector(value));result[key]=result.get(key,0)+value.get("outcomeCount",0)
        return dict(sorted(result.items()))
    periods=[record.get("forecastTargetPeriod") for record in monitoring["outcomes"]]
    summary_expected={"verifiedOutcomeCount":len(monitoring["outcomes"]),"cohortCount":len(cohorts),"assessmentReferenceDimensionCount":ref_count,"computableDescriptiveDimensionCount":ref_count,"insufficientEvidenceDimensionCount":0,"windowSizeNotGovernedDimensionCount":len(cohorts),"percentageUnavailableDimensionCount":sum("percentage_metric_unavailable" in value.get("warnings",[]) for value in cohorts),"rangeUnavailableDimensionCount":sum("range_metric_unavailable" in value.get("warnings",[]) for value in cohorts),"sourceFamilyCounts":counts(lambda value:value["identity"]["sourceFamily"]),"modelCounts":counts(lambda value:f"{value['identity']['modelId']}|{value['identity']['modelFamily']}|{value['identity']['parameterSha256']}"),"policyCounts":counts(lambda value:f"{value['identity']['monitoringPolicy']['policyId']}|{value['identity']['monitoringPolicy']['policyVersion']}|{value['identity']['monitoringPolicy']['policySha256']}"),"latestTargetPeriod":max(periods),"includedOutcomeSetSha256":monitoring["summary"].get("outcomeSetSha256"),"includedCohortSetSha256":cohort_hash,"generatedAt":evidence.get("generatedAt")}
    if any(summary.get(key)!=value for key,value in summary_expected.items()): raise ValueError("degradation_summary_reconciliation_failed")
    if assessment_id is None or outcome_id is None:
        active=[]
        for cohort in cohorts:
            identity=cohort.get("identity",{}); source=identity.get("sourceFamily"); forecast_policy=identity.get("forecastPolicy",{})
            expected_policy=QUICK_POLICY if source=="quick_forecast_p1" else DECISION_POLICY if source=="approved_forecast_p2" else None
            if (identity.get("modelId"),identity.get("modelFamily"),identity.get("parameterSha256"))==(model_id,family,parameter_sha) and expected_policy and (forecast_policy.get("policyId"),forecast_policy.get("policyVersion"),forecast_policy.get("policySha256"))==expected_policy:
                active.append(cohort)
        if not active: raise ValueError("lifecycle_context_not_bound_to_active_model")
        cohort=active[0]
        return {"latestSha256":sha256_file(latest_path),"evidenceId":evidence["evidenceId"],"commitSha256":commit_sha,"evidenceSha256":evidence_sha,"summarySha256":summary_sha,"cohortId":cohort["cohortId"],"dimensionId":None,"evidence":evidence,"commit":commit,"summary":summary}
    matches = []
    for cohort in evidence.get("cohorts", []):
        identity = cohort.get("identity", {})
        outcome_ids = {row.get("outcomeId") for row in cohort.get("orderedOutcomes", [])}
        for reference in cohort.get("assessmentReferences", []):
            if outcome_id in outcome_ids and (reference.get("assessmentId"), reference.get("assessmentCommitSha256"), reference.get("modelId"), reference.get("modelFamily"), reference.get("parameterSha256")) == (assessment_id, assessment_commit_sha, model_id, family, parameter_sha) and (identity.get("modelId"), identity.get("modelFamily"), identity.get("parameterSha256")) == (model_id, family, parameter_sha):
                matches.append((cohort, reference))
    if len(matches) != 1:
        raise ValueError("degradation_assessment_reference_membership_invalid")
    cohort, reference = matches[0]
    selected_rows=[row for row in cohort.get("orderedOutcomes",[]) if row.get("outcomeId")==outcome_id]
    selected_commit=next((row for row in expected_outcomes if row["outcomeId"]==outcome_id),None)
    if len(selected_rows)!=1 or selected_commit is None or any(selected_rows[0].get(key)!=selected_commit.get(key) for key in ("outcomeCommitSha256","outcomeEvidenceSha256")): raise ValueError("degradation_selected_outcome_binding_invalid")
    references=[row for row in commit.get("assessmentReferences",[]) if row.get("assessmentId")==assessment_id]
    if len(references)!=1 or references[0].get("assessmentCommitSha256")!=assessment_commit_sha or references[0].get("candidateComparisonSha256")!=reference.get("candidateComparisonSha256"): raise ValueError("degradation_commit_assessment_reference_invalid")
    dimension = f"{cohort['cohortId']}:{assessment_id}:{model_id}:{parameter_sha}"
    return {"latestSha256":sha256_file(latest_path),"evidenceId":evidence["evidenceId"],"commitSha256":commit_sha,"evidenceSha256":evidence_sha,"summarySha256":summary_sha,"cohortId":cohort["cohortId"],"dimensionId":dimension,"evidence":evidence,"commit":commit,"summary":summary}


def verify_monitoring_and_degradation_context(repository_root: Path, runtime_root: Path, job: Mapping[str, Any], active: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if job.get("evidenceContextStatus") == "explicit_no_evidence":
        return {"evidenceContextStatus":"explicit_no_evidence"}
    monitoring = _verify_monitoring(repository_root,runtime_root,job)
    identity=active or {"modelId":"random_forest","modelFamily":"RandomForestRegressor","parameterSha256":PARAMETER_SHA}
    degradation=_verify_degradation(repository_root,runtime_root,job,monitoring,None,None,None,identity["modelId"],identity["modelFamily"],identity["parameterSha256"])
    return {"evidenceContextStatus":"verified_monitoring_and_degradation","monitoringLatestSha256":monitoring["latestSha256"],"monitoringSummarySha256":monitoring["summarySha256"],"monitoringIncludedOutcomeSetSha256":monitoring["summary"]["outcomeSetSha256"],"degradationLatestSha256":degradation["latestSha256"],"degradationEvidenceCommitSha256":degradation["commitSha256"],"degradationEvidenceSha256":degradation["evidenceSha256"]}


def verify_promotion_sources(repository_root: Path, runtime_root: Path, job: Mapping[str, Any]) -> dict[str, Any]:
    approved=_verify_approved_forecast(repository_root,runtime_root,job["expectedApprovedForecastCommitSha256"]); approved_commit=approved["commit"];run_id=approved["runId"];bundle=approved["bundle"]
    model_id, family, parameter = bundle["modelId"], bundle["modelFamily"], bundle["parameterHash"]
    assessment = _verify_assessment(repository_root, runtime_root, job["expectedAssessmentCommitSha256"], model_id, family, parameter)
    decision = _verify_decision(repository_root, runtime_root, job["expectedDecisionCommitSha256"], assessment, model_id, family, parameter)
    authorization = _verify_authorization(repository_root, runtime_root, job["expectedAuthorizationCommitSha256"], assessment, decision, run_id, approved_commit, model_id, parameter)
    lifecycle = bundle["lifecycle"]
    if (approved_commit.get("assessmentCommitSha256"),approved_commit.get("decisionCommitSha256"),approved_commit.get("authorizationCommitSha256"),approved_commit.get("selectedModelId"),approved_commit.get("selectedModelParameterSha256"),approved_commit.get("technicalWinnerModelId"),approved_commit.get("technicalWinnerParameterSha256"),approved_commit.get("candidateRegistrySha256"),approved_commit.get("featureOrderSha256")) != (assessment["commitSha256"],decision["commitSha256"],authorization["commitSha256"],model_id,parameter,model_id,parameter,REGISTRY_SHA,FEATURE_SHA):
        raise ValueError("approved_forecast_promotion_binding_invalid")
    outcome_verified=_verify_outcome(repository_root,runtime_root,job["expectedOutcomeCommitSha256"],approved); outcome=outcome_verified["outcome"]
    monitoring = _verify_monitoring(repository_root,runtime_root,job); outcome_id = outcome_verified["outcomeId"]
    members = [row for row in monitoring["includedOutcomes"] if row["outcomeId"] == outcome_id and row["outcomeCommitSha256"] == job["expectedOutcomeCommitSha256"] and row["outcomeEvidenceSha256"]==outcome_verified["outcomeEvidenceSha256"]]
    if len(members) != 1 or not any(record.get("outcomeId") == outcome_id and record.get("modelId") == model_id and record.get("modelFamily")==family and record.get("modelParametersSha256")==parameter and record.get("sourceFamily") == "approved_forecast_p2" for record in monitoring["outcomes"]):
        raise ValueError("monitoring_outcome_membership_invalid")
    degradation = _verify_degradation(repository_root,runtime_root,job,monitoring,outcome_id,assessment["assessmentId"],assessment["commitSha256"],model_id,family,parameter)
    if (model_id,family,parameter,bundle["candidateRegistrySha256"],bundle["featureOrderSha256"]) != ("random_forest","RandomForestRegressor",PARAMETER_SHA,REGISTRY_SHA,FEATURE_SHA):
        raise ValueError("selected_model_not_active_quick_forecast_compatible")
    return {"selectedModelId":model_id,"selectedModelFamily":family,"selectedModelParameterSha256":parameter,"candidateRegistrySha256":REGISTRY_SHA,"featureOrderSha256":FEATURE_SHA,"sourceAssessmentId":assessment["assessmentId"],"sourceAssessmentCommitSha256":assessment["commitSha256"],"sourceDecisionId":decision["decisionId"],"sourceDecisionArtifactSha256":decision["artifactSha256"],"sourceDecisionCommitSha256":decision["commitSha256"],"sourceAuthorizationId":authorization["authorizationId"],"sourceAuthorizationRecordSha256":authorization["recordSha256"],"sourceAuthorizationCommitSha256":authorization["commitSha256"],"sourceAuthorizationConsumptionSha256":authorization["consumptionSha256"],"sourceApprovedForecastId":run_id,"sourceApprovedForecastCommitSha256":job["expectedApprovedForecastCommitSha256"],"sourceOutcomeId":outcome_id,"sourceOutcomeCommitSha256":job["expectedOutcomeCommitSha256"],"sourceMonitoringLatestSha256":monitoring["latestSha256"],"sourceMonitoringSummarySha256":monitoring["summarySha256"],"sourceMonitoringIncludedOutcomeSetSha256":monitoring["summary"]["outcomeSetSha256"],"sourceDegradationLatestSha256":degradation["latestSha256"],"sourceDegradationEvidenceId":degradation["evidenceId"],"sourceDegradationEvidenceCommitSha256":degradation["commitSha256"],"sourceDegradationEvidenceSha256":degradation["evidenceSha256"],"assessmentReferenceCohortId":degradation["cohortId"],"assessmentReferenceDimensionId":degradation["dimensionId"]}


def resolve_previous_assignment(runtime_root: Path, active: Mapping[str, Any]) -> dict[str, Any]:
    prior = active.get("priorAssignmentId")
    if not prior:
        raise ValueError("rollback_previous_assignment_unavailable")
    matches = []
    for path in (runtime_root / "model-lifecycle").glob("*/artifacts/model_assignment.json"):
        value = _json(path)
        if value.get("assignmentId") == prior:
            matches.append((path, value))
    if len(matches) != 1:
        raise ValueError("rollback_source_assignment_invalid")
    path, value = matches[0]; commit_path = path.parent.parent / "metadata/model_assignment_commit.json"
    if (value.get("assignedModelId"),value.get("modelFamily"),value.get("parameterSha256"),value.get("featureOrderSha256"),value.get("candidateRegistrySha256")) != ("random_forest","RandomForestRegressor",PARAMETER_SHA,FEATURE_SHA,REGISTRY_SHA):
        raise ValueError("selected_model_not_active_quick_forecast_compatible")
    return {"assignment":value,"commitSha256":sha256_file(commit_path)}
