"""Strict version-routed forecast-outcome policy loading."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
from typing import Any, Mapping
from jsonschema import Draft202012Validator, FormatChecker
from runtime_context import ROOT

POLICY_ID="RUNTIME.FORECAST_OUTCOME.MONITORING"
P1_VERSION="p1.4g-v1"; P1_SHA="0121c2fad28b7b8e9080df52698593d1cab677febf4fa668e11f6f19541fb249"
P2_VERSION="p2-v1"; P2_SHA="c73461e211e334733309232806fa2d41c2e5fdce7aa5e096d065e13e7525eaab"
P21_VERSION="p2-v2"; P21_SHA="5c3e1f7f14ab6a0a2fbc28639411a0269224b6f71746a315b9c6e159a6eacca6"
P22_VERSION="p2-v3"; P22_SHA="cc3b533b7cfc16b841401b7a60f6308632526f58d5685578d7f368dec96a09d9"
SCHEMA=ROOT/"config/runtime_forecast_outcome_policy.schema.json"
class ForecastOutcomePolicyError(ValueError): pass

def canonical_policy_sha256(value:Mapping[str,Any])->str:
    content=dict(value);content.pop("policy_sha256",None)
    return hashlib.sha256(json.dumps(content,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()).hexdigest()

def _policy_path(deployment_id:str,schema_version:str,policy_version:str)->Path:
    if deployment_id!="dhaka_south":raise ForecastOutcomePolicyError("Unsupported outcome-monitoring deployment.")
    if (schema_version,policy_version)==("1.0",P1_VERSION):return ROOT/"config/deployments"/deployment_id/"forecast_outcome_policy_p1.4g-v1.json"
    if (schema_version,policy_version)==("2.0",P2_VERSION):return ROOT/"config/deployments"/deployment_id/"forecast_outcome_policy_p2-v1.json"
    if (schema_version,policy_version)==("2.1",P21_VERSION):return ROOT/"config/deployments"/deployment_id/"forecast_outcome_policy_p2-v2.json"
    if (schema_version,policy_version)==("2.1",P22_VERSION):return ROOT/"config/deployments"/deployment_id/"forecast_outcome_policy.json"
    raise ForecastOutcomePolicyError("Unknown or hybrid outcome-monitoring policy identity.")

def load_and_validate_forecast_outcome_policy(deployment_id:str,schema_version:str="2.1",policy_version:str|None=None,policy_sha256:str|None=None)->tuple[dict[str,Any],str]:
    expected_version=policy_version or (P1_VERSION if schema_version=="1.0" else P2_VERSION if schema_version=="2.0" else P22_VERSION if schema_version=="2.1" else "")
    path=_policy_path(deployment_id,schema_version,expected_version)
    policy=json.loads(path.read_text(encoding="utf-8"));schema=json.loads(SCHEMA.read_text(encoding="utf-8"))
    errors=sorted(Draft202012Validator(schema,format_checker=FormatChecker()).iter_errors(policy),key=lambda e:list(e.path))
    digest=canonical_policy_sha256(policy);expected_sha=P1_SHA if expected_version==P1_VERSION else P2_SHA if expected_version==P2_VERSION else P21_SHA if expected_version==P21_VERSION else P22_SHA
    identity=(policy.get("schema_version"),policy.get("policy_id"),policy.get("policy_version"),policy.get("policy_sha256"))
    if identity!=(schema_version,POLICY_ID,expected_version,expected_sha) or digest!=expected_sha or policy_sha256 not in (None,expected_sha):raise ForecastOutcomePolicyError("Outcome-monitoring policy identity or hash mismatch.")
    if errors:raise ForecastOutcomePolicyError(errors[0].message)
    if policy.get("deployment_id")!=deployment_id or policy.get("policy_status")!="active":raise ForecastOutcomePolicyError("Outcome-monitoring policy is unavailable.")
    if schema_version=="2.0" and set(policy.get("source_families",{}))!={"quick_forecast_p1","approved_forecast_p1","approved_forecast_p2"}:raise ForecastOutcomePolicyError("Outcome-monitoring source families are invalid.")
    if schema_version=="2.1" and set(policy.get("source_families",{}))!={"quick_forecast_p1","quick_forecast_p2","approved_forecast_p1","approved_forecast_p2"}:raise ForecastOutcomePolicyError("Outcome-monitoring source families are invalid.")
    return policy,digest
