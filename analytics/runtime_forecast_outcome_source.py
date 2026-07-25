"""Strict, side-effect-free verification of governed runtime forecast sources."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from forecast_outcome_metrics import parse_target_period
from model_factory import load_and_validate_candidate_registry
from runtime_commit import sha256_file
from runtime_context import ROOT

QUICK_POLICY = ("RUNTIME.QUICK_FORECAST.COMPATIBILITY", "p1.4f-v1", "5e6bcb68e5f29a50f8d377892d7786cc1932b3435e8a0b709a363d6c2e42bb9a")
QUICK_P2_POLICY = ("RUNTIME.QUICK_FORECAST.COMPATIBILITY", "p2-v1", "4a6f166d037ab4c69df980549626d993db473bcec325fa2a68dbe5f8485a757e")
LIFECYCLE_P2_V2 = ("RUNTIME.MODEL_LIFECYCLE.DECISION", "p2-v2", "294b7949adecc39b284adaa198db47109ee4b1cc39259e87bc9073e1bff93b64")
ASSESSMENT_P1 = ("RUNTIME.DATASET_ASSESSMENT.GOVERNANCE", "p1.4d-1-v1", "dbf9d4cc4713bbb9d114b2dab916d0f20b3004ac14b37ca663c3caecefcea0af")
ASSESSMENT_P2 = ("RUNTIME.DATASET_ASSESSMENT.GOVERNANCE", "p2-v1", "04c620ebe42526a74f1fe7054e3281df36bb587b363c027a3a675a86ee70efff")
ASSESSMENT_P2_V2 = ("RUNTIME.DATASET_ASSESSMENT.GOVERNANCE", "p2-v2", "569faeca27a4715e72085ac97c78b00f83351bd7783fc156f5bd8f626cab28b8")
DECISION_P1 = ("RUNTIME.INTERNAL_ONE_RUN_MODEL_DECISION", "p1.4d-3-e-v1", "8fece340b85951d3bee8b037c4ac79ae82636ee371a934e9371bcb4a633491a4")
DECISION_P2 = ("RUNTIME.INTERNAL_ONE_RUN_MODEL_DECISION", "p2-v1", "aaef2ed2afd3afe03a0aec91889f144a3274cad21aa8cef8ef772bb90cfdcb4a")
DECISION_P2_V2 = ("RUNTIME.INTERNAL_ONE_RUN_MODEL_DECISION", "p2-v2", "6f643f01e7e01353986af52f395b2c71cb05dc162ba7f71127c1397ce2adcf1d")
REGISTRY_SHA = "2e627f8a368a7e92cebd4ad62139b1050c7614559affd620e9a41738fd6a25d4"
FEATURE_SHA = "aeccbe517da452e1132f08c02599418523fb003280b11ff9cda66cfb3aa55a85"
CURRENT_REGISTRY_SHA = "74cb3635c5e211874ee5ad23196fc95bfdfbdb5c6438cc3d060f0b9ff49acfa0"
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


def _flat_policy_tuple(value: Mapping[str, Any], prefix: str) -> tuple[Any, Any, Any]:
    return (value.get(f"{prefix}PolicyId"), value.get(f"{prefix}PolicyVersion"), value.get(f"{prefix}PolicySha256"))


def _approved_p2_contract(commit: Mapping[str, Any]) -> tuple[str, tuple[str, str, str], tuple[str, str, str]]:
    policies = (_policy_tuple(commit.get("assessmentPolicy", {}), True), _policy_tuple(commit.get("decisionPolicy", {}), True))
    if policies == (ASSESSMENT_P2, DECISION_P2):
        return "p2-v1", ASSESSMENT_P2, DECISION_P2
    if policies == (ASSESSMENT_P2_V2, DECISION_P2_V2):
        return "p2-v2", ASSESSMENT_P2_V2, DECISION_P2_V2
    raise ForecastSourceError("Approved Phase 2 policy identity is unknown or mixed.", "forecast_not_eligible")


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


def _verify_assignment_archive(root: Path, authority: Mapping[str, Any]) -> dict[str, Any]:
    assignment_id = authority.get("assignmentId")
    expected_commit_sha = authority.get("assignmentCommitSha256")
    if not isinstance(assignment_id, str) or "/" in assignment_id or "\\" in assignment_id or ".." in assignment_id:
        raise ForecastSourceError("Quick assignment identity is invalid.")
    assignment_root = root / "model-assignments" / assignment_id
    record_path = assignment_root / "artifacts/assignment_record.json"
    commit_path = assignment_root / "metadata/commit.json"
    if not record_path.is_file() or not commit_path.is_file():
        raise ForecastSourceError("Quick assignment archive is missing.")
    record = _json(record_path); commit = _json(commit_path)
    _schema(record, "runtime_model_assignment.schema.json")
    _schema(commit, "runtime_model_assignment_commit.schema.json")
    if commit.get("schemaVersion") != "2.0" or record.get("schemaVersion") != "2.0":
        raise ForecastSourceError("Quick assignment archive contract is not p2-v2.")
    if commit.get("assignmentId") != assignment_id or record.get("assignmentId") != assignment_id:
        raise ForecastSourceError("Quick assignment archive identity mismatch.")
    if sha256_file(commit_path) != expected_commit_sha:
        raise ForecastSourceError("Quick assignment commit hash mismatch.")
    if sha256_file(record_path) != commit.get("assignmentRecordSha256"):
        raise ForecastSourceError("Quick assignment record hash mismatch.")
    expected = (
        assignment_id, "dhaka_south", "assign_selected_model",
        authority.get("modelId"), authority.get("modelFamily"), authority.get("parameterSha256"),
        authority.get("preprocessingIdentity"), authority.get("candidateRegistrySha256"),
        authority.get("featureOrderSha256"),
    )
    actual = (
        record.get("assignmentId"), record.get("deploymentId"), record.get("assignmentAction"),
        record.get("modelId"), record.get("modelFamily"), record.get("parameterSha256"),
        record.get("preprocessingIdentity"), record.get("candidateRegistrySha256"),
        record.get("featureOrderSha256"),
    )
    if actual != expected:
        raise ForecastSourceError("Quick assignment authority does not match its archive.")
    seen = {assignment_id}
    current = record
    while current.get("priorAssignmentId") is not None:
        prior_id = current.get("priorAssignmentId"); prior_sha = current.get("priorAssignmentCommitSha256")
        if not isinstance(prior_id, str) or not isinstance(prior_sha, str) or prior_id in seen or "/" in prior_id or "\\" in prior_id or ".." in prior_id:
            raise ForecastSourceError("Quick prior-assignment linkage is invalid.")
        seen.add(prior_id)
        prior_root = root / "model-assignments" / prior_id
        prior_record_path = prior_root / "artifacts/assignment_record.json"
        prior_commit_path = prior_root / "metadata/commit.json"
        if not prior_record_path.is_file() or not prior_commit_path.is_file():
            raise ForecastSourceError("Quick prior assignment archive is missing.")
        prior_record = _json(prior_record_path); prior_commit = _json(prior_commit_path)
        _schema(prior_record, "runtime_model_assignment.schema.json")
        _schema(prior_commit, "runtime_model_assignment_commit.schema.json")
        if (prior_record.get("schemaVersion"), prior_commit.get("schemaVersion"), prior_record.get("assignmentId"), prior_commit.get("assignmentId")) != ("2.0", "2.0", prior_id, prior_id):
            raise ForecastSourceError("Quick prior assignment contract is invalid.")
        if sha256_file(prior_commit_path) != prior_sha or sha256_file(prior_record_path) != prior_commit.get("assignmentRecordSha256"):
            raise ForecastSourceError("Quick prior assignment hash binding is invalid.")
        current = prior_record
    return record


def _quick_p2(root: Path, run: Path, run_id: str, snapshot: dict[str,str], commit: dict[str,Any]) -> dict[str,Any]:
    _schema(commit, "runtime_commit.schema.json")
    if commit.get("workflowMode") != "quick_forecast" or commit.get("schemaVersion") != "2.1":
        raise ForecastSourceError("Quick p2 source requires the complete 2.1 contract.", "forecast_not_eligible")
    run_record_path = run / "metadata/run.json"
    if not run_record_path.is_file() or commit.get("runRecordSha256") != sha256_file(run_record_path):
        raise ForecastSourceError("Quick p2 run-record binding mismatch.")
    run_record = _json(run_record_path)
    artifacts = {
        "forecast": ("forecast_output.json", "runtime_forecast_output.schema.json"),
        "calibration": ("forecast_calibration.json", "runtime_forecast_calibration.schema.json"),
        "uncertainty": ("forecast_uncertainty.json", "runtime_forecast_uncertainty.schema.json"),
        "dashboard": ("dashboard_summary.json", "runtime_dashboard_summary.schema.json"),
        "card": ("model_card.json", "runtime_model_card.schema.json"),
    }
    values: dict[str, dict[str, Any]] = {}
    _schema(run_record, "runtime_run.schema.json")
    for key, (filename, schema_name) in artifacts.items():
        value = _json(run / "artifacts" / filename); _schema(value, schema_name); values[key] = value
        if value.get("schemaVersion") != "2.1":
            raise ForecastSourceError("Quick p2 source contains a mixed 2.0/2.1 bundle.", "forecast_not_eligible")
    forecast=values["forecast"];calibration=values["calibration"];uncertainty=values["uncertainty"];dashboard=values["dashboard"];card=values["card"]
    if run_record.get("schemaVersion") != "2.1":
        raise ForecastSourceError("Quick p2 run record is not schema 2.1.", "forecast_not_eligible")
    common = (run_id, commit.get("jobId"), commit.get("datasetId"), "dhaka_south")
    for value in (run_record, forecast, calibration, uncertainty, card):
        if (value.get("runId"), value.get("jobId"), value.get("datasetId"), value.get("deploymentId", value.get("deploymentProfileId"))) != common:
            raise ForecastSourceError("Quick p2 run/artifact identity mismatch.")
    if (dashboard.get("run",{}).get("runId"),dashboard.get("run",{}).get("jobId"),dashboard.get("run",{}).get("datasetId"),dashboard.get("run",{}).get("deploymentId")) != common:
        raise ForecastSourceError("Quick p2 dashboard identity mismatch.")
    authority = {
        "assignmentId": run_record.get("assignmentId"),
        "assignmentCommitSha256": run_record.get("assignmentCommitSha256"),
        "assignmentAction": run_record.get("assignmentAction"),
        "authoritySnapshotSha256": run_record.get("authoritySnapshotSha256"),
        "modelId": run_record.get("activeModelId"),
        "modelFamily": run_record.get("modelFamily"),
        "parameterSha256": run_record.get("parameterSha256"),
        "preprocessingIdentity": run_record.get("preprocessingIdentity"),
        "candidateRegistrySha256": run_record.get("candidateRegistrySha256"),
        "featureOrderSha256": run_record.get("featureOrderSha256"),
        "lifecyclePolicyId": run_record.get("lifecyclePolicyId"),
        "lifecyclePolicyVersion": run_record.get("lifecyclePolicyVersion"),
        "lifecyclePolicySha256": run_record.get("lifecyclePolicySha256"),
    }
    authority_rows = [
        authority,
        {"assignmentId":forecast.get("assignmentId"),"assignmentCommitSha256":forecast.get("assignmentCommitSha256"),"assignmentAction":forecast.get("assignmentAction"),"authoritySnapshotSha256":forecast.get("authoritySnapshotSha256"),"modelId":forecast.get("activeModelId"),"modelFamily":forecast.get("modelFamily"),"parameterSha256":forecast.get("parameterHash"),"preprocessingIdentity":forecast.get("preprocessingIdentity"),"candidateRegistrySha256":forecast.get("candidateRegistrySha256"),"featureOrderSha256":forecast.get("trainingDataIdentity",{}).get("featureOrderSha256"),"lifecyclePolicyId":forecast.get("lifecyclePolicyId"),"lifecyclePolicyVersion":forecast.get("lifecyclePolicyVersion"),"lifecyclePolicySha256":forecast.get("lifecyclePolicySha256")},
        {"assignmentId":card.get("assignmentId"),"assignmentCommitSha256":card.get("assignmentCommitSha256"),"assignmentAction":card.get("assignmentAction"),"authoritySnapshotSha256":card.get("authoritySnapshotSha256"),"modelId":card.get("model",{}).get("id"),"modelFamily":card.get("model",{}).get("family"),"parameterSha256":card.get("model",{}).get("parameterHash"),"preprocessingIdentity":card.get("model",{}).get("preprocessingIdentity"),"candidateRegistrySha256":card.get("model",{}).get("candidateRegistrySha256"),"featureOrderSha256":card.get("features",{}).get("orderSha256"),"lifecyclePolicyId":card.get("lifecyclePolicy",{}).get("id"),"lifecyclePolicyVersion":card.get("lifecyclePolicy",{}).get("version"),"lifecyclePolicySha256":card.get("lifecyclePolicy",{}).get("sha256")},
    ]
    if any(row != authority for row in authority_rows) or (authority["assignmentAction"],authority["candidateRegistrySha256"],authority["featureOrderSha256"]) != ("assign_selected_model",CURRENT_REGISTRY_SHA,FEATURE_SHA):
        raise ForecastSourceError("Quick p2 committed authority is inconsistent.")
    if (authority["lifecyclePolicyId"],authority["lifecyclePolicyVersion"],authority["lifecyclePolicySha256"]) != LIFECYCLE_P2_V2:
        raise ForecastSourceError("Quick p2 lifecycle policy mismatch.")
    _verify_assignment_archive(root, authority)
    if _policy_tuple(forecast.get("policy",{})) != QUICK_P2_POLICY or _policy_tuple(card.get("policy",{})) != QUICK_P2_POLICY:
        raise ForecastSourceError("Quick p2 policy mismatch.", "forecast_not_eligible")
    if (run_record.get("policyId"),run_record.get("policyVersion"),run_record.get("policySha256")) != QUICK_P2_POLICY:
        raise ForecastSourceError("Quick p2 run policy mismatch.", "forecast_not_eligible")
    if any(value is not False for value in (forecast.get("deploymentModelAdopted"),card.get("deploymentModelAdopted"))):
        raise ForecastSourceError("Quick p2 forecast cannot adopt the deployment model.")
    presentation=(forecast.get("forecastPresentationMode"),forecast.get("calibrationStatus"),forecast.get("uncertaintyReasonCode"))
    if presentation != (uncertainty.get("forecastPresentationMode"),uncertainty.get("calibrationStatus"),uncertainty.get("uncertaintyReasonCode")) or presentation != (card.get("forecastPresentationMode"),card.get("calibrationStatus"),card.get("uncertaintyReasonCode")):
        raise ForecastSourceError("Quick p2 presentation/calibration contract mismatch.")
    calibration_sha=snapshot.get("artifacts/forecast_calibration.json")
    if card.get("calibration",{}).get("artifactSha256") != calibration_sha:
        raise ForecastSourceError("Quick p2 model-card calibration binding mismatch.")
    if presentation == ("point_and_interval","governed_available",None):
        if any(uncertainty.get(k) is None for k in ("lowerRaw","upperRaw")) or uncertainty.get("residualSourceArtifactSha256") != calibration_sha or calibration.get("calibrationStatus") != "governed_available":
            raise ForecastSourceError("Quick p2 governed calibration evidence is incomplete.")
    elif presentation == ("point_only","unavailable","model_calibration_unavailable"):
        if any(uncertainty.get(k) is not None for k in ("lowerRaw","upperRaw","residualSourceArtifactSha256")) or calibration.get("calibrationStatus") != "unavailable":
            raise ForecastSourceError("Quick p2 unavailable calibration contains interval evidence.")
    else:
        raise ForecastSourceError("Quick p2 presentation/calibration contract is unsupported.")
    history=dashboard.get("history",[]);origin=(history[-1] if history else {}).get("period")
    if forecast.get("target")!="target_cases_next_2w" or forecast.get("horizonWeeks")!=2 or _advance(origin)!=forecast.get("targetPeriod"):
        raise ForecastSourceError("Quick p2 forecast target contract mismatch.", "target_period_mismatch")
    if forecast.get("forecastReported") != int(round(max(0.0,float(forecast.get("forecastRaw"))))):
        raise ForecastSourceError("Quick p2 reported forecast changed.")
    return {"sourceFamily":"quick_forecast_p2","sourceContractVersion":"p2-v2","commit":commit,"runRecord":run_record,"forecast":forecast,"uncertainty":uncertainty,"calibration":calibration,"card":card,"snapshot":snapshot,"origin":origin,"modelId":authority["modelId"],"modelFamily":authority["modelFamily"],"parameterHash":authority["parameterSha256"],"preprocessingIdentity":authority["preprocessingIdentity"],"candidateRegistrySha256":authority["candidateRegistrySha256"],"featureOrderSha256":authority["featureOrderSha256"],"sourcePolicy":{"policyId":QUICK_P2_POLICY[0],"policyVersion":QUICK_P2_POLICY[1],"policySha256":QUICK_P2_POLICY[2]},"assignment":authority,"lifecycle":{}}


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
    common_identity=(run_id,commit.get("datasetId"),"dhaka_south","approved_assessment_forecast")
    for value in (forecast,card):
        if (value.get("runId"),value.get("datasetId"),value.get("deploymentId"),value.get("workflowMode"))!=common_identity:
            raise ForecastSourceError("Approved artifact identity mismatch.")
    if (uncertainty.get("runId"),uncertainty.get("datasetId"),uncertainty.get("deploymentId"))!=common_identity[:3]:
        raise ForecastSourceError("Approved uncertainty identity mismatch.")
    ids=(commit.get("assessmentId"),commit.get("decisionId"),commit.get("authorizationId"))
    if ids != (forecast.get("assessmentId"),forecast.get("decisionId"),forecast.get("authorizationId")) or ids != (card.get("assessment",{}).get("id"),card.get("decision",{}).get("id"),card.get("authorization",{}).get("id")): raise ForecastSourceError("Approved lifecycle identity mismatch.")
    if ids[:2] != (uncertainty.get("assessmentId"),uncertainty.get("decisionId")):
        raise ForecastSourceError("Approved uncertainty lifecycle mismatch.")
    assessment_id,decision_id,authorization_id=ids
    assessment_commit_path=root/"assessments"/assessment_id/"metadata/commit.json";decision_path=root/"decisions"/decision_id/"decision.json";decision_commit_path=root/"decisions"/decision_id/"commit.json";authorization_path=root/"authorizations"/authorization_id/"authorization.json";authorization_commit_path=root/"authorizations"/authorization_id/"commit.json"
    for path in (assessment_commit_path,decision_path,decision_commit_path,authorization_path,authorization_commit_path):
        if not path.is_file(): raise ForecastSourceError("Approved lifecycle evidence is missing.")
    assessment_commit=_json(assessment_commit_path);decision=_json(decision_path);decision_commit=_json(decision_commit_path)
    authorization=_json(authorization_path);authorization_commit=_json(authorization_commit_path)
    _schema(assessment_commit,"runtime_assessment_commit.schema.json");_schema(decision,"runtime_decision.schema.json")
    _schema(decision_commit,"runtime_decision_commit.schema.json");_schema(authorization,"runtime_forecast_authorization.schema.json")
    _schema(authorization_commit,"runtime_forecast_authorization_commit.schema.json")
    lifecycle_hashes={"assessmentCommitSha256":sha256_file(assessment_commit_path),"decisionCommitSha256":sha256_file(decision_commit_path),"authorizationCommitSha256":sha256_file(authorization_commit_path)}
    if lifecycle_hashes["assessmentCommitSha256"]!=commit.get("assessmentCommitSha256") or lifecycle_hashes["decisionCommitSha256"]!=commit.get("decisionCommitSha256"): raise ForecastSourceError("Approved lifecycle commit binding mismatch.")
    if authorization.get("assessmentCommitSha256")!=lifecycle_hashes["assessmentCommitSha256"] or authorization.get("decisionCommitSha256")!=lifecycle_hashes["decisionCommitSha256"]: raise ForecastSourceError("Authorization lifecycle binding mismatch.")
    if (decision_commit.get("decisionId"),decision_commit.get("assessmentId"),decision_commit.get("decisionSha256"),decision_commit.get("assessmentCommitSha256"))!=(decision_id,assessment_id,sha256_file(decision_path),lifecycle_hashes["assessmentCommitSha256"]):
        raise ForecastSourceError("Decision commit content mismatch.")
    if (authorization_commit.get("authorizationId"),authorization_commit.get("decisionId"),authorization_commit.get("authorizationSha256"),authorization_commit.get("decisionCommitSha256"))!=(authorization_id,decision_id,sha256_file(authorization_path),lifecycle_hashes["decisionCommitSha256"]):
        raise ForecastSourceError("Authorization commit content mismatch.")
    model_id=commit.get("selectedModelId");family=card.get("model",{}).get("family");parameter=commit.get("selectedModelParameterSha256")
    if parameter!=forecast.get("selectedModelParameterSha256") or parameter!=card.get("model",{}).get("parameterHash") or authorization.get("selectedModelId")!=model_id or authorization.get("selectedModelParameterSha256")!=parameter:
        raise ForecastSourceError("Approved selected-model binding mismatch.")
    if forecast.get("target")!="target_cases_next_2w" or forecast.get("horizonWeeks")!=2 or card.get("target")!="target_cases_next_2w" or card.get("horizonWeeks")!=2: raise ForecastSourceError("Approved target contract mismatch.","forecast_not_eligible")
    training=forecast.get("trainingDataIdentity",{});dashboard=_json(run/"artifacts/dashboard_summary.json");history=dashboard.get("history",[]);origin=(history[-1] if history else {}).get("period")
    if _advance(origin)!=forecast.get("targetPeriod"): raise ForecastSourceError("Approved target period mismatch.","target_period_mismatch")
    if forecast.get("forecastReported")!=int(round(max(0.0,float(forecast.get("forecastRaw"))))): raise ForecastSourceError("Approved reported forecast changed.")
    if version=="1.0":
        contract_version="p1";family_name="approved_forecast_p1"; assessment_policy=ASSESSMENT_P1;decision_policy=DECISION_P1
        registry_sha=REGISTRY_SHA
        assessment_summary=_json(root/"assessments"/assessment_id/"artifacts/assessment_summary.json")
        rolling=_json(root/"assessments"/assessment_id/"artifacts/rolling_validation.json");folds=rolling.get("folds",[])
        planned=assessment_summary.get("foldPolicy",{}).get("plannedFoldCount");selected_period={"start":folds[0]["targetPeriod"],"end":folds[-1]["targetPeriod"]} if folds else None
        labelled=assessment_summary.get("labelledRows")
        if (labelled,planned,training.get("trainingRowCount"),card.get("assessment",{}).get("foldCount"))!=(173,68,173,68): raise ForecastSourceError("Historical approved history changed.")
        if (decision.get("assessmentPolicyId"),decision.get("assessmentPolicyVersion"),decision.get("assessmentPolicySha256"))!=assessment_policy or (decision.get("decisionPolicyId"),decision.get("decisionPolicyVersion"),decision.get("decisionPolicySha256"))!=decision_policy: raise ForecastSourceError("Historical approved policy mismatch.")
        fold_plan=assessment_commit.get("foldPlanSha256");successful=68;failed=0;matrix=training.get("featureMatrixSha256")
    else:
        contract_version,assessment_policy,decision_policy=_approved_p2_contract(commit)
        family_name="approved_forecast_p2"
        governance=forecast.get("governanceEvidence",{});labelled=governance.get("assessmentLabelledRows");planned=governance.get("assessmentPlannedFoldCount");selected_period=governance.get("selectedEvaluationPeriod");fold_plan=governance.get("foldPlanSha256");successful=governance.get("successfulFolds");failed=governance.get("failedFolds");matrix=training.get("featureMatrixSha256")
        if not isinstance(labelled,int) or labelled<157 or training.get("trainingRowCount")!=labelled or not isinstance(planned,int) or not 52<=planned<=68 or successful!=planned or failed!=0: raise ForecastSourceError("Phase 2 dynamic evidence mismatch.")
        if _policy_tuple(governance.get("assessmentPolicy",{}),True)!=assessment_policy or _policy_tuple(governance.get("decisionPolicy",{}),True)!=decision_policy: raise ForecastSourceError("Phase 2 policy binding mismatch.")
        if _flat_policy_tuple(decision,"assessment")!=assessment_policy or _flat_policy_tuple(decision,"decision")!=decision_policy or _flat_policy_tuple(authorization,"assessment")!=assessment_policy or _flat_policy_tuple(authorization,"decision")!=decision_policy:
            raise ForecastSourceError("Phase 2 lifecycle policy mismatch.")
        if _flat_policy_tuple(decision_commit,"assessment")!=assessment_policy or _flat_policy_tuple(decision_commit,"decision")!=decision_policy:
            raise ForecastSourceError("Phase 2 decision commit policy mismatch.")
        if (_policy_tuple(card.get("assessment",{}).get("policy",{}),True),_policy_tuple(card.get("decision",{}).get("policy",{}),True))!=(assessment_policy,decision_policy):
            raise ForecastSourceError("Phase 2 model-card policy mismatch.")
        registry=None;registry_sha=REGISTRY_SHA
        if contract_version=="p2-v2":
            registry,registry_sha=load_and_validate_candidate_registry()
        expected={**lifecycle_hashes,"candidateRegistrySha256":registry_sha,"foldPlanSha256":fold_plan}
        if any(governance.get(k)!=v for k,v in expected.items()) or commit.get("authorizationCommitSha256")!=lifecycle_hashes["authorizationCommitSha256"]: raise ForecastSourceError("Phase 2 governance hash mismatch.")
        if commit.get("technicalWinnerModelId")!=forecast.get("technicalWinnerModelId") or commit.get("technicalWinnerParameterSha256")!=forecast.get("technicalWinnerParameterSha256"): raise ForecastSourceError("Technical-winner evidence mismatch.")
    if contract_version=="p2-v2":
        assert registry is not None
        candidates={candidate["model_id"]:candidate for candidate in registry["candidates"] if candidate.get("selectable") is True and candidate.get("selection_role")=="learned_selectable"}
        candidate=candidates.get(model_id)
        if candidate is None:
            raise ForecastSourceError("Approved selected model is not supported by the current candidate registry.","forecast_not_eligible")
        preprocessing=candidate["preprocessing_identity"]
        model_values=(commit.get("selectedModelId"),forecast.get("selectedModelId"),card.get("model",{}).get("id"),decision.get("selectedModelId"),authorization.get("selectedModelId"),uncertainty.get("selectedModelId"))
        registry_values=(commit.get("candidateRegistrySha256"),forecast.get("candidateRegistrySha256"),forecast.get("governanceEvidence",{}).get("candidateRegistrySha256"),card.get("model",{}).get("candidateRegistrySha256"),decision.get("candidateRegistrySha256"),authorization.get("candidateRegistrySha256"),assessment_commit.get("candidateRegistrySha256"),uncertainty.get("candidateRegistrySha256"))
        feature_values=(commit.get("featureOrderSha256"),forecast.get("featureOrderSha256"),forecast.get("governanceEvidence",{}).get("featureOrderSha256"),training.get("featureOrderSha256"),card.get("features",{}).get("orderSha256"),decision.get("featureOrderSha256"),authorization.get("featureOrderSha256"),uncertainty.get("featureOrderSha256"))
        family_values=(family,commit.get("selectedModelFamily"),forecast.get("selectedModelFamily"),forecast.get("governanceEvidence",{}).get("selectedModelFamily"),decision.get("selectedModelFamily"),authorization.get("selectedModelFamily"),uncertainty.get("modelFamily"))
        parameter_values=(parameter,candidate.get("parameters_sha256"),forecast.get("selectedModelParameterSha256"),card.get("model",{}).get("parameterHash"),decision.get("selectedModelParameterSha256"),authorization.get("selectedModelParameterSha256"),uncertainty.get("selectedModelParameterSha256"))
        preprocessing_values=(preprocessing,commit.get("selectedModelPreprocessingIdentity"),forecast.get("selectedModelPreprocessingIdentity"),forecast.get("governanceEvidence",{}).get("selectedModelPreprocessingIdentity"),training.get("preprocessingIdentity"),card.get("model",{}).get("preprocessingIdentity"),card.get("training",{}).get("preprocessingIdentity"),decision.get("selectedModelPreprocessingIdentity"),authorization.get("selectedModelPreprocessingIdentity"),uncertainty.get("preprocessingIdentity"))
        fold_plan_values=(commit.get("foldPlanSha256"),forecast.get("foldPlanSha256"),forecast.get("governanceEvidence",{}).get("foldPlanSha256"),decision.get("foldPlanSha256"),authorization.get("foldPlanSha256"),assessment_commit.get("foldPlanSha256"),uncertainty.get("foldPlanSha256"))
        if any(value!=model_id for value in model_values):
            raise ForecastSourceError("Approved current model identity mismatch.")
        if any(value!=registry_sha for value in registry_values) or any(value!=FEATURE_SHA for value in feature_values):
            raise ForecastSourceError("Approved current registry or feature binding mismatch.")
        if any(value!=candidate["model_family"] for value in family_values):
            raise ForecastSourceError("Approved current model-family binding mismatch.")
        if any(value!=candidate["parameters_sha256"] for value in parameter_values):
            raise ForecastSourceError("Approved current parameter binding mismatch.")
        if any(value!=preprocessing for value in preprocessing_values):
            raise ForecastSourceError("Approved current preprocessing binding mismatch.")
        if any(value!=fold_plan for value in fold_plan_values):
            raise ForecastSourceError("Approved current fold-plan binding mismatch.")
        technical_winner=(commit.get("technicalWinnerModelId"),commit.get("technicalWinnerParameterSha256"))
        if any(value!=technical_winner for value in ((forecast.get("technicalWinnerModelId"),forecast.get("technicalWinnerParameterSha256")),(decision.get("technicalWinnerModelId"),decision.get("technicalWinnerParameterSha256")),(card.get("model",{}).get("technicalWinnerId"),card.get("model",{}).get("technicalWinnerParameterHash")))) or authorization.get("technicalWinnerModelId")!=technical_winner[0]:
            raise ForecastSourceError("Approved current technical-winner binding mismatch.")
        if _flat_policy_tuple(authorization,"decision")!=_policy_tuple(authorization,True):
            raise ForecastSourceError("Approved authorization policy identity mismatch.")
        if any(value is not False for value in (commit.get("deploymentModelAdopted"),forecast.get("deploymentModelAdopted"),card.get("deploymentModelAdopted"),decision.get("deploymentModelAdopted"),authorization.get("deploymentModelAdopted"))):
            raise ForecastSourceError("Approved one-run forecast cannot adopt a deployment model.")
        uncertainty_contract=(uncertainty.get("forecastPresentationMode"),uncertainty.get("calibrationStatus"),uncertainty.get("uncertaintyReasonCode"),uncertainty.get("calibrationProvenance"))
        if uncertainty_contract!=("point_only","pending","model_specific_calibration_pending",None) or any(uncertainty.get(k) is not None for k in ("lowerRaw","upperRaw")):
            raise ForecastSourceError("Approved p2-v2 uncertainty contract mismatch.")
    else:
        if MODEL_FAMILIES.get(model_id)!=family:
            raise ForecastSourceError("Approved selected-model binding mismatch.")
        if card.get("model",{}).get("candidateRegistrySha256")!=REGISTRY_SHA or card.get("features",{}).get("orderSha256")!=FEATURE_SHA:
            raise ForecastSourceError("Approved registry or feature binding mismatch.")
        if uncertainty.get("uncertaintyStatus")!="pending_selected_model_calibration" or any(uncertainty.get(k) is not None for k in ("lowerRaw","upperRaw")):
            raise ForecastSourceError("Approved uncertainty evidence mismatch.")
    lifecycle={"assessmentId":assessment_id,"assessmentCommitSha256":lifecycle_hashes["assessmentCommitSha256"],"assessmentPolicy":{"policyId":assessment_policy[0],"policyVersion":assessment_policy[1],"policySha256":assessment_policy[2]},"decisionId":decision_id,"decisionCommitSha256":lifecycle_hashes["decisionCommitSha256"],"decisionPolicy":{"policyId":decision_policy[0],"policyVersion":decision_policy[1],"policySha256":decision_policy[2]},"authorizationId":authorization_id,"authorizationCommitSha256":lifecycle_hashes["authorizationCommitSha256"],"technicalWinnerModelId":commit.get("technicalWinnerModelId",forecast.get("technicalWinnerModelId")),"technicalWinnerParameterSha256":commit.get("technicalWinnerParameterSha256",decision.get("technicalWinnerParameterSha256")),"trainingRowCount":training.get("trainingRowCount"),"trainingPeriod":training.get("trainingPeriod"),"plannedFoldCount":planned,"successfulFolds":successful,"failedFolds":failed,"selectedEvaluationPeriod":selected_period,"foldPlanSha256":fold_plan,"featureMatrixSha256":matrix}
    return {"sourceFamily":family_name,"sourceContractVersion":contract_version,"commit":commit,"forecast":forecast,"uncertainty":uncertainty,"calibration":None,"card":card,"snapshot":snapshot,"origin":origin,"modelId":model_id,"modelFamily":family,"parameterHash":parameter,"candidateRegistrySha256":registry_sha,"featureOrderSha256":FEATURE_SHA,"sourcePolicy":{"policyId":decision_policy[0],"policyVersion":decision_policy[1],"policySha256":decision_policy[2]},"lifecycle":lifecycle}


def verify_forecast_source(root: Path, run_id: str, expected_commit: str, allowed_families: set[str] | None = None) -> dict[str,Any]:
    run,snapshot,commit=_snapshot_and_commit(root,run_id,expected_commit)
    workflow=commit.get("workflowMode")
    bundle=(_quick_p2(root,run,run_id,snapshot,commit) if commit.get("schemaVersion")=="2.1" else _quick(root,run,run_id,snapshot,commit)) if workflow=="quick_forecast" else _approved(root,run,run_id,snapshot,commit) if workflow=="approved_assessment_forecast" else None
    if bundle is None or (allowed_families is not None and bundle["sourceFamily"] not in allowed_families): raise ForecastSourceError("Forecast source family is not governed.","forecast_not_eligible")
    return bundle
