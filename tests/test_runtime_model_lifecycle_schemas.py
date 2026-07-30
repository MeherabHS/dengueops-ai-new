import copy,json,tempfile,unittest,uuid
from pathlib import Path
from jsonschema import Draft202012Validator
from tests.test_runtime_model_lifecycle import lifecycle_job
from tests.test_runtime_quick_forecast import build_ready_runtime
from runtime_active_model import FEATURE_SHA,PARAMETER_SHA,PROFILE_SHA,QUICK_SHA,REGISTRY_SHA,resolve_historical_active_model_p2_v1
from runtime_model_lifecycle import prepare_bundle
ROOT=Path(__file__).resolve().parents[1]
class LifecycleSchemaTests(unittest.TestCase):
 def _jobs(self,root):
  sha="0"*64;context={"evidenceContextStatus":"verified_monitoring_and_degradation","expectedMonitoringLatestSha256":sha,"expectedMonitoringSummarySha256":sha,"expectedMonitoringIncludedOutcomeSetSha256":sha,"expectedDegradationLatestSha256":sha,"expectedDegradationEvidenceCommitSha256":sha,"expectedDegradationEvidenceSha256":sha}
  promotion={"expectedAssessmentCommitSha256":sha,"expectedDecisionCommitSha256":sha,"expectedAuthorizationCommitSha256":sha,"expectedApprovedForecastCommitSha256":sha,"expectedOutcomeCommitSha256":sha,**{key:value for key,value in context.items() if key!="evidenceContextStatus"}}
  values=[lifecycle_job(root,expectedProfileSha256=PROFILE_SHA)[0],lifecycle_job(root,"retain_current_model",**context)[0],lifecycle_job(root,"promote_selected_model",**promotion)[0],lifecycle_job(root,"rollback_previous_assignment",expectedAssignmentPointerState="present",expectedAssignmentPointerSha256=sha)[0],lifecycle_job(root,"defer",**context)[0],lifecycle_job(root,"defer",evidenceContextStatus="explicit_no_evidence")[0],lifecycle_job(root,"reject",**context)[0],lifecycle_job(root,"reject",evidenceContextStatus="verified_assessment_and_decision",expectedAssessmentCommitSha256=sha,expectedDecisionCommitSha256=sha)[0]]
  return values
 def _bundles(self,root):
  jobs=self._jobs(root);fallback=resolve_historical_active_model_p2_v1(repository_root=ROOT,runtime_root=root);prior=str(uuid.uuid4());active={**fallback,"authoritySource":"committed_assignment","assignmentId":prior,"assignmentCommitSha256":"1"*64,"authoritySnapshotSha256":"2"*64}
  verified_promotion={"selectedModelId":"random_forest","selectedModelFamily":"RandomForestRegressor","selectedModelParameterSha256":PARAMETER_SHA,"candidateRegistrySha256":REGISTRY_SHA,"featureOrderSha256":FEATURE_SHA,"sourceAssessmentId":str(uuid.uuid4()),"sourceAssessmentCommitSha256":"0"*64,"sourceDecisionId":str(uuid.uuid4()),"sourceDecisionArtifactSha256":"0"*64,"sourceDecisionCommitSha256":"0"*64,"sourceAuthorizationId":str(uuid.uuid4()),"sourceAuthorizationRecordSha256":"0"*64,"sourceAuthorizationCommitSha256":"0"*64,"sourceAuthorizationConsumptionSha256":"0"*64,"sourceApprovedForecastId":str(uuid.uuid4()),"sourceApprovedForecastCommitSha256":"0"*64,"sourceOutcomeId":str(uuid.uuid4()),"sourceOutcomeCommitSha256":"0"*64,"sourceMonitoringLatestSha256":"0"*64,"sourceMonitoringSummarySha256":"0"*64,"sourceMonitoringIncludedOutcomeSetSha256":"0"*64,"sourceDegradationLatestSha256":"0"*64,"sourceDegradationEvidenceId":str(uuid.uuid4()),"sourceDegradationEvidenceCommitSha256":"0"*64,"sourceDegradationEvidenceSha256":"0"*64,"assessmentReferenceCohortId":"cohort","assessmentReferenceDimensionId":"dimension"}
  verified_context={"evidenceContextStatus":"verified_monitoring_and_degradation"};verified_rollback={"assignment":{"assignmentId":str(uuid.uuid4())},"commitSha256":"3"*64}
  verified=[{"expectedProfileSha256":PROFILE_SHA},verified_context,verified_promotion,verified_rollback,verified_context,{"evidenceContextStatus":"explicit_no_evidence"},verified_context,{"evidenceContextStatus":"verified_assessment_and_decision"}]
  bundles=[]
  for job,evidence in zip(jobs,verified):bundles.append(prepare_bundle(ROOT,root,job,active if job["action"]=="rollback_previous_assignment" else fallback,evidence))
  return jobs,bundles
 def test_schemas_are_strict_and_valid(self):
  for name in ["runtime_job.schema.json","runtime_model_lifecycle_policy.schema.json","runtime_model_lifecycle_decision.schema.json","runtime_model_lifecycle_decision_commit.schema.json","runtime_model_assignment.schema.json","runtime_model_assignment_commit.schema.json","runtime_model_assignment_latest.schema.json"]:
   s=json.loads((ROOT/"config"/name).read_text());Draft202012Validator.check_schema(s);self.assertIn("additionalProperties",json.dumps(s))
 def test_policy_schema_rejects_extra(self):
  s=json.loads((ROOT/"config/runtime_model_lifecycle_policy.schema.json").read_text());p=json.loads((ROOT/"config/deployments/dhaka_south/model_lifecycle_policy.json").read_text());p["threshold"]=1;self.assertTrue(list(Draft202012Validator(s).iter_errors(p)))
 def test_lifecycle_jobs_are_action_disjoint(self):
  schema=json.loads((ROOT/"config/runtime_job.schema.json").read_text());validator=Draft202012Validator(schema)
  with tempfile.TemporaryDirectory() as directory:
   job,_=lifecycle_job(Path(directory),expectedProfileSha256=PROFILE_SHA);self.assertFalse(list(validator.iter_errors(job)));job["expectedMonitoringLatestSha256"]="0"*64;self.assertTrue(list(validator.iter_errors(job)))
 def test_foreign_field_matrix_rejects_every_hybrid(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);jobs,bundles=self._bundles(root)
   groups=[("runtime_job.schema.json",jobs),("runtime_model_lifecycle_decision.schema.json",[value["decision"] for value in bundles]),("runtime_model_lifecycle_decision_commit.schema.json",[value["decisionCommit"] for value in bundles])]
   for schema_name,fixtures in groups:
    validator=Draft202012Validator(json.loads((ROOT/"config"/schema_name).read_text()))
    for target in fixtures:
     self.assertFalse(list(validator.iter_errors(target)),schema_name)
     for source in fixtures:
      for field in set(source)-set(target):
       hybrid={**target,field:source[field]}
       self.assertTrue(list(validator.iter_errors(hybrid)),f"{schema_name}:{target['action']} accepted {field}")
 def test_assignment_branches_are_closed_and_committed_names_do_not_leak(self):
  with tempfile.TemporaryDirectory() as directory:
   _,bundles=self._bundles(Path(directory));assignments=[value["assignment"] for value in bundles if value["assignment"]];commits=[value["assignmentCommit"] for value in bundles if value["assignmentCommit"]]
   for schema_name,fixtures in (("runtime_model_assignment.schema.json",assignments),("runtime_model_assignment_commit.schema.json",commits)):
    validator=Draft202012Validator(json.loads((ROOT/"config"/schema_name).read_text()))
    for target in fixtures:
     self.assertFalse(list(validator.iter_errors(target)))
     for source in fixtures:
      for field in set(source)-set(target):self.assertTrue(list(validator.iter_errors({**target,field:source[field]})),f"{schema_name} accepted {field}")
   for value in [item for bundle in bundles for item in (bundle["decision"],bundle["decisionCommit"])]:
    self.assertFalse(any(key.startswith("expected") and key not in {"expectedAssignmentPointerState","expectedAssignmentPointerSha256"} for key in value))
 def test_assignment_latest_action_matrix_is_exactly_disjoint(self):
  schema=json.loads((ROOT/"config/runtime_model_assignment_latest.schema.json").read_text());validator=Draft202012Validator(schema)
  assignment_id=str(uuid.uuid4());decision_id=str(uuid.uuid4());sha="0"*64
  common={"schemaVersion":"1.0","deploymentId":"dhaka_south","assignmentId":assignment_id,"assignedModelId":"random_forest","modelFamily":"RandomForestRegressor","parameterSha256":PARAMETER_SHA,"featureOrderSha256":FEATURE_SHA,"candidateRegistrySha256":REGISTRY_SHA,"policyId":"RUNTIME.MODEL_LIFECYCLE.DECISION","policyVersion":"p2-v1","policySha256":"570a931bc2e98ca5cada78c5fe891e699e43e7c9f513b8df2257c06f1261b7bb","lifecycleDecisionId":decision_id,"lifecycleDecisionCommitSha256":sha,"assignmentCommitSha256":sha,"assignmentPath":f"model-lifecycle/{decision_id}/artifacts/model_assignment.json","assignmentSha256":sha,"lifecycleDecisionPath":f"model-lifecycle/{decision_id}/artifacts/lifecycle_decision.json","lifecycleDecisionSha256":sha,"publishedAt":"2026-01-01T00:00:00Z","activeModelAuthority":"committed_assignment","automaticAction":False}
  prior_id=str(uuid.uuid4())
  fixtures=[{**common,"assignmentAction":"bootstrap","priorAssignmentId":None,"priorAssignmentCommitSha256":None},{**common,"assignmentAction":"promote","priorAssignmentId":prior_id,"priorAssignmentCommitSha256":"1"*64},{**common,"assignmentAction":"rollback","priorAssignmentId":prior_id,"priorAssignmentCommitSha256":"1"*64}]
  branches=[Draft202012Validator({**branch,"$defs":schema["$defs"]}) for branch in schema["oneOf"]]
  for fixture in fixtures:
   self.assertFalse(list(validator.iter_errors(fixture)))
   self.assertEqual(sum(not list(branch.iter_errors(fixture)) for branch in branches),1)
   self.assertTrue(list(validator.iter_errors({**fixture,"assignmentAction":"retain"})))
   self.assertTrue(list(validator.iter_errors({**fixture,"foreignEvidenceSha256":sha})))
   for missing in ("assignmentCommitSha256","lifecycleDecisionCommitSha256"):
    invalid=dict(fixture);invalid.pop(missing);self.assertTrue(list(validator.iter_errors(invalid)))
  bootstrap,promotion,rollback=fixtures
  self.assertTrue(list(validator.iter_errors({**bootstrap,"priorAssignmentId":prior_id,"priorAssignmentCommitSha256":"1"*64})))
  self.assertFalse(list(validator.iter_errors({**promotion,"priorAssignmentId":None,"priorAssignmentCommitSha256":None})))
  self.assertTrue(list(validator.iter_errors({**promotion,"priorAssignmentId":None})))
  self.assertTrue(list(validator.iter_errors({**rollback,"priorAssignmentId":None,"priorAssignmentCommitSha256":None})))
 def test_quick_jobs_are_historical_or_complete_authority_records(self):
  schema=json.loads((ROOT/"config/runtime_job.schema.json").read_text());validator=Draft202012Validator(schema)
  with tempfile.TemporaryDirectory() as directory:
   runtime,_workspace,_path,job=build_ready_runtime(Path(directory),validation_mode="assess_dataset");self.assertFalse(list(validator.iter_errors(job)));job["authoritySnapshotSha256"]="0"*64;self.assertTrue(list(validator.iter_errors(job)))
   authority=resolve_historical_active_model_p2_v1(repository_root=ROOT,runtime_root=runtime);job.update({"activeModelAuthoritySource":authority["authoritySource"],"authoritySnapshotSha256":authority["authoritySnapshotSha256"],"historicalProfileSha256":PROFILE_SHA,"resolvedModelId":"random_forest","resolvedModelFamily":"RandomForestRegressor","resolvedModelParameterSha256":PARAMETER_SHA,"resolvedFeatureOrderSha256":FEATURE_SHA,"resolvedCandidateRegistrySha256":REGISTRY_SHA,"quickPolicyId":"RUNTIME.QUICK_FORECAST.COMPATIBILITY","quickPolicyVersion":"p1.4f-v1","quickPolicySha256":QUICK_SHA});self.assertFalse(list(validator.iter_errors(job)))
 def test_p2_quick_job_branches_are_closed_and_reject_mixed_contracts(self):
  schema=json.loads((ROOT/"config/runtime_job.schema.json").read_text());validator=Draft202012Validator(schema);sha="0"*64
  with tempfile.TemporaryDirectory() as directory:
   _runtime,_workspace,_path,p1=build_ready_runtime(Path(directory),validation_mode="assess_dataset")
   p2={**p1,"jobKind":"quick_forecast","schemaVersion":"2.0","policyVersion":"p2-v1","policySha256":"4a6f166d037ab4c69df980549626d993db473bcec325fa2a68dbe5f8485a757e","activeModelAuthoritySource":"committed_assignment","authoritySnapshotSha256":sha,"assignmentId":str(uuid.uuid4()),"assignmentCommitSha256":sha,"assignmentAction":"assign_selected_model","resolvedModelId":"ridge_regression","resolvedModelFamily":"Ridge","resolvedModelParameterSha256":"f59e0d298750b54d9ab8312c6a68a4eaf4910bea81042dd3a1c4711dcb307e5b","resolvedPreprocessingIdentity":"9a666eb944a664443f4141b148eefb109cf3894674076df8f163d0d835474645","resolvedCandidateRegistrySha256":"74cb3635c5e211874ee5ad23196fc95bfdfbdb5c6438cc3d060f0b9ff49acfa0","resolvedFeatureOrderSha256":FEATURE_SHA,"lifecyclePolicyId":"RUNTIME.MODEL_LIFECYCLE.DECISION","lifecyclePolicyVersion":"p2-v2","lifecyclePolicySha256":"294b7949adecc39b284adaa198db47109ee4b1cc39259e87bc9073e1bff93b64","quickPolicyId":"RUNTIME.QUICK_FORECAST.COMPATIBILITY","quickPolicyVersion":"p2-v1","quickPolicySha256":"4a6f166d037ab4c69df980549626d993db473bcec325fa2a68dbe5f8485a757e"}
   self.assertFalse(list(validator.iter_errors(p2)))
   p21={**p2,"schemaVersion":"2.1","policyVersion":"p2-v2","policySha256":"09c338d56737ba35b5a0db82c97a7e26222297dfbb07cba36bf0e5f831b9adc2","resolvedCandidateRegistrySha256":"e6fd8aff5d092f7a9e112647515349d7aed43b21f5d78d97b8f988d492ab0226","lifecyclePolicyVersion":"p2-v3","lifecyclePolicySha256":"ae50f6e29ab0caba16401b5314c7d26c75658887d78a36c0b0d7c029a5b6a86a","quickPolicyVersion":"p2-v2","quickPolicySha256":"09c338d56737ba35b5a0db82c97a7e26222297dfbb07cba36bf0e5f831b9adc2"}
   self.assertFalse(list(validator.iter_errors(p21)))
   for missing in ("assignmentCommitSha256","lifecyclePolicySha256","resolvedPreprocessingIdentity","authoritySnapshotSha256"):
    for valid in (p2,p21):
     invalid=dict(valid);invalid.pop(missing);self.assertTrue(list(validator.iter_errors(invalid)),f"{valid['schemaVersion']}:{missing}")
   legacy=dict(p2);legacy.pop("assignmentCommitSha256");legacy["commitSha256"]=sha;self.assertTrue(list(validator.iter_errors(legacy)))
   self.assertTrue(list(validator.iter_errors({**p1,"resolvedPreprocessingIdentity":sha})))
   historical_authority={**p1,"activeModelAuthoritySource":"historical_profile_fallback_pending_explicit_bootstrap","authoritySnapshotSha256":sha,"historicalProfileSha256":PROFILE_SHA,"resolvedModelId":"random_forest","resolvedModelFamily":"RandomForestRegressor","resolvedModelParameterSha256":PARAMETER_SHA,"resolvedFeatureOrderSha256":FEATURE_SHA,"resolvedCandidateRegistrySha256":REGISTRY_SHA,"quickPolicyId":"RUNTIME.QUICK_FORECAST.COMPATIBILITY","quickPolicyVersion":"p1.4f-v1","quickPolicySha256":QUICK_SHA}
   self.assertFalse(list(validator.iter_errors(historical_authority)))
   self.assertTrue(list(validator.iter_errors({**historical_authority,"schemaVersion":"2.0","policyVersion":"p2-v1","policySha256":p2["policySha256"]})))
 def test_baseline_and_alternate_rf_identites_fail_every_artifact_boundary(self):
  with tempfile.TemporaryDirectory() as directory:
   jobs,bundles=self._bundles(Path(directory));promotion_job=jobs[2];promotion=bundles[2]
   job_validator=Draft202012Validator(json.loads((ROOT/"config/runtime_job.schema.json").read_text()))
   decision_validator=Draft202012Validator(json.loads((ROOT/"config/runtime_model_lifecycle_decision.schema.json").read_text()))
   assignment_validator=Draft202012Validator(json.loads((ROOT/"config/runtime_model_assignment.schema.json").read_text()))
   for model_id in ("previous_week_naive","moving_average_4w","seasonal_naive_52w","alternate_random_forest"):
    self.assertTrue(list(job_validator.iter_errors({**promotion_job,"selectedModelId":model_id})))
    self.assertTrue(list(decision_validator.iter_errors({**promotion["decision"],"selectedModelId":model_id})))
    self.assertTrue(list(assignment_validator.iter_errors({**promotion["assignment"],"assignedModelId":model_id})))
   for field,value in (("selectedModelFamily","AlternateRandomForest"),("selectedParameterSha256","0"*64)):
    self.assertTrue(list(decision_validator.iter_errors({**promotion["decision"],field:value})))
   for field,value in (("modelFamily","AlternateRandomForest"),("parameterSha256","0"*64),("assignedModelId","random_forest_alternate")):
    self.assertTrue(list(assignment_validator.iter_errors({**promotion["assignment"],field:value})))
if __name__=="__main__":unittest.main()
