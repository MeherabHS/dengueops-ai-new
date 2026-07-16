"""Governed P1.4G forecast-outcome policy loading and identity validation."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
from typing import Any, Mapping
from jsonschema import Draft202012Validator, FormatChecker
from runtime_context import ROOT
from runtime_policy import load_and_validate_quick_forecast_policy

SCHEMA=ROOT/"config/runtime_forecast_outcome_policy.schema.json"
class ForecastOutcomePolicyError(ValueError): pass

def canonical_policy_sha256(value: Mapping[str, Any]) -> str:
    content=dict(value); content.pop("policy_sha256",None)
    return hashlib.sha256(json.dumps(content,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()).hexdigest()

def load_and_validate_forecast_outcome_policy(deployment_id: str) -> tuple[dict[str,Any],str]:
    if deployment_id!="dhaka_south": raise ForecastOutcomePolicyError("Unsupported outcome-monitoring deployment.")
    path=ROOT/"config/deployments"/deployment_id/"forecast_outcome_policy.json"
    policy=json.loads(path.read_text(encoding="utf-8")); schema=json.loads(SCHEMA.read_text(encoding="utf-8"))
    errors=[e.message for e in Draft202012Validator(schema,format_checker=FormatChecker()).iter_errors(policy)]
    digest=canonical_policy_sha256(policy)
    if policy.get("policy_sha256")!=digest: errors.append("Outcome policy hash mismatch.")
    profile=json.loads((ROOT/"config/deployments"/deployment_id/"profile.json").read_text(encoding="utf-8"))
    quick,quick_digest=load_and_validate_quick_forecast_policy(deployment_id)
    registry_bytes=(ROOT/"config/candidate_models.json").read_bytes(); formulas_bytes=(ROOT/"config/formulas.json").read_bytes();formulas=json.loads(formulas_bytes)
    scope=policy.get("forecast_scope",{}); formula=policy.get("formula_registry",{})
    checks=[(policy.get("geography"),profile.get("geography"),"geography"),(policy.get("timezone"),profile.get("timezone"),"timezone"),
      (scope.get("required_policy_id"),quick.get("policy_id"),"Quick Forecast policy ID"),(scope.get("required_policy_version"),quick.get("policy_version"),"Quick Forecast policy version"),(scope.get("required_policy_sha256"),quick_digest,"Quick Forecast policy"),
      (scope.get("model_parameters_sha256"),profile.get("model",{}).get("model_parameters_sha256"),"model parameters"),
      (scope.get("candidate_registry_sha256"),hashlib.sha256(registry_bytes).hexdigest(),"candidate registry"),
      (scope.get("feature_order_sha256"),profile.get("forecast_uncertainty",{}).get("feature_order_sha256"),"feature order"),
      (formula.get("version"),profile.get("formula_registry_version"),"formula version"),
      (formula.get("sha256"),hashlib.sha256(formulas_bytes).hexdigest(),"formula registry")]
    errors.extend(f"Outcome policy {label} binding mismatch." for actual,expected,label in checks if actual!=expected)
    formula_ids={item.get("formula_id") for item in formulas.get("formulas",[]) if isinstance(item,dict)}
    if formulas.get("registry_version")!=formula.get("version"):errors.append("Outcome policy formula registry version mismatch.")
    if set(formula.get("referenced_formula_ids",[]))!={"METRIC.MAE","METRIC.RMSE","METRIC.MAPE"} or not set(formula.get("referenced_formula_ids",[]))<=formula_ids:errors.append("Outcome policy formula identity mismatch.")
    if errors: raise ForecastOutcomePolicyError(" ".join(dict.fromkeys(errors)))
    return policy,digest
