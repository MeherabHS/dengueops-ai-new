import json
import shutil
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"analytics"))

from runtime_commit import atomic_json, sha256_file
from runtime_worker import run_once
from runtime_forecast_outcome import execute as execute_outcome
from runtime_model_degradation_evidence import execute as execute_degradation
from runtime_assessment_evidence import (
    aggregate_candidate,
    select_technical_winner,
    NONNEGATIVE_RAW_MODEL_IDS,
)
from tests.test_runtime_assessment_commit import build_ready_assessment_runtime, iso_now
from tests.test_runtime_forecast_outcome import build_outcome_job
from tests.test_runtime_model_degradation_evidence import degradation_job


def build_promotion_chain_p2_v1(base: Path, repository_root: Path, model_id: str = "random_forest") -> dict:
    base_runtime, _workspace, _pending, assessment_job = build_ready_assessment_runtime(
        base / "base", assessment_policy_version="p2-v1"
    )
    if not run_once(base_runtime, "lifecycle-assessment"): raise AssertionError("assessment did not execute")
    runtime=(base/model_id/"runtime").resolve();shutil.copytree(base_runtime,runtime,copy_function=shutil.copyfile)
    assessment = runtime / "assessments" / assessment_job["assessmentId"]
    summary_path=assessment/"artifacts/assessment_summary.json"; comparison_path=assessment/"artifacts/candidate_model_comparison.json"; rolling_path=assessment/"artifacts/rolling_validation.json";recommendation_path=assessment/"artifacts/recommendation.json";metadata_path=assessment/"metadata/assessment.json";commit_path=assessment/"metadata/commit.json"
    summary=json.loads(summary_path.read_text());comparison=json.loads(comparison_path.read_text());rolling=json.loads(rolling_path.read_text());recommendation=json.loads(recommendation_path.read_text());metadata=json.loads(metadata_path.read_text());selected=next(candidate for candidate in summary["candidates"] if candidate["modelId"]==model_id)
    if model_id!="random_forest":
        for fold in rolling["folds"]:
            chosen=next(value for value in fold["predictions"] if value["modelId"]==model_id);forest=next(value for value in fold["predictions"] if value["modelId"]=="random_forest");chosen["modelId"],forest["modelId"]="random_forest",model_id
        actuals=[fold["actualTarget"] for fold in rolling["folds"]];records={candidate["modelId"]:[next(value for value in fold["predictions"] if value["modelId"]==candidate["modelId"]) for fold in rolling["folds"]] for candidate in comparison["candidates"]}
        for candidate in comparison["candidates"]:
            historical_metrics = aggregate_candidate(records[candidate["modelId"]], actuals)
            candidate["metrics"] = {key: value for key, value in historical_metrics.items() if key not in {"mse", "r2"}}
        winner,tie_stage,tie_steps,eligible_ids=select_technical_winner(comparison["candidates"]);assert winner==model_id
        winner_records=records[winner]
        for candidate in comparison["candidates"]:
            better=tied=worse=0
            for record,chosen_record in zip(records[candidate["modelId"]],winner_records):
                difference=record["absoluteError"]-chosen_record["absoluteError"];better+=difference < -1e-9;tied+=abs(difference)<=1e-9;worse+=difference>1e-9
            candidate["foldWinsTiesLosses"]={"better":better,"tied":tied,"worse":worse}
        comparison.update(technicalWinnerModelId=winner,winnerParameterSha256=selected["parametersSha256"],tieStage=tie_stage,tieResolutionSteps=tie_steps,selectionEligibleCandidateIds=eligible_ids,selectionReason=f"{winner} had the lowest governed metric sequence among candidates completing all {len(rolling['folds'])} folds.")
        winner_candidate=next(value for value in comparison["candidates"] if value["modelId"]==winner);runner=min((value for value in comparison["candidates"] if value["modelId"]!=winner),key=lambda value:value["metrics"]["mae"]);winner_mae=winner_candidate["metrics"]["mae"];runner_mae=runner["metrics"]["mae"]
        recommendation.update(technicalWinnerModelId=winner,winnerParameterSha256=winner_candidate["parametersSha256"],evidenceInputs={"winnerMae":winner_mae,"runnerUpMae":runner_mae,"absoluteMaeGap":runner_mae-winner_mae,"relativeMaeGap":(runner_mae-winner_mae)/runner_mae,"successfulFoldRatio":1.0,"failedFoldCount":0,"clippingCount":winner_candidate["metrics"]["clippingCount"],"warningCount":winner_candidate["metrics"]["warningCount"],"candidateBreadth":len(comparison["candidates"]),"tieBreakStageUsed":tie_stage,"datasetFoldCount":len(rolling["folds"])})
        atomic_json(rolling_path,rolling)
        comparison["rollingValidationSha256"]=sha256_file(rolling_path)
    comparison["technicalWinnerModelId"]=model_id;comparison["winnerParameterSha256"]=selected["parametersSha256"];summary["technicalWinnerModelId"]=model_id;summary["candidates"]=comparison["candidates"];summary["selectionReason"]=comparison["selectionReason"];summary["tieStage"]=comparison["tieStage"]
    atomic_json(comparison_path,comparison);atomic_json(recommendation_path,recommendation);summary["evidenceHashes"]["rollingValidationSha256"]=sha256_file(rolling_path);summary["evidenceHashes"]["candidateComparisonSha256"]=sha256_file(comparison_path);summary["evidenceHashes"]["recommendationSha256"]=sha256_file(recommendation_path);atomic_json(summary_path,summary)
    metadata["artifactHashes"]["rollingValidationSha256"]=sha256_file(rolling_path);metadata["artifactHashes"]["candidateComparisonSha256"]=sha256_file(comparison_path);metadata["artifactHashes"]["recommendationSha256"]=sha256_file(recommendation_path);metadata["artifactHashes"]["assessmentSummarySha256"]=sha256_file(summary_path);atomic_json(metadata_path,metadata)
    assessment_commit=json.loads(commit_path.read_text());assessment_commit["artifactHashes"]["rolling_validation.json"]=sha256_file(rolling_path);assessment_commit["artifactHashes"]["candidate_model_comparison.json"]=sha256_file(comparison_path);assessment_commit["artifactHashes"]["recommendation.json"]=sha256_file(recommendation_path);assessment_commit["artifactHashes"]["assessment_summary.json"]=sha256_file(summary_path);atomic_json(commit_path,assessment_commit)
    assessment_commit_sha=sha256_file(commit_path);decision_id,authorization_id,job_id,run_id=[str(uuid.uuid4()) for _ in range(4)];created=iso_now();expires=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat().replace("+00:00","Z")
    policy=json.loads((repository_root/"config/deployments/dhaka_south/decision_policy_p2-v1.json").read_text());decision_root=runtime/"decisions"/decision_id;decision_root.mkdir(parents=True)
    decision={"schemaVersion":"2.0","decisionId":decision_id,"assessmentId":assessment_job["assessmentId"],"assessmentCommitSha256":assessment_commit_sha,"datasetId":summary["datasetId"],"assessmentSchemaVersion":"2.0","assessmentLabelledRows":summary["labelledRows"],"assessmentPlannedFoldCount":summary["foldPolicy"]["plannedFoldCount"],"selectedEvaluationPeriod":summary["foldPolicy"]["selectedEvaluationPeriod"],"assessmentSummarySha256":sha256_file(summary_path),"comparisonSha256":sha256_file(comparison_path),"recommendationSha256":summary["evidenceHashes"]["recommendationSha256"],"foldPlanSha256":summary["foldPlanSha256"],"deploymentId":"dhaka_south","validationRecordSha256":summary["provenance"]["validationRecordSha256"],"assessmentPolicyId":policy["allowedAssessmentPolicyId"],"assessmentPolicyVersion":policy["allowedAssessmentPolicyVersion"],"assessmentPolicySha256":policy["allowedAssessmentPolicySha256"],"decisionPolicyId":policy["policyId"],"decisionPolicyVersion":policy["policyVersion"],"decisionPolicySha256":policy["policySha256"],"candidateRegistrySha256":policy["candidateRegistrySha256"],"technicalWinnerModelId":model_id,"technicalWinnerParameterSha256":selected["parametersSha256"],"decision":"approve_technical_winner","selectedModelId":model_id,"selectedModelParameterSha256":selected["parametersSha256"],"decisionScope":"one_run","operatorType":"trusted_internal_unverified","operatorIdentifier":"lifecycle-fixture","institutionalApproval":False,"reason":"Governed lifecycle fixture.","limitationsAcknowledged":True,"decisionStatus":"approved_technical_winner","forecastAuthorized":True,"authorizationId":authorization_id,"createdAt":created,"correlationId":str(uuid.uuid4()),"supersedesDecisionId":None,"supersessionStatus":"active"}
    atomic_json(decision_root/"decision.json",decision)
    decision_commit={"schemaVersion":"2.0","decisionId":decision_id,"assessmentId":assessment_job["assessmentId"],"decisionSha256":sha256_file(decision_root/"decision.json"),"assessmentCommitSha256":assessment_commit_sha,"assessmentSchemaVersion":"2.0","assessmentSummarySha256":sha256_file(summary_path),"assessmentPolicyId":policy["allowedAssessmentPolicyId"],"assessmentPolicyVersion":policy["allowedAssessmentPolicyVersion"],"assessmentPolicySha256":policy["allowedAssessmentPolicySha256"],"decisionPolicyId":policy["policyId"],"decisionPolicyVersion":policy["policyVersion"],"decisionPolicySha256":policy["policySha256"],"foldPlanSha256":summary["foldPlanSha256"],"assessmentLabelledRows":summary["labelledRows"],"assessmentPlannedFoldCount":summary["foldPolicy"]["plannedFoldCount"],"status":"committed","committedAt":created,"latestPointerUpdated":False,"deploymentProfileModified":False}
    atomic_json(decision_root/"commit.json",decision_commit);decision_commit_sha=sha256_file(decision_root/"commit.json")
    auth_root=runtime/"authorizations"/authorization_id;auth_root.mkdir(parents=True)
    authorization={"schemaVersion":"2.0","authorizationId":authorization_id,"decisionId":decision_id,"decisionCommitSha256":decision_commit_sha,"assessmentId":assessment_job["assessmentId"],"assessmentCommitSha256":assessment_commit_sha,"assessmentPolicyId":policy["allowedAssessmentPolicyId"],"assessmentPolicyVersion":policy["allowedAssessmentPolicyVersion"],"assessmentPolicySha256":policy["allowedAssessmentPolicySha256"],"decisionPolicyId":policy["policyId"],"decisionPolicyVersion":policy["policyVersion"],"decisionPolicySha256":policy["policySha256"],"datasetId":summary["datasetId"],"deploymentId":"dhaka_south","selectedModelId":model_id,"selectedModelParameterSha256":selected["parametersSha256"],"assessmentLabelledRows":summary["labelledRows"],"assessmentPlannedFoldCount":summary["foldPolicy"]["plannedFoldCount"],"foldPlanSha256":summary["foldPlanSha256"],"workflowMode":"approved_assessment_forecast","scope":"one_run","initialStatus":"available","createdAt":created,"expiresAt":expires,"policyId":policy["policyId"],"policyVersion":policy["policyVersion"],"policySha256":policy["policySha256"]}
    atomic_json(auth_root/"authorization.json",authorization);atomic_json(auth_root/"commit.json",{"schemaVersion":"1.0","authorizationId":authorization_id,"decisionId":decision_id,"authorizationSha256":sha256_file(auth_root/"authorization.json"),"decisionCommitSha256":decision_commit_sha,"status":"committed","committedAt":created});authorization_commit_sha=sha256_file(auth_root/"commit.json")
    state=runtime/"authorization-state"/authorization_id;state.mkdir(parents=True);atomic_json(state/"reservation.json",{"schemaVersion":"1.0","authorizationId":authorization_id,"decisionId":decision_id,"eventType":"reserved","eventId":str(uuid.uuid4()),"createdAt":created,"jobId":job_id,"runId":run_id})
    job={"schemaVersion":"1.0","jobKind":"approved_forecast","jobId":job_id,"runId":run_id,"decisionId":decision_id,"decisionCommitSha256":decision_commit_sha,"authorizationId":authorization_id,"assessmentId":assessment_job["assessmentId"],"assessmentCommitSha256":assessment_commit_sha,"workspaceId":assessment_job["assessmentId"],"datasetId":summary["datasetId"],"deploymentId":"dhaka_south","selectedModelId":model_id,"selectedModelParameterSha256":selected["parametersSha256"],"workflowMode":"approved_assessment_forecast","validationRecordSha256":summary["provenance"]["validationRecordSha256"],"status":"queued","progress":"queued","createdAt":created,"claimedAt":None,"startedAt":None,"updatedAt":created,"completedAt":None,"heartbeatAt":None,"workerId":None,"processId":None,"timeoutSeconds":600,"retryCount":0,"error":None,"committedRunId":None}
    atomic_json(runtime/"jobs/pending"/f"{job_id}.json",job)
    if not run_once(runtime,"lifecycle-approved"):raise AssertionError("approved forecast did not execute")
    approved_commit_sha=sha256_file(runtime/"runs"/run_id/"metadata/commit.json")
    outcome_job,outcome_path=build_outcome_job(runtime,{"runId":run_id},record_id=f"lifecycle-{model_id}");execute_outcome(SimpleNamespace(runtime_root=str(runtime),job_record=str(outcome_path),staging=str(runtime/"outcome-staging"/outcome_job["outcomeId"])))
    outcome_commit_sha=sha256_file(runtime/"forecast-outcomes"/outcome_job["outcomeId"]/"metadata/commit.json");monitoring_latest=runtime/"deployments/dhaka_south/monitoring/latest.json";monitoring=json.loads(monitoring_latest.read_text());monitoring_summary=runtime/monitoring["monitoringSummaryPath"]
    degradation,degradation_path=degradation_job(runtime);execute_degradation(SimpleNamespace(runtime_root=str(runtime),job_record=str(degradation_path),staging=str(runtime/"degradation-staging"/degradation["evidenceId"])))
    degradation_latest=runtime/"deployments/dhaka_south/degradation/latest.json";degradation_pointer=json.loads(degradation_latest.read_text());degradation_evidence=runtime/degradation_pointer["evidencePath"]
    return {"runtime":runtime,"assessmentId":assessment_job["assessmentId"],"decisionId":decision_id,"authorizationId":authorization_id,"runId":run_id,"outcomeId":outcome_job["outcomeId"],"modelId":model_id,"assessmentCommitSha256":assessment_commit_sha,"decisionCommitSha256":decision_commit_sha,"authorizationCommitSha256":authorization_commit_sha,"approvedForecastCommitSha256":approved_commit_sha,"outcomeCommitSha256":outcome_commit_sha,"monitoringLatestSha256":sha256_file(monitoring_latest),"monitoringSummarySha256":sha256_file(monitoring_summary),"monitoringIncludedOutcomeSetSha256":json.loads(monitoring_summary.read_text())["outcomeSetSha256"],"degradationLatestSha256":sha256_file(degradation_latest),"degradationEvidenceCommitSha256":degradation_pointer["commitSha256"],"degradationEvidenceSha256":sha256_file(degradation_evidence)}


build_promotion_chain = build_promotion_chain_p2_v1


def _force_assessment_winner(
    rolling: dict,
    comparison: dict,
    summary: dict,
    recommendation: dict,
    target_id: str,
    donor_id: str,
) -> str:
    """
    Swap fold prediction records from donor_id → target_id so that target_id
    obtains the donor's complete, successful fold records and becomes the
    technical winner.  donor_id receives target_id's (possibly partial) records.
    All derived metrics, statuses and comparison fields are recomputed.
    Returns the new technicalWinnerModelId (should equal target_id).
    """
    # Collect per-fold records keyed by fold index
    donor_preds: dict[int, dict] = {}
    target_preds: dict[int, dict] = {}
    for fold_idx, fold in enumerate(rolling["folds"]):
        for pred in fold["predictions"]:
            if pred["modelId"] == donor_id:
                donor_preds[fold_idx] = dict(pred)
            elif pred["modelId"] == target_id:
                target_preds[fold_idx] = dict(pred)

    # Rebuild prediction lists: target_id receives donor_id's predictions,
    # scaled by 0.9 towards actual target so target_id's MAE/RMSE/WAPE are
    # strictly 10% lower than donor_id's and target_id wins stage 1 (mae) cleanly.
    for fold_idx, fold in enumerate(rolling["folds"]):
        actual = float(fold["actualTarget"])
        fold["predictions"] = [
            p for p in fold["predictions"]
            if p["modelId"] not in {donor_id, target_id}
        ]
        if fold_idx in donor_preds:
            dp = donor_preds[fold_idx]
            new_target = dict(dp)
            new_target["modelId"] = target_id
            raw_diff = float(dp["rawPrediction"]) - actual
            pub_diff = float(dp["publishedPrediction"]) - actual
            new_raw = round(actual + 0.9 * raw_diff, 6)
            new_pub = max(0.0, round(actual + 0.9 * pub_diff, 6)) if target_id in NONNEGATIVE_RAW_MODEL_IDS else round(actual + 0.9 * pub_diff, 6)
            new_abs_err = round(abs(new_pub - actual), 6)
            new_target["rawPrediction"] = new_raw
            new_target["publishedPrediction"] = new_pub
            new_target["clippingApplied"] = new_raw < 0
            new_target["signedError"] = round(new_pub - actual, 6)
            new_target["absoluteError"] = new_abs_err
            new_target["squaredError"] = round(new_abs_err ** 2, 6)
            fold["predictions"].append(new_target)

        if fold_idx in target_preds:
            new_donor = dict(target_preds[fold_idx])
            new_donor["modelId"] = donor_id
            fold["predictions"].append(new_donor)

    # Build per-candidate fold record lists (None for missing folds)
    candidate_ids = [c["modelId"] for c in comparison["candidates"]]
    records_map: dict[str, list] = {cid: [] for cid in candidate_ids}
    actuals: list[float] = [float(fold["actualTarget"]) for fold in rolling["folds"]]
    for fold in rolling["folds"]:
        preds_in_fold = {p["modelId"]: p for p in fold["predictions"]}
        for cid in candidate_ids:
            records_map[cid].append(preds_in_fold.get(cid))

    # Recompute metrics for every candidate
    for candidate in comparison["candidates"]:
        cid = candidate["modelId"]
        raw_records = records_map[cid]
        full_records = []
        full_actuals = []
        for actual, rec in zip(actuals, raw_records):
            if rec is not None:
                full_records.append(rec)
                full_actuals.append(actual)
        # Count only folds with a success/warning foldStatus as "successful".
        # Failed-status fold records are present in rolling (non-None) but must not
        # count toward completion — otherwise NB's 47 failed folds would be counted
        # as successful and make it incorrectly selectionEligible.
        successful = sum(
            1 for r in raw_records
            if r is not None and r.get("foldStatus") in {"success", "warning"}
        )
        failed = len(rolling["folds"]) - successful
        candidate["successfulFolds"] = successful
        candidate["failedFolds"] = failed
        if full_records:
            metrics = aggregate_candidate(full_records, full_actuals)
        else:
            metrics = None
        candidate["metrics"] = (
            {k: v for k, v in metrics.items() if k not in {"mse", "r2"}} if metrics else None
        )
        planned_folds = len(rolling["folds"])
        candidate["selectionEligible"] = (
            candidate.get("candidateClass") == "learned_model"
            and successful == planned_folds
            and failed == 0
            and metrics is not None
        )
        candidate["completionStatus"] = "complete" if (successful == planned_folds and failed == 0) else "incomplete"

    # Reselect technical winner
    winner_id_new, tie_stage, tie_steps, eligible_ids = select_technical_winner(comparison["candidates"])
    assert winner_id_new == target_id, (
        f"After patching, expected technical winner to be '{target_id}', got '{winner_id_new}'. "
        "Check that donor_id had the best metrics and fully completed all folds."
    )

    # Recompute fold wins/ties/losses relative to new winner
    winner_records = records_map[winner_id_new]
    for candidate in comparison["candidates"]:
        better = tied = worse = 0
        for wr, cr in zip(winner_records, records_map[candidate["modelId"]]):
            if (
                wr is not None
                and cr is not None
                and wr.get("absoluteError") is not None
                and cr.get("absoluteError") is not None
            ):
                diff = cr["absoluteError"] - wr["absoluteError"]
                if diff < -1e-9:
                    better += 1
                elif abs(diff) <= 1e-9:
                    tied += 1
                else:
                    worse += 1
        candidate["foldWinsTiesLosses"] = {"better": better, "tied": tied, "worse": worse}

    # Assign statuses
    baseline_ids = {c["modelId"] for c in comparison["candidates"] if c.get("comparisonRole") == "baseline_only"}
    for candidate in comparison["candidates"]:
        cid = candidate["modelId"]
        if cid in baseline_ids:
            candidate["status"] = "baseline_only"
        elif not candidate.get("eligible", True):
            candidate["status"] = "disqualified"
        elif not candidate["selectionEligible"]:
            candidate["status"] = "failed"
        elif cid == winner_id_new:
            candidate["status"] = "technical_winner"
        else:
            candidate["status"] = "eligible_non_winner"

    winner_candidate = next(c for c in comparison["candidates"] if c["modelId"] == winner_id_new)
    runner_up = min(
        (c for c in comparison["candidates"] if c["modelId"] != winner_id_new and c.get("selectionEligible")),
        key=lambda c: c["metrics"]["mae"],
        default=None,
    )
    winner_mae = float(winner_candidate["metrics"]["mae"])
    runner_mae = float(runner_up["metrics"]["mae"]) if runner_up else winner_mae

    comparison.update(
        technicalWinnerModelId=winner_id_new,
        winnerParameterSha256=winner_candidate["parametersSha256"],
        tieStage=tie_stage,
        tieResolutionSteps=tie_steps,
        selectionEligibleCandidateIds=eligible_ids,
        selectionReason=(
            f"{winner_id_new} had the lowest governed metric sequence among candidates "
            f"completing all {len(rolling['folds'])} folds."
        ),
    )

    summary["technicalWinnerModelId"] = winner_id_new
    summary["candidates"] = comparison["candidates"]
    summary["selectionReason"] = comparison["selectionReason"]
    summary["tieStage"] = tie_stage

    recommendation.update(
        technicalWinnerModelId=winner_id_new,
        winnerParameterSha256=winner_candidate["parametersSha256"],
        evidenceInputs={
            "winnerMae": winner_mae,
            "runnerUpMae": runner_mae,
            "absoluteMaeGap": runner_mae - winner_mae,
            "relativeMaeGap": (runner_mae - winner_mae) / runner_mae if runner_mae else 0.0,
            "successfulFoldRatio": 1.0,
            "failedFoldCount": 0,
            "clippingCount": winner_candidate["metrics"].get("clippingCount", 0),
            "warningCount": winner_candidate["metrics"].get("warningCount", 0),
            "candidateBreadth": len(comparison["candidates"]),
            "tieBreakStageUsed": tie_stage,
            "datasetFoldCount": len(rolling["folds"]),
        },
    )
    return winner_id_new


def _rebuild_assessment_hashes(
    rolling_path: Path,
    comparison_path: Path,
    recommendation_path: Path,
    summary_path: Path,
    metadata_path: Path,
    commit_path: Path,
    rolling: dict,
    comparison: dict,
    recommendation: dict,
    summary: dict,
) -> str:
    """
    Persist all patched assessment artifacts and recompute the full hash chain.
    Returns the new assessment commit SHA-256.
    """
    atomic_json(rolling_path, rolling)
    comparison["rollingValidationSha256"] = sha256_file(rolling_path)
    atomic_json(comparison_path, comparison)
    atomic_json(recommendation_path, recommendation)
    summary["evidenceHashes"]["rollingValidationSha256"] = sha256_file(rolling_path)
    summary["evidenceHashes"]["candidateComparisonSha256"] = sha256_file(comparison_path)
    summary["evidenceHashes"]["recommendationSha256"] = sha256_file(recommendation_path)
    atomic_json(summary_path, summary)

    metadata = json.loads(metadata_path.read_text())
    # assessment.json uses camelCase hash-field keys (not filename keys)
    metadata["artifactHashes"]["rollingValidationSha256"] = sha256_file(rolling_path)
    metadata["artifactHashes"]["candidateComparisonSha256"] = sha256_file(comparison_path)
    metadata["artifactHashes"]["recommendationSha256"] = sha256_file(recommendation_path)
    metadata["artifactHashes"]["assessmentSummarySha256"] = sha256_file(summary_path)
    atomic_json(metadata_path, metadata)

    assessment_commit = json.loads(commit_path.read_text())
    assessment_commit["artifactHashes"]["rolling_validation.json"] = sha256_file(rolling_path)
    assessment_commit["artifactHashes"]["candidate_model_comparison.json"] = sha256_file(comparison_path)
    assessment_commit["artifactHashes"]["recommendation.json"] = sha256_file(recommendation_path)
    assessment_commit["artifactHashes"]["assessment_summary.json"] = sha256_file(summary_path)
    atomic_json(commit_path, assessment_commit)

    return sha256_file(commit_path)


def build_one_run_chain_p2_v2(
    base: Path,
    repository_root: Path,
    model_id: str = "random_forest",
    override: bool = False,
) -> dict:
    """
    Build a fully internally consistent p2-v2 one-run evidence chain for
    the requested model_id.

    override=False  →  model_id is the technical winner
                        (assessment chain is patched so model_id wins)
    override=True   →  the actual assessment winner is preserved;
                        model_id must be a different, eligible non-winner
                        (assessment chain is patched so model_id is eligible
                        if it isn't already, while preserving the real winner)
    """
    base_runtime, _workspace, _pending, assessment_job = build_ready_assessment_runtime(
        base / "base", assessment_policy_version="p2-v2"
    )
    if not run_once(base_runtime, "one-run-assessment"):
        raise AssertionError("p2-v2 assessment did not execute")

    runtime = (base / model_id / "runtime").resolve()
    shutil.copytree(base_runtime, runtime, copy_function=shutil.copyfile)

    assessment = runtime / "assessments" / assessment_job["assessmentId"]
    summary_path      = assessment / "artifacts/assessment_summary.json"
    comparison_path   = assessment / "artifacts/candidate_model_comparison.json"
    rolling_path      = assessment / "artifacts/rolling_validation.json"
    recommendation_path = assessment / "artifacts/recommendation.json"
    metadata_path     = assessment / "metadata/assessment.json"
    commit_path       = assessment / "metadata/commit.json"

    summary      = json.loads(summary_path.read_text())
    comparison   = json.loads(comparison_path.read_text())
    rolling      = json.loads(rolling_path.read_text())
    recommendation = json.loads(recommendation_path.read_text())

    actual_winner_id = summary["technicalWinnerModelId"]

    if not override:
        # --- Technical-winner path -------------------------------------------
        # Patch assessment so model_id is the technical winner.
        if model_id != actual_winner_id:
            _force_assessment_winner(
                rolling, comparison, summary, recommendation,
                target_id=model_id,
                donor_id=actual_winner_id,
            )
        # For models already the winner, no patching needed.
        assessment_commit_sha = _rebuild_assessment_hashes(
            rolling_path, comparison_path, recommendation_path,
            summary_path, metadata_path, commit_path,
            rolling, comparison, recommendation, summary,
        )
        # Refresh from disk
        summary    = json.loads(summary_path.read_text())
        comparison = json.loads(comparison_path.read_text())
        selected   = next(c for c in summary["candidates"] if c["modelId"] == model_id)
        winner     = selected
        selection_type      = "technical_winner"
        decision_type       = "approve_technical_winner"
        candidate_status    = "technical_winner"
        requires_override_ack = False
        override_reason     = None
    else:
        # --- Eligible non-winner override path --------------------------------
        # Keep the actual winner; patch model_id to be an eligible non-winner
        # if it isn't already (e.g. NB failing folds).
        assert model_id != actual_winner_id, (
            f"override=True requires model_id ({model_id!r}) to differ from the technical winner "
            f"({actual_winner_id!r}). Use override=False for the winner."
        )
        model_candidate = next(
            (c for c in comparison["candidates"] if c["modelId"] == model_id), None
        )
        if model_candidate is None or not model_candidate.get("selectionEligible"):
            # Patch model_id to be eligible by giving it records from an eligible non-winner.
            eligible_non_winners = [
                c for c in comparison["candidates"]
                if c["modelId"] not in {actual_winner_id, model_id}
                and c.get("selectionEligible")
                and c.get("candidateClass") == "learned_model"
            ]
            if not eligible_non_winners:
                raise AssertionError(
                    f"No eligible non-winner available to donate folds to {model_id!r}. "
                    "Cannot build override chain."
                )
            donor = eligible_non_winners[0]["modelId"]
            # Save winner records before patching so we can restore them
            winner_preds_saved: dict[int, dict] = {}
            for fold_idx, fold in enumerate(rolling["folds"]):
                for pred in fold["predictions"]:
                    if pred["modelId"] == actual_winner_id:
                        winner_preds_saved[fold_idx] = dict(pred)
            # Swap donor → model_id to make model_id eligible
            _force_assessment_winner(
                rolling, comparison, summary, recommendation,
                target_id=model_id,
                donor_id=donor,
            )
            # Now model_id is the winner — but we need actual_winner_id to win again.
            # Swap model_id ↔ actual_winner_id to restore the original winner.
            # At this point model_id has donor's records and actual_winner_id has
            # model_id's old (possibly empty) records. We need to give actual_winner_id
            # back its original records.
            for fold_idx, fold in enumerate(rolling["folds"]):
                fold["predictions"] = [
                    p for p in fold["predictions"] if p["modelId"] != actual_winner_id
                ]
                if fold_idx in winner_preds_saved:
                    fold["predictions"].append(dict(winner_preds_saved[fold_idx]))

            # Recompute from scratch after the second swap
            candidate_ids = [c["modelId"] for c in comparison["candidates"]]
            actuals_l: list[float] = [float(fold["actualTarget"]) for fold in rolling["folds"]]
            records_map2: dict[str, list] = {cid: [] for cid in candidate_ids}
            for fold in rolling["folds"]:
                preds_in_fold = {p["modelId"]: p for p in fold["predictions"]}
                for cid in candidate_ids:
                    records_map2[cid].append(preds_in_fold.get(cid))

            for candidate in comparison["candidates"]:
                cid = candidate["modelId"]
                raw = records_map2[cid]
                full_recs = [r for r in raw if r is not None]
                full_acts = [actuals_l[i] for i, r in enumerate(raw) if r is not None]
                successful = sum(
                    1 for r in raw
                    if r is not None and r.get("foldStatus") in {"success", "warning"}
                )
                failed = len(rolling["folds"]) - successful
                candidate["successfulFolds"] = successful
                candidate["failedFolds"] = failed
                if full_recs:
                    met = aggregate_candidate(full_recs, full_acts)
                    candidate["metrics"] = {k: v for k, v in met.items() if k not in {"mse", "r2"}} if met else None
                else:
                    candidate["metrics"] = None
                planned_folds = len(rolling["folds"])
                candidate["selectionEligible"] = (
                    candidate.get("candidateClass") == "learned_model"
                    and successful == planned_folds
                    and failed == 0
                    and candidate["metrics"] is not None
                )
                candidate["completionStatus"] = "complete" if (successful == planned_folds and failed == 0) else "incomplete"

            w2, ts2, tt2, ei2 = select_technical_winner(comparison["candidates"])
            assert w2 == actual_winner_id, (
                f"Expected actual winner {actual_winner_id!r} after override patching, got {w2!r}"
            )
            winner_cand2 = next(c for c in comparison["candidates"] if c["modelId"] == w2)
            runner_up2 = min(
                (c for c in comparison["candidates"] if c["modelId"] != w2 and c.get("selectionEligible")),
                key=lambda c: c["metrics"]["mae"],
                default=None,
            )
            wm2 = float(winner_cand2["metrics"]["mae"])
            rm2 = float(runner_up2["metrics"]["mae"]) if runner_up2 else wm2
            # Recompute fold wins/ties/losses
            wrecords = records_map2[w2]
            baseline_ids2 = {c["modelId"] for c in comparison["candidates"] if c.get("comparisonRole") == "baseline_only"}
            for candidate in comparison["candidates"]:
                better = tied = worse = 0
                for wr, cr in zip(wrecords, records_map2[candidate["modelId"]]):
                    if (
                        wr is not None
                        and cr is not None
                        and wr.get("absoluteError") is not None
                        and cr.get("absoluteError") is not None
                    ):
                        diff = cr["absoluteError"] - wr["absoluteError"]
                        if diff < -1e-9: better += 1
                        elif abs(diff) <= 1e-9: tied += 1
                        else: worse += 1
                candidate["foldWinsTiesLosses"] = {"better": better, "tied": tied, "worse": worse}
                cid = candidate["modelId"]
                if cid in baseline_ids2:
                    candidate["status"] = "baseline_only"
                elif not candidate.get("eligible", True):
                    candidate["status"] = "disqualified"
                elif not candidate["selectionEligible"]:
                    candidate["status"] = "failed"
                elif cid == w2:
                    candidate["status"] = "technical_winner"
                else:
                    candidate["status"] = "eligible_non_winner"
            comparison.update(
                technicalWinnerModelId=w2,
                winnerParameterSha256=winner_cand2["parametersSha256"],
                tieStage=ts2, tieResolutionSteps=tt2,
                selectionEligibleCandidateIds=ei2,
                selectionReason=(
                    f"{w2} had the lowest governed metric sequence among candidates "
                    f"completing all {len(rolling['folds'])} folds."
                ),
            )
            summary["technicalWinnerModelId"] = w2
            summary["candidates"] = comparison["candidates"]
            summary["selectionReason"] = comparison["selectionReason"]
            summary["tieStage"] = ts2
            recommendation.update(
                technicalWinnerModelId=w2,
                winnerParameterSha256=winner_cand2["parametersSha256"],
                evidenceInputs={
                    "winnerMae": wm2, "runnerUpMae": rm2,
                    "absoluteMaeGap": rm2 - wm2,
                    "relativeMaeGap": (rm2 - wm2) / rm2 if rm2 else 0.0,
                    "successfulFoldRatio": 1.0, "failedFoldCount": 0,
                    "clippingCount": winner_cand2["metrics"].get("clippingCount", 0),
                    "warningCount": winner_cand2["metrics"].get("warningCount", 0),
                    "candidateBreadth": len(comparison["candidates"]),
                    "tieBreakStageUsed": ts2,
                    "datasetFoldCount": len(rolling["folds"]),
                },
            )

        assessment_commit_sha = _rebuild_assessment_hashes(
            rolling_path, comparison_path, recommendation_path,
            summary_path, metadata_path, commit_path,
            rolling, comparison, recommendation, summary,
        )
        # Refresh from disk
        summary    = json.loads(summary_path.read_text())
        comparison = json.loads(comparison_path.read_text())
        selected   = next(c for c in summary["candidates"] if c["modelId"] == model_id)
        winner     = next(c for c in summary["candidates"] if c["modelId"] == summary["technicalWinnerModelId"])
        assert selected.get("selectionEligible"), (
            f"model_id={model_id!r} is still not eligible after override patching."
        )
        selection_type      = "eligible_non_winner_override"
        decision_type       = "approve_eligible_non_winner"
        candidate_status    = "eligible_non_winner"
        requires_override_ack = True
        override_reason     = "Governed eligible challenger override."

    # -------------------------------------------------------------------------
    # Build decision, authorization, approved-forecast job
    # -------------------------------------------------------------------------
    decision_id, authorization_id, job_id, run_id = [str(uuid.uuid4()) for _ in range(4)]
    created = iso_now()
    expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat().replace("+00:00", "Z")

    policy = json.loads(
        (repository_root / "config/deployments/dhaka_south/decision_policy.json").read_text()
    )
    decision_root = runtime / "decisions" / decision_id
    decision_root.mkdir(parents=True)

    decision: dict = {
        "schemaVersion": "2.0",
        "decisionId": decision_id,
        "assessmentId": assessment_job["assessmentId"],
        "assessmentCommitSha256": assessment_commit_sha,
        "assessmentSchemaVersion": "2.0",
        "assessmentSummarySha256": sha256_file(summary_path),
        "comparisonSha256": sha256_file(comparison_path),
        "recommendationSha256": summary["evidenceHashes"]["recommendationSha256"],
        "foldPlanSha256": summary["foldPlanSha256"],
        "assessmentLabelledRows": summary["labelledRows"],
        "assessmentPlannedFoldCount": summary["foldPolicy"]["plannedFoldCount"],
        "selectedEvaluationPeriod": summary["foldPolicy"]["selectedEvaluationPeriod"],
        "datasetId": summary["datasetId"],
        "deploymentId": "dhaka_south",
        "validationRecordSha256": summary["provenance"]["validationRecordSha256"],
        "assessmentPolicyId": policy["allowedAssessmentPolicyId"],
        "assessmentPolicyVersion": policy["allowedAssessmentPolicyVersion"],
        "assessmentPolicySha256": policy["allowedAssessmentPolicySha256"],
        "decisionPolicyId": policy["policyId"],
        "decisionPolicyVersion": policy["policyVersion"],
        "decisionPolicySha256": policy["policySha256"],
        "candidateRegistrySha256": policy["candidateRegistrySha256"],
        "featureOrderSha256": policy["featureOrderSha256"],
        "technicalWinnerModelId": winner["modelId"],
        "technicalWinnerParameterSha256": winner["parametersSha256"],
        "decision": decision_type,
        "selectionType": selection_type,
        "selectedModelId": selected["modelId"],
        "selectedModelFamily": selected["modelFamily"],
        "selectedModelParameterSha256": selected["parametersSha256"],
        "selectedModelPreprocessingIdentity": selected["preprocessingIdentity"],
        "selectedCandidateStatus": candidate_status,
        "decisionScope": "one_run",
        "operatorType": "trusted_internal_unverified",
        "operatorIdentifier": "p2-v2-one-run-fixture",
        "institutionalApproval": False,
        "technicalWinnerNotSelectedAcknowledged": True if requires_override_ack else False,
        "reason": override_reason if requires_override_ack else None,
        "limitationsAcknowledged": True,
        "uncertaintyLimitationsAcknowledged": True,
        "deploymentModelAdopted": False,
        "decisionStatus": (
            "approved_eligible_non_winner" if override else "approved_technical_winner"
        ),
        "forecastAuthorized": True,
        "authorizationId": authorization_id,
        "createdAt": created,
        "correlationId": str(uuid.uuid4()),
        "supersedesDecisionId": None,
        "supersessionStatus": "active",
    }

    atomic_json(decision_root / "decision.json", decision)

    decision_commit = {
        "schemaVersion": "2.0",
        "decisionId": decision_id,
        "assessmentId": assessment_job["assessmentId"],
        "decisionSha256": sha256_file(decision_root / "decision.json"),
        "assessmentCommitSha256": assessment_commit_sha,
        "assessmentSchemaVersion": "2.0",
        "assessmentSummarySha256": sha256_file(summary_path),
        "assessmentPolicyId": policy["allowedAssessmentPolicyId"],
        "assessmentPolicyVersion": policy["allowedAssessmentPolicyVersion"],
        "assessmentPolicySha256": policy["allowedAssessmentPolicySha256"],
        "decisionPolicyId": policy["policyId"],
        "decisionPolicyVersion": policy["policyVersion"],
        "decisionPolicySha256": policy["policySha256"],
        "foldPlanSha256": summary["foldPlanSha256"],
        "assessmentLabelledRows": summary["labelledRows"],
        "assessmentPlannedFoldCount": summary["foldPolicy"]["plannedFoldCount"],
        "status": "committed",
        "committedAt": created,
        "latestPointerUpdated": False,
        "deploymentProfileModified": False,
    }
    atomic_json(decision_root / "commit.json", decision_commit)
    decision_commit_sha = sha256_file(decision_root / "commit.json")

    auth_root = runtime / "authorizations" / authorization_id
    auth_root.mkdir(parents=True)
    authorization = {
        "schemaVersion": "2.0",
        "authorizationId": authorization_id,
        "decisionId": decision_id,
        "decisionCommitSha256": decision_commit_sha,
        "assessmentId": assessment_job["assessmentId"],
        "assessmentCommitSha256": assessment_commit_sha,
        "assessmentPolicyId": policy["allowedAssessmentPolicyId"],
        "assessmentPolicyVersion": policy["allowedAssessmentPolicyVersion"],
        "assessmentPolicySha256": policy["allowedAssessmentPolicySha256"],
        "decisionPolicyId": policy["policyId"],
        "decisionPolicyVersion": policy["policyVersion"],
        "decisionPolicySha256": policy["policySha256"],
        "datasetId": summary["datasetId"],
        "deploymentId": "dhaka_south",
        "selectedModelId": selected["modelId"],
        "selectedModelFamily": selected["modelFamily"],
        "selectedModelParameterSha256": selected["parametersSha256"],
        "selectedModelPreprocessingIdentity": selected["preprocessingIdentity"],
        "candidateRegistrySha256": policy["candidateRegistrySha256"],
        "featureOrderSha256": policy["featureOrderSha256"],
        "selectionType": selection_type,
        "technicalWinnerModelId": winner["modelId"],
        "technicalWinnerNotSelectedAcknowledged": requires_override_ack,
        "uncertaintyLimitationsAcknowledged": True,
        "deploymentModelAdopted": False,
        "assessmentLabelledRows": summary["labelledRows"],
        "assessmentPlannedFoldCount": summary["foldPolicy"]["plannedFoldCount"],
        "foldPlanSha256": summary["foldPlanSha256"],
        "workflowMode": "approved_assessment_forecast",
        "scope": "one_run",
        "initialStatus": "available",
        "createdAt": created,
        "expiresAt": expires,
        "policyId": policy["policyId"],
        "policyVersion": policy["policyVersion"],
        "policySha256": policy["policySha256"],
    }
    atomic_json(auth_root / "authorization.json", authorization)
    atomic_json(auth_root / "commit.json", {
        "schemaVersion": "1.0",
        "authorizationId": authorization_id,
        "decisionId": decision_id,
        "authorizationSha256": sha256_file(auth_root / "authorization.json"),
        "decisionCommitSha256": decision_commit_sha,
        "status": "committed",
        "committedAt": created,
    })
    authorization_commit_sha = sha256_file(auth_root / "commit.json")

    state = runtime / "authorization-state" / authorization_id
    state.mkdir(parents=True)
    atomic_json(state / "reservation.json", {
        "schemaVersion": "1.0",
        "authorizationId": authorization_id,
        "decisionId": decision_id,
        "eventType": "reserved",
        "eventId": str(uuid.uuid4()),
        "createdAt": created,
        "jobId": job_id,
        "runId": run_id,
    })

    job = {
        "schemaVersion": "1.0",
        "jobKind": "approved_forecast",
        "jobId": job_id,
        "runId": run_id,
        "decisionId": decision_id,
        "decisionCommitSha256": decision_commit_sha,
        "authorizationId": authorization_id,
        "assessmentId": assessment_job["assessmentId"],
        "assessmentCommitSha256": assessment_commit_sha,
        "workspaceId": assessment_job["assessmentId"],
        "datasetId": summary["datasetId"],
        "deploymentId": "dhaka_south",
        "selectedModelId": selected["modelId"],
        "selectedModelParameterSha256": selected["parametersSha256"],
        "workflowMode": "approved_assessment_forecast",
        "validationRecordSha256": summary["provenance"]["validationRecordSha256"],
        "status": "queued",
        "progress": "queued",
        "createdAt": created,
        "claimedAt": None,
        "startedAt": None,
        "updatedAt": created,
        "completedAt": None,
        "heartbeatAt": None,
        "workerId": None,
        "processId": None,
        "timeoutSeconds": 600,
        "retryCount": 0,
        "error": None,
        "committedRunId": None,
    }
    atomic_json(runtime / "jobs/pending" / f"{job_id}.json", job)
    if not run_once(runtime, "lifecycle-approved"):
        raise AssertionError("approved forecast job did not execute")

    run_dir = runtime / "runs" / run_id
    if not run_dir.exists():
        # Capture stderr from the failed job for a clear error
        failed_jobs = list((runtime / "jobs/failed").glob("*.json"))
        err_detail = ""
        if failed_jobs:
            try:
                fj = json.loads(failed_jobs[0].read_text())
                err_detail = f": {fj.get('error', {})}"
            except Exception:
                pass
        raise AssertionError(
            f"Approved forecast run directory missing for model '{selected['modelId']}'{err_detail}"
        )

    return {
        "runtime": runtime,
        "assessmentId": assessment_job["assessmentId"],
        "decisionId": decision_id,
        "authorizationId": authorization_id,
        "runId": run_id,
        "jobId": job_id,
        "modelId": selected["modelId"],
        "assessmentCommitSha256": assessment_commit_sha,
        "decisionCommitSha256": decision_commit_sha,
        "authorizationCommitSha256": authorization_commit_sha,
    }
