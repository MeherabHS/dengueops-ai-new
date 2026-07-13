"""Governed P1.2A candidate comparison on authoritative P1.1 folds."""
from __future__ import annotations

import hashlib, json, math, os, tempfile, time, warnings
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import sklearn
from jsonschema import Draft202012Validator
from sklearn.exceptions import ConvergenceWarning

from deployment_profiles import load_deployment_profile
from feature_engineering import FEATURE_COLUMNS
from formula_registry import build_formula_metadata, current_deployment_gate
from model_factory import (build_candidate_estimator, canonical_sha256,
                           file_sha256, load_and_validate_candidate_registry)
from validation_backtest import (GBR_PARAMS, TARGET_COL, generate_rolling_fold_descriptors,
                                 load_feature_matrix, model_parameters_sha256)

ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = ROOT / "config" / "candidate_models.json"
COMPARISON_SCHEMA_PATH = ROOT / "config" / "candidate_model_comparison.schema.json"
ROLLING_PATH = ROOT / "data" / "rolling_validation.json"
OUTPUT_PATH = ROOT / "data" / "candidate_model_comparison.json"
FORBIDDEN_TUNING_FIELDS = {"parameter_grid", "search_space", "cross_validation_selector", "trial_count", "optimization_objective", "tuning_method"}
REUSED = {"previous_week_naive": "naive", "moving_average_4w": "moving_average", "gradient_boosting": "gradient_boosting"}
FORMULA_IDS = ("VALIDATION.ROLLING_ORIGIN", "MODEL.CANDIDATE_COMPARISON")

def _sha(value: Any) -> str:
    return canonical_sha256(value)

def load_candidate_registry() -> dict:
    value, _ = load_and_validate_candidate_registry(REGISTRY_PATH)
    errors = []
    gbr = next((c for c in value.get("candidates", []) if c.get("model_id") == "gradient_boosting"), {})
    if gbr.get("parameters") != GBR_PARAMS: errors.append("Candidate GBR configuration differs from the governed P1.1 configuration.")
    if errors: raise ValueError(" ".join(dict.fromkeys(errors)))
    return value

def _estimator(model_id: str, parameters: dict):
    """Backward-compatible private adapter; construction remains factory-authoritative."""
    registry = load_candidate_registry()
    candidate = next((item for item in registry["candidates"] if item["model_id"] == model_id), None)
    if candidate is None or candidate["parameters"] != parameters:
        raise ValueError(f"Parameters for {model_id} do not match the governed registry.")
    return build_candidate_estimator(model_id, registry)

def _record(fold_id: str, actual: float, raw: float, runtime: float, warning_messages: list[str], *, seasonal_period=None, seasonal_row=None) -> dict:
    if not math.isfinite(raw): raise ValueError("non_finite_prediction")
    published = max(0.0, raw); signed = published - actual
    result = {"fold_id":fold_id,"actual":actual,"raw_prediction":raw,"published_prediction":published,"clipping_applied":raw < 0,
        "signed_error":signed,"absolute_error":abs(signed),"squared_error":signed*signed,
        "percentage_error":abs(signed)/actual*100 if actual>0 else None,"percentage_exclusion_reason":None if actual>0 else "actual_is_zero",
        "error_direction":"under_prediction" if signed<0 else "over_prediction" if signed>0 else "exact",
        "fold_status":"warning" if warning_messages else "success","warnings":warning_messages,"failure_reason":None,"runtime_seconds":runtime}
    if seasonal_period is not None: result.update(seasonal_source_period=seasonal_period, seasonal_source_row_id=seasonal_row)
    return result

def _failed(fold_id: str, actual: float, reason: str, runtime: float, warning_messages: list[str]) -> dict:
    return {"fold_id":fold_id,"actual":actual,"raw_prediction":None,"published_prediction":None,"clipping_applied":False,
        "signed_error":None,"absolute_error":None,"squared_error":None,"percentage_error":None,"percentage_exclusion_reason":"fold_failed",
        "error_direction":None,"fold_status":"failed","warnings":warning_messages,"failure_reason":reason,"runtime_seconds":runtime}

def _aggregate(records: list[dict]) -> dict:
    successful = [record for record in records if record["fold_status"] != "failed"]
    failed = len(records)-len(successful)
    if not successful:
        return {"fold_count":len(records),"successful_folds":0,"failed_folds":failed,"mae":None,"rmse":None,"wape":None,"mape":None,
            "median_absolute_error":None,"maximum_absolute_error":None,"minimum_absolute_error":None,"absolute_error_standard_deviation":None,
            "q1":None,"q3":None,"iqr":None,"negative_raw_prediction_count":0,"clipping_count":0,"convergence_warning_count":0,
            "runtime_seconds":sum(r["runtime_seconds"] for r in records)}
    absolute=np.array([r["absolute_error"] for r in successful]); squared=np.array([r["squared_error"] for r in successful]); actual=sum(r["actual"] for r in successful)
    percentages=[r["percentage_error"] for r in successful if r["percentage_error"] is not None]; q1,q3=np.percentile(absolute,[25,75])
    return {"fold_count":len(records),"successful_folds":len(successful),"failed_folds":failed,"mae":float(absolute.mean()),"rmse":float(np.sqrt(squared.mean())),
        "wape":float(100*absolute.sum()/actual) if actual else None,"mape":float(np.mean(percentages)) if percentages else None,
        "median_absolute_error":float(np.median(absolute)),"maximum_absolute_error":float(absolute.max()),"minimum_absolute_error":float(absolute.min()),
        "absolute_error_standard_deviation":float(np.std(absolute,ddof=0)),"q1":float(q1),"q3":float(q3),"iqr":float(q3-q1),
        "negative_raw_prediction_count":sum(r["raw_prediction"] is not None and r["raw_prediction"]<0 for r in records),
        "clipping_count":sum(r["clipping_applied"] for r in records),"convergence_warning_count":sum(any("ConvergenceWarning" in w for w in r["warnings"]) for r in records),
        "runtime_seconds":sum(r["runtime_seconds"] for r in records)}

def select_comparison_winner(metrics: dict, candidates: list[dict], tolerance: float=1e-9) -> tuple[str, list[str], list[str]]:
    eligible=[c for c in candidates if metrics[c["model_id"]]["successful_folds"]==68 and metrics[c["model_id"]]["failed_folds"]==0 and metrics[c["model_id"]]["mae"] is not None]
    if not eligible: raise ValueError("No candidate completed all 68 folds.")
    steps=[]; remaining=eligible
    for field in ("mae","rmse","wape","median_absolute_error","maximum_absolute_error"):
        best=min(metrics[c["model_id"]][field] for c in remaining)
        remaining=[c for c in remaining if abs(metrics[c["model_id"]][field]-best)<=tolerance]
        steps.append(f"{field}: retained {','.join(c['model_id'] for c in remaining)}")
        if len(remaining)==1: break
    if len(remaining)>1:
        rank=min(c["selection_complexity_rank"] for c in remaining); remaining=[c for c in remaining if c["selection_complexity_rank"]==rank]; steps.append("selection_complexity_rank")
    if len(remaining)>1: remaining=sorted(remaining,key=lambda c:c["model_id"]); steps.append("lexicographic_model_id")
    return remaining[0]["model_id"], steps, [c["model_id"] for c in eligible]

def validate_comparison_artifact(artifact: dict, *, expected_registry_sha256=None, expected_rolling_sha256=None, expected_rolling=None, expected_model_card=None, expected_artifact_sha256=None) -> None:
    schema=json.loads(COMPARISON_SCHEMA_PATH.read_text(encoding="utf-8")); errors=[e.message for e in Draft202012Validator(schema).iter_errors(artifact)]
    if expected_registry_sha256 and artifact.get("candidate_registry_sha256") != expected_registry_sha256: errors.append("Candidate registry hash mismatch.")
    if expected_rolling_sha256 and artifact.get("rolling_validation_artifact_sha256") != expected_rolling_sha256: errors.append("Rolling artifact hash mismatch.")
    if expected_rolling is not None:
        expected_refs=[{"fold_id":f["fold_id"],"training_matrix_sha256":f["training_matrix_sha256"],"validation_matrix_sha256":f["validation_matrix_sha256"]} for f in expected_rolling["folds"]]
        if artifact.get("fold_references") != expected_refs: errors.append("Candidate comparison fold references differ from rolling validation.")
    if expected_model_card is not None and expected_model_card.get("candidate_model_comparison_artifact_sha256") != expected_artifact_sha256: errors.append("Model-card comparison hash mismatch.")
    if errors: raise ValueError(" ".join(dict.fromkeys(errors)))

def build_candidate_comparison(df: pd.DataFrame, rolling: dict, rolling_sha256: str, registry: dict, registry_sha256: str) -> dict:
    descriptors=generate_rolling_fold_descriptors(df); rolling_folds=rolling["folds"]
    if len(rolling_folds)!=68 or rolling["provenance"].get("run_id") != df.iloc[0]["input_run_id"]: raise ValueError("Rolling artifact provenance or fold count mismatch.")
    predictions={c["model_id"]:[] for c in registry["candidates"]}; case_lookup={(int(r.epi_year),int(r.epi_week)): (float(r.cases),f"{int(r.epi_year)}-W{int(r.epi_week):02d}") for _,r in df.iterrows()}
    for descriptor, rolling_fold in zip(descriptors, rolling_folds):
        for key in ("fold_id","training_matrix_sha256","validation_matrix_sha256","feature_order_sha256"):
            if rolling_fold[key] != descriptor[key]: raise ValueError(f"Rolling fold {key} mismatch.")
        actual=descriptor["actual_target"]
        for model_id, rolling_id in REUSED.items():
            source=rolling_fold["predictions"][rolling_id]; predictions[model_id].append(_record(descriptor["fold_id"],actual,float(source["raw_prediction"]),0.0,[]))
        validation=df.iloc[descriptor["validation_index"]]; target_date=date.fromisocalendar(int(validation.epi_year),int(validation.epi_week),1)+timedelta(weeks=2-52); sy,sw,_=target_date.isocalendar(); started=time.perf_counter()
        if (sy,sw) not in case_lookup: predictions["seasonal_naive_52w"].append(_failed(descriptor["fold_id"],actual,"seasonal_source_missing",time.perf_counter()-started,[]))
        else:
            raw,row_id=case_lookup[(sy,sw)]; predictions["seasonal_naive_52w"].append(_record(descriptor["fold_id"],actual,raw,time.perf_counter()-started,[],seasonal_period=f"{sy}-W{sw:02d}",seasonal_row=row_id))
        train=df.iloc[descriptor["train_start_index"]:descriptor["train_end_exclusive"]]; x_train=train[FEATURE_COLUMNS].to_numpy(); y_train=train[TARGET_COL].to_numpy(); x_valid=validation[FEATURE_COLUMNS].to_numpy(float).reshape(1,-1)
        for model_id in ("ridge_regression","poisson_regression","random_forest"):
            candidate=next(c for c in registry["candidates"] if c["model_id"]==model_id); started=time.perf_counter(); warning_messages=[]
            try:
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always"); model=build_candidate_estimator(model_id,registry); model.fit(x_train,y_train); raw=float(model.predict(x_valid)[0])
                warning_messages=[f"{w.category.__name__}: {w.message}" for w in caught]
                unresolved=[w for w in caught if issubclass(w.category,ConvergenceWarning)]
                if unresolved: raise ValueError("unresolved_convergence_warning")
                if model_id=="poisson_regression" and raw<0: raise ValueError("invalid_negative_poisson_output")
                predictions[model_id].append(_record(descriptor["fold_id"],actual,raw,time.perf_counter()-started,warning_messages))
            except Exception as exc: predictions[model_id].append(_failed(descriptor["fold_id"],actual,str(exc),time.perf_counter()-started,warning_messages))
    metrics={model_id:_aggregate(records) for model_id,records in predictions.items()}; winner,steps,eligible=select_comparison_winner(metrics,registry["candidates"])
    selected_errors={r["fold_id"]:r["absolute_error"] for r in predictions[winner]}; paired={}; wtl={}
    for model_id,records in predictions.items():
        diffs=np.array([r["absolute_error"]-selected_errors[r["fold_id"]] for r in records if r["fold_status"]!="failed"]); q1,q3=np.percentile(diffs,[25,75])
        paired[model_id]={"mean":float(diffs.mean()),"median":float(np.median(diffs)),"minimum":float(diffs.min()),"maximum":float(diffs.max()),"q1":float(q1),"q3":float(q3),"iqr":float(q3-q1),
            "better_fold_count":int((diffs < -1e-9).sum()),"tied_fold_count":int((np.abs(diffs)<=1e-9).sum()),"worse_fold_count":int((diffs>1e-9).sum())}
        wtl[model_id]={k:paired[model_id][k] for k in ("better_fold_count","tied_fold_count","worse_fold_count")}
    profile=load_deployment_profile(rolling["deployment_profile_id"]); formula=build_formula_metadata(FORMULA_IDS,current_deployment_gate()); selected=next(c for c in registry["candidates"] if c["model_id"]==winner)
    artifact={"comparison_schema_version":"1.0","comparison_version":"p1.2a-v1","availability_status":"generated","validation_method":rolling["validation_method"],"fold_count":68,
        "rolling_validation_artifact_path":"data/rolling_validation.json","rolling_validation_artifact_sha256":rolling_sha256,"rolling_validation_version":rolling["validation_version"],
        "fold_reference_policy":"exact_fold_ids_and_matrix_hashes_reference_p1.1","fold_references":[{"fold_id":f["fold_id"],"training_matrix_sha256":f["training_matrix_sha256"],"validation_matrix_sha256":f["validation_matrix_sha256"]} for f in rolling_folds],"candidate_registry_version":registry["candidate_registry_version"],"candidate_registry_sha256":registry_sha256,
        "selection_policy_version":"p1.2a-v1","selection_policy":{"rule":"lowest_MAE_among_68_fold_eligible_candidates","tie_sequence":["rmse","wape","median_absolute_error","maximum_absolute_error","selection_complexity_rank","model_id"],"failed_candidate_ineligible":True,"weighted_score":False},
        "primary_metric":"MAE","secondary_metrics":["RMSE","WAPE","median_absolute_error","maximum_absolute_error"],"tie_tolerance":1e-9,"tie_resolution_steps":steps,"candidates":registry["candidates"],
        "per_fold_predictions":predictions,"aggregate_metrics":metrics,"paired_error_differences":paired,"wins_ties_losses":wtl,
        "model_failures":{k:[r for r in v if r["fold_status"]=="failed"] for k,v in predictions.items()},"comparison_selected_model":winner,
        "comparison_selected_model_reason":f"{winner} had the lowest eligible rolling-origin MAE under the predeclared p1.2a-v1 rule.","selected_model_rank":1,
        "selected_model_parameters_sha256":selected["parameters_sha256"],"selection_status":"comparison_complete_not_adopted","selection_eligibility":{c["model_id"]:c["model_id"] in eligible for c in registry["candidates"]},
        "adoption_status":"not_adopted_p1.2a","current_forecast_model":"gradient_boosting","limitations":["Candidate models were compared on identical leakage-controlled rolling-origin folds using deterministic synthetic benchmark data. The selected model is a technical demonstration choice and does not establish real-world Dhaka superiority.","Rolling folds and targets are temporally dependent; paired summaries are descriptive and no significance claims are made.","The comparison winner is not adopted in P1.2A; P0.4 explainability and legacy uncertainty remain bound to Gradient Boosting."],
        "deployment_gate":profile["deployment_gate"],"data_mode":profile["data_mode"],"observed_data_mode":profile["observed_data_mode"],**formula,
        "deployment_profile_id":rolling["deployment_profile_id"],"deployment_profile_sha256":rolling["deployment_profile_sha256"],"evidence_registry_sha256":rolling["evidence_registry_sha256"],
        "model_card_id":rolling["model_card_id"],"model_card_version":rolling["model_card_version"],"provenance":rolling["provenance"],"generated_at":datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    validate_comparison_artifact(artifact,expected_registry_sha256=registry_sha256,expected_rolling_sha256=rolling_sha256,expected_rolling=rolling)
    return artifact

def write_comparison_atomic(artifact: dict, path: Path=OUTPUT_PATH) -> str:
    # tie_resolution_steps is optional in schema only after it is declared there.
    validate_comparison_artifact(artifact); payload=json.dumps(artifact,indent=2,ensure_ascii=False,allow_nan=False).encode(); path.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix=f".{path.name}.",suffix=".tmp",dir=path.parent)
    try:
        with os.fdopen(fd,"wb") as handle: handle.write(payload); handle.flush(); os.fsync(handle.fileno())
        os.replace(temp,path)
    finally:
        if os.path.exists(temp): os.unlink(temp)
    return hashlib.sha256(payload).hexdigest()

def main() -> None:
    registry=load_candidate_registry(); rolling_bytes=ROLLING_PATH.read_bytes(); rolling=json.loads(rolling_bytes); artifact=build_candidate_comparison(load_feature_matrix(),rolling,hashlib.sha256(rolling_bytes).hexdigest(),registry,file_sha256(REGISTRY_PATH)); write_comparison_atomic(artifact); print(f"Candidate comparison: {artifact['comparison_selected_model']} ({OUTPUT_PATH})")

if __name__ == "__main__": main()
