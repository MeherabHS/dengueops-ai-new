from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))

from runtime_commit import atomic_json, sha256_file
from runtime_worker import run_once
from tests.test_runtime_assessment_commit import build_ready_assessment_runtime, iso_now

MODELS = ("ridge_regression","poisson_regression","random_forest","gradient_boosting","elastic_net",
          "negative_binomial_regression","extra_trees","hist_gradient_boosting")


def prepare(runtime: Path, assessment_id: str, model_id: str) -> tuple[str, str]:
    assessment = runtime / "assessments" / assessment_id
    summary_path = assessment / "artifacts/assessment_summary.json"
    comparison_path = assessment / "artifacts/candidate_model_comparison.json"
    summary, comparison = json.loads(summary_path.read_text()), json.loads(comparison_path.read_text())
    selected = next(value for value in summary["candidates"] if value["modelId"] == model_id)
    compared = next(value for value in comparison["candidates"] if value["modelId"] == model_id)
    planned = summary["foldPolicy"]["plannedFoldCount"]
    if not selected["selectionEligible"]:
        for value in (selected, compared):
            value.update(successfulFolds=planned, failedFolds=0, selectionEligible=True,
                         completionStatus="complete", status="eligible_non_winner")
        summary["candidates"] = comparison["candidates"]
        atomic_json(comparison_path, comparison)
        summary["evidenceHashes"]["candidateComparisonSha256"] = sha256_file(comparison_path)
        atomic_json(summary_path, summary)
        commit_path = assessment / "metadata/commit.json"
        commit = json.loads(commit_path.read_text())
        commit["artifactHashes"]["candidate_model_comparison.json"] = sha256_file(comparison_path)
        commit["artifactHashes"]["assessment_summary.json"] = sha256_file(summary_path)
        atomic_json(commit_path, commit)
    summary, comparison = json.loads(summary_path.read_text()), json.loads(comparison_path.read_text())
    selected = next(value for value in summary["candidates"] if value["modelId"] == model_id)
    winner = next(value for value in summary["candidates"] if value["modelId"] == summary["technicalWinnerModelId"])
    decision_id, authorization_id, job_id, run_id = [str(uuid.uuid4()) for _ in range(4)]
    created, expires = iso_now(), (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat().replace("+00:00","Z")
    assessment_commit = sha256_file(assessment / "metadata/commit.json")
    policy = json.loads((ROOT / "config/deployments/dhaka_south/decision_policy.json").read_text())
    override = model_id != summary["technicalWinnerModelId"]
    decision = {"schemaVersion":"2.0","decisionId":decision_id,"assessmentId":assessment_id,"assessmentCommitSha256":assessment_commit,
        "assessmentSchemaVersion":"2.0","assessmentSummarySha256":sha256_file(summary_path),"comparisonSha256":sha256_file(comparison_path),
        "recommendationSha256":summary["evidenceHashes"]["recommendationSha256"],"foldPlanSha256":summary["foldPlanSha256"],
        "assessmentLabelledRows":summary["labelledRows"],"assessmentPlannedFoldCount":planned,"selectedEvaluationPeriod":summary["foldPolicy"]["selectedEvaluationPeriod"],
        "datasetId":summary["datasetId"],"deploymentId":"dhaka_south","validationRecordSha256":summary["provenance"]["validationRecordSha256"],
        "assessmentPolicyId":"RUNTIME.DATASET_ASSESSMENT.GOVERNANCE","assessmentPolicyVersion":"p2-v2","assessmentPolicySha256":policy["allowedAssessmentPolicySha256"],
        "decisionPolicyId":policy["policyId"],"decisionPolicyVersion":"p2-v2","decisionPolicySha256":policy["policySha256"],
        "candidateRegistrySha256":policy["candidateRegistrySha256"],"featureOrderSha256":policy["featureOrderSha256"],
        "technicalWinnerModelId":winner["modelId"],"technicalWinnerParameterSha256":winner["parametersSha256"],
        "decision":"approve_eligible_non_winner" if override else "approve_technical_winner",
        "selectionType":"eligible_non_winner_override" if override else "technical_winner","selectedModelId":model_id,
        "selectedModelFamily":selected["modelFamily"],"selectedModelParameterSha256":selected["parametersSha256"],
        "selectedModelPreprocessingIdentity":selected["preprocessingIdentity"],"selectedCandidateStatus":"eligible_non_winner" if override else "technical_winner",
        "decisionScope":"one_run","operatorType":"trusted_internal_unverified","operatorIdentifier":"phase-b-test-operator",
        "institutionalApproval":False,"reason":"Governed eligible challenger." if override else "Governed technical winner.",
        "technicalWinnerNotSelectedAcknowledged":override,"uncertaintyLimitationsAcknowledged":True,"deploymentModelAdopted":False,
        "limitationsAcknowledged":True,"decisionStatus":"approved_eligible_non_winner" if override else "approved_technical_winner",
        "forecastAuthorized":True,"authorizationId":authorization_id,"createdAt":created,"correlationId":str(uuid.uuid4()),
        "supersedesDecisionId":None,"supersessionStatus":"active"}
    errors=list(Draft202012Validator(json.loads((ROOT/"config/runtime_decision.schema.json").read_text()),format_checker=FormatChecker()).iter_errors(decision))
    if errors: raise AssertionError(errors[0].message)
    decision_root=runtime/"decisions"/decision_id;decision_root.mkdir(parents=True);atomic_json(decision_root/"decision.json",decision)
    decision_commit={"schemaVersion":"2.0","decisionId":decision_id,"assessmentId":assessment_id,"decisionSha256":sha256_file(decision_root/"decision.json"),
        "assessmentCommitSha256":assessment_commit,"assessmentSchemaVersion":"2.0","assessmentSummarySha256":sha256_file(summary_path),
        "assessmentPolicyId":decision["assessmentPolicyId"],"assessmentPolicyVersion":"p2-v2","assessmentPolicySha256":decision["assessmentPolicySha256"],
        "decisionPolicyId":policy["policyId"],"decisionPolicyVersion":"p2-v2","decisionPolicySha256":policy["policySha256"],
        "foldPlanSha256":summary["foldPlanSha256"],"assessmentLabelledRows":summary["labelledRows"],"assessmentPlannedFoldCount":planned,
        "status":"committed","committedAt":created,"latestPointerUpdated":False,"deploymentProfileModified":False}
    atomic_json(decision_root/"commit.json",decision_commit);decision_commit_sha=sha256_file(decision_root/"commit.json")
    authorization={"schemaVersion":"2.0","authorizationId":authorization_id,"decisionId":decision_id,"decisionCommitSha256":decision_commit_sha,
        "assessmentId":assessment_id,"assessmentCommitSha256":assessment_commit,"assessmentPolicyId":decision["assessmentPolicyId"],
        "assessmentPolicyVersion":"p2-v2","assessmentPolicySha256":decision["assessmentPolicySha256"],"decisionPolicyId":policy["policyId"],
        "decisionPolicyVersion":"p2-v2","decisionPolicySha256":policy["policySha256"],"datasetId":summary["datasetId"],"deploymentId":"dhaka_south",
        "selectedModelId":model_id,"selectedModelFamily":selected["modelFamily"],"selectedModelParameterSha256":selected["parametersSha256"],
        "selectedModelPreprocessingIdentity":selected["preprocessingIdentity"],"candidateRegistrySha256":policy["candidateRegistrySha256"],
        "featureOrderSha256":policy["featureOrderSha256"],"selectionType":decision["selectionType"],"technicalWinnerModelId":winner["modelId"],
        "technicalWinnerNotSelectedAcknowledged":override,"uncertaintyLimitationsAcknowledged":True,"deploymentModelAdopted":False,
        "assessmentLabelledRows":summary["labelledRows"],"assessmentPlannedFoldCount":planned,"foldPlanSha256":summary["foldPlanSha256"],
        "workflowMode":"approved_assessment_forecast","scope":"one_run","initialStatus":"available","createdAt":created,"expiresAt":expires,
        "policyId":policy["policyId"],"policyVersion":"p2-v2","policySha256":policy["policySha256"]}
    auth_root=runtime/"authorizations"/authorization_id;auth_root.mkdir(parents=True);atomic_json(auth_root/"authorization.json",authorization)
    atomic_json(auth_root/"commit.json",{"schemaVersion":"1.0","authorizationId":authorization_id,"decisionId":decision_id,
        "authorizationSha256":sha256_file(auth_root/"authorization.json"),"decisionCommitSha256":decision_commit_sha,"status":"committed","committedAt":created})
    state=runtime/"authorization-state"/authorization_id;state.mkdir(parents=True);atomic_json(state/"reservation.json",{"schemaVersion":"1.0","authorizationId":authorization_id,
        "decisionId":decision_id,"eventType":"reserved","eventId":str(uuid.uuid4()),"createdAt":created,"jobId":job_id,"runId":run_id})
    job={"schemaVersion":"1.0","jobKind":"approved_forecast","jobId":job_id,"runId":run_id,"decisionId":decision_id,
        "decisionCommitSha256":decision_commit_sha,"authorizationId":authorization_id,"assessmentId":assessment_id,"assessmentCommitSha256":assessment_commit,
        "workspaceId":assessment_id,"datasetId":summary["datasetId"],"deploymentId":"dhaka_south","selectedModelId":model_id,
        "selectedModelParameterSha256":selected["parametersSha256"],"workflowMode":"approved_assessment_forecast",
        "validationRecordSha256":summary["provenance"]["validationRecordSha256"],"status":"queued","progress":"queued","createdAt":created,
        "claimedAt":None,"startedAt":None,"updatedAt":created,"completedAt":None,"heartbeatAt":None,"workerId":None,"processId":None,
        "timeoutSeconds":600,"retryCount":0,"error":None,"committedRunId":None}
    atomic_json(runtime/"jobs/pending"/f"{job_id}.json",job)
    return job_id,run_id


class ProductV2OneRunForecastTests(unittest.TestCase):
    def test_all_eight_models_execute_without_adopting_assignment(self):
        profile_before=hashlib.sha256((ROOT/"config/deployments/dhaka_south/profile.json").read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            base,_,_,assessment_job=build_ready_assessment_runtime(Path(directory)/"base",source_rows=164)
            self.assertTrue(run_once(base,"phase-b-assessment"))
            for model_id in MODELS:
                with self.subTest(model=model_id):
                    runtime=Path(directory)/model_id/"runtime";shutil.copytree(base,runtime,copy_function=shutil.copyfile)
                    pointer=runtime/"deployments/dhaka_south/model-assignment/latest.json"
                    self.assertFalse(pointer.exists())
                    job_id,run_id=prepare(runtime,assessment_job["assessmentId"],model_id)
                    self.assertTrue(run_once(runtime,f"phase-b-{model_id}"))
                    completed=json.loads((runtime/"jobs/completed"/f"{job_id}.json").read_text())
                    self.assertEqual(completed["committedRunId"],run_id)
                    output=json.loads((runtime/"runs"/run_id/"artifacts/forecast_output.json").read_text())
                    uncertainty=json.loads((runtime/"runs"/run_id/"artifacts/forecast_uncertainty.json").read_text())
                    self.assertEqual(output["selectedModelId"],model_id)
                    self.assertEqual(output["forecastPresentationMode"],"point_only")
                    self.assertEqual(output["calibrationStatus"],"pending")
                    self.assertFalse(output["deploymentModelAdopted"])
                    self.assertIsNone(uncertainty["lowerRaw"]);self.assertIsNone(uncertainty["upperRaw"])
                    self.assertFalse(pointer.exists())
        self.assertEqual(hashlib.sha256((ROOT/"config/deployments/dhaka_south/profile.json").read_bytes()).hexdigest(),profile_before)


if __name__ == "__main__":
    unittest.main()
