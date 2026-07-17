"""Stage evidence-only model-performance comparisons from a verified monitoring snapshot."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from model_degradation_metrics import aggregate_metrics, canonical_json, canonical_sha256, metric_delta, metric_ratio, ordered_outcome_set_hash, ordered_outcomes, period_warnings, strict_cohort_identity, strict_cohort_key, training_history_context
from runtime_commit import atomic_json
from runtime_context import ROOT, require_absolute_directory, require_within
from runtime_model_degradation_policy import load_and_validate_model_degradation_policy
from runtime_model_degradation_source import verify_model_degradation_source


def _now() -> str: return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
def _json(path: Path) -> dict[str, Any]:
    value=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value,dict):raise ValueError(f"{path.name} must be an object.")
    return value
def _schema(value: Mapping[str,Any], name: str) -> None:
    schema=_json(ROOT/"config"/name);errors=sorted(Draft202012Validator(schema,format_checker=FormatChecker()).iter_errors(value),key=lambda error:list(error.path))
    if errors:raise ValueError(f"{name}: {errors[0].message}")
def _update_job(path:Path,job:dict[str,Any],progress:str)->None:job.update(progress=progress,updatedAt=_now());atomic_json(path,job)


def build_model_degradation_evidence(job: Mapping[str,Any], policy: Mapping[str,Any], policy_sha: str, source: Mapping[str,Any], generated_at: str) -> tuple[dict[str,Any],dict[str,Any]]:
    groups:dict[str,list[dict[str,Any]]]={}
    for outcome in source["outcomes"]:
        groups.setdefault(strict_cohort_key(outcome),[]).append(outcome)
    cohorts=[]
    for cohort_id in sorted(groups):
        records=ordered_outcomes(groups[cohort_id]);identity=strict_cohort_identity(records[0])
        if any(strict_cohort_identity(record)!=identity for record in records):raise ValueError("Cohort identity collision.")
        refs=[]
        if identity["sourceFamily"]!="quick_forecast_p1":
            by_assessment:dict[str,list[Mapping[str,Any]]]={}
            for record in records:by_assessment.setdefault(str(record["sourceEvidence"]["assessmentId"]),[]).append(record)
            for assessment_id in sorted(by_assessment):
                reference=source["assessmentReferences"].get(assessment_id)
                if not reference:raise ValueError("Approved cohort lacks exact assessment reference.")
                observed=aggregate_metrics(by_assessment[assessment_id]);assessment_mae=float(reference["assessmentMAE"]);assessment_rmse=float(reference["assessmentRMSE"])
                raw_equivalent=reference["clippingCount"]==0 and all(float(record["forecastRaw"])>=0 for record in by_assessment[assessment_id])
                refs.append({"referenceType":"committed_assessment",**reference,"observedOutcomeCount":observed["count"],"observedMAE":observed["mae"],"maeDelta":metric_delta(assessment_mae,observed["mae"]),"maeRatio":metric_ratio(assessment_mae,observed["mae"]),"observedRMSE":observed["rmse"],"rmseDelta":metric_delta(assessment_rmse,observed["rmse"]),"rmseRatio":metric_ratio(assessment_rmse,observed["rmse"]),"comparabilityStatus":"limited_cross_population_comparability","forecastValueBasisStatus":"equivalent_no_clipping_observed" if raw_equivalent else "forecast_value_basis_mismatch","sampleSufficiencyStatus":"not_governed","materialWorseningStatus":"not_governed","lifecycleActionStatus":"prohibited_not_generated","evidenceState":"computable_descriptive_evidence"})
        warnings=period_warnings(records)
        population=aggregate_metrics(records)
        if population["percentageEligibleCount"]==0:warnings.append("percentage_metric_unavailable")
        if population["rangeEligibleCount"]==0:warnings.append("range_metric_unavailable")
        if identity["sourceFamily"]=="quick_forecast_p1":warnings.append("not_applicable_no_assessment_reference")
        ordered_refs=[{"outcomeId":record["outcomeId"],"outcomeCommitSha256":record["outcomeCommitSha256"],"outcomeEvidenceSha256":record["outcomeEvidenceSha256"],"sourceForecastRunId":str(record.get("sourceForecastRunId",record.get("forecastRunId"))),"targetPeriod":record["forecastTargetPeriod"]} for record in records]
        cohorts.append({"cohortId":cohort_id,"identity":identity,"outcomeCount":len(records),"orderedOutcomes":ordered_refs,"outcomeSetSha256":ordered_outcome_set_hash(records),"actualPopulation":population,"trainingContext":training_history_context(records),"assessmentReferenceStatus":"not_applicable_no_assessment_reference" if identity["sourceFamily"]=="quick_forecast_p1" else "computable_descriptive_evidence","assessmentReferences":refs,"monitoringWindow":{"status":"window_size_not_governed","windowOutcomeCount":None,"metricsCalculated":False,"sampleSufficiencyStatus":"not_governed","materialWorseningStatus":"not_governed","lifecycleActionStatus":"prohibited_not_generated"},"warnings":sorted(set(warnings))})
    cohort_set_sha=canonical_sha256([{"cohortId":value["cohortId"],"outcomeSetSha256":value["outcomeSetSha256"]} for value in cohorts])
    degradation_policy={"policyId":policy["policy_id"],"policyVersion":policy["policy_version"],"policySha256":policy_sha};monitoring_policy={"policyId":"RUNTIME.FORECAST_OUTCOME.MONITORING","policyVersion":"p2-v1","policySha256":policy["accepted_monitoring_policy"]["policy_sha256"]}
    monitoring_input={"latestPath":source["latestPath"],"latestSha256":source["latestSha256"],"summaryPath":source["summaryPath"],"summarySha256":source["summarySha256"],"includedOutcomeSetSha256":source["summary"]["outcomeSetSha256"],"verifiedOutcomeCount":len(source["outcomes"])}
    evidence={"schemaVersion":"1.0","evidenceId":job["evidenceId"],"jobId":job["jobId"],"deploymentId":"dhaka_south","geography":{"level":"city","id":"BGD-DHAKA-SOUTH","name":"Dhaka South"},"degradationPolicy":degradation_policy,"monitoringPolicy":monitoring_policy,"monitoringInput":monitoring_input,"evidenceStatus":"evidence_only","materialWorseningStatus":"not_governed","lifecycleActionStatus":"prohibited_not_generated","cohorts":cohorts,"includedCohortSetSha256":cohort_set_sha,"generatedAt":generated_at,"limitations":[policy["maturity_statement"],"Assessment-reference and monitoring-window evidence are separate dimensions.","Monitoring-window metrics are disabled because no governed window size exists.","Statistical sufficiency and material worsening are not governed."]}
    def counts(key):
        result:dict[str,int]={}
        for cohort in cohorts:result[str(key(cohort))]=result.get(str(key(cohort)),0)+cohort["outcomeCount"]
        return dict(sorted(result.items()))
    all_periods=[record["forecastTargetPeriod"] for record in source["outcomes"]]
    ref_count=sum(len(value["assessmentReferences"]) for value in cohorts);percentage_unavailable=sum("percentage_metric_unavailable" in value["warnings"] for value in cohorts);range_unavailable=sum("range_metric_unavailable" in value["warnings"] for value in cohorts)
    summary={"schemaVersion":"1.0","evidenceId":job["evidenceId"],"deploymentId":"dhaka_south","policyId":policy["policy_id"],"policyVersion":policy["policy_version"],"policySha256":policy_sha,"monitoringPolicyId":"RUNTIME.FORECAST_OUTCOME.MONITORING","monitoringPolicyVersion":"p2-v1","monitoringPolicySha256":monitoring_policy["policySha256"],"verifiedOutcomeCount":len(source["outcomes"]),"cohortCount":len(cohorts),"assessmentReferenceDimensionCount":ref_count,"computableDescriptiveDimensionCount":ref_count,"insufficientEvidenceDimensionCount":0,"windowSizeNotGovernedDimensionCount":len(cohorts),"percentageUnavailableDimensionCount":percentage_unavailable,"rangeUnavailableDimensionCount":range_unavailable,"sourceFamilyCounts":counts(lambda value:value["identity"]["sourceFamily"]),"modelCounts":counts(lambda value:f"{value['identity']['modelId']}|{value['identity']['modelFamily']}|{value['identity']['parameterSha256']}"),"policyCounts":counts(lambda value:f"{value['identity']['monitoringPolicy']['policyId']}|{value['identity']['monitoringPolicy']['policyVersion']}|{value['identity']['monitoringPolicy']['policySha256']}"),"latestTargetPeriod":max(all_periods,key=lambda value:__import__('datetime').datetime.fromisocalendar(int(value[:4]),int(value[-2:]),1)),"includedCohortSetSha256":cohort_set_sha,"includedOutcomeSetSha256":source["summary"]["outcomeSetSha256"],"evidenceStatus":"evidence_only","materialWorseningStatus":"not_governed","lifecycleActionStatus":"prohibited_not_generated","generatedAt":generated_at}
    canonical_json(evidence);canonical_json(summary);return evidence,summary


def execute(args:argparse.Namespace)->dict[str,Any]:
    root=require_absolute_directory(args.runtime_root,"runtime root");job_path=require_within(root,args.job_record,"job record");staging=require_within(root,args.staging,"degradation staging");job=_json(job_path)
    if job.get("jobKind")!="degradation_evidence":raise ValueError("Not a degradation-evidence job.")
    _schema(job,"runtime_job.schema.json");policy,digest=load_and_validate_model_degradation_policy(job["deploymentId"],job["schemaVersion"],job["policyVersion"],job["policySha256"])
    _update_job(job_path,job,"verifying_monitoring_snapshot");source=verify_model_degradation_source(root,job["expectedMonitoringLatestSha256"],job["expectedMonitoringSummarySha256"],job["expectedIncludedOutcomeSetSha256"])
    generated=_now();evidence,summary=build_model_degradation_evidence(job,policy,digest,source,generated)
    (staging/"artifacts").mkdir(parents=True,exist_ok=False);(staging/"metadata").mkdir(parents=True,exist_ok=False);atomic_json(staging/"artifacts/degradation_evidence.json",evidence);atomic_json(staging/"artifacts/degradation_summary.json",summary)
    _schema(evidence,"runtime_model_degradation_evidence.schema.json");_schema(summary,"runtime_model_degradation_summary.schema.json");_update_job(job_path,job,"committing_degradation_evidence")
    from runtime_model_degradation_commit import commit_model_degradation_evidence
    return commit_model_degradation_evidence(root,staging,job,policy)


def main()->int:
    parser=argparse.ArgumentParser();parser.add_argument("--runtime-root",required=True);parser.add_argument("--job-record",required=True);parser.add_argument("--staging",required=True);args=parser.parse_args()
    try:result=execute(args);print(json.dumps({"evidenceId":result["commit"]["evidenceId"],"committed":True,"recovered":result["recovered"]}));return 0
    except Exception as exc:print(f"degradation_failure:{type(exc).__name__}:{exc}",file=__import__('sys').stderr);return 1
if __name__=="__main__":raise SystemExit(main())
