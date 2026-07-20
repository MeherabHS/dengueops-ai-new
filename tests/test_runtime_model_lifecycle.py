import json
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"analytics"))
from runtime_active_model import PROFILE_SHA,ActiveModelError,resolve_active_model
from runtime_model_lifecycle import ACKS,execute
from runtime_model_lifecycle_commit import commit_lifecycle
from runtime_model_lifecycle_policy import POLICY_SHA256
from runtime_commit import atomic_json


def lifecycle_job(root:Path,action="bootstrap_historical_profile",decision_id=None,**fields):
    now="2026-07-17T00:00:00Z"
    job={"schemaVersion":"1.0","jobKind":"model_lifecycle","jobId":str(uuid.uuid4()),"lifecycleDecisionId":decision_id or str(uuid.uuid4()),"deploymentId":"dhaka_south","geography":{"level":"city","id":"BGD-DHAKA-SOUTH","name":"Dhaka South"},"workflowMode":"model_lifecycle","policyId":"RUNTIME.MODEL_LIFECYCLE.DECISION","policyVersion":"p2-v1","policySha256":POLICY_SHA256,"action":action,"operatorIdentifier":"test-operator","reason":"Explicit isolated lifecycle test.",**ACKS,"expectedAssignmentPointerState":"absent","expectedAssignmentPointerSha256":None,"status":"running","progress":"running","createdAt":now,"claimedAt":now,"startedAt":now,"updatedAt":now,"completedAt":None,"heartbeatAt":now,"workerId":"test","processId":1,"timeoutSeconds":60,"retryCount":0,"error":None,"committedLifecycleDecisionId":None}
    job.update(fields)
    path=root/f"{job['jobId']}.json";path.write_text(json.dumps(job),encoding="utf-8")
    return job,path


class LifecycleTests(unittest.TestCase):
    def test_isolated_bootstrap_and_resolver(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime=Path(directory);job,path=lifecycle_job(runtime,expectedProfileSha256=PROFILE_SHA)
            result=execute(path,runtime,runtime/"lifecycle-staging"/job["lifecycleDecisionId"],ROOT)
            self.assertTrue((runtime/"deployments/dhaka_south/model-assignment/latest.json").is_file())
            authority=resolve_active_model(ROOT,runtime)
            self.assertEqual(authority["authoritySource"],"committed_assignment")
            self.assertEqual(result["assignmentId"],authority["assignmentId"])

    def test_defer_without_evidence_is_decision_only_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime=Path(directory);job,path=lifecycle_job(runtime,"defer",evidenceContextStatus="explicit_no_evidence")
            first=execute(path,runtime,runtime/"lifecycle-staging"/job["lifecycleDecisionId"],ROOT)
            self.assertIsNone(first["assignmentId"]);self.assertFalse((runtime/"deployments/dhaka_south/model-assignment/latest.json").exists())
            second=execute(path,runtime,runtime/"retry-staging"/job["lifecycleDecisionId"],ROOT)
            self.assertTrue(second["idempotent"])

    def test_pointer_publication_failure_recovers_exact_orphan(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime=Path(directory);job,path=lifecycle_job(runtime,expectedProfileSha256=PROFILE_SHA);staging=runtime/"lifecycle-staging"/job["lifecycleDecisionId"]
            from runtime_model_lifecycle import prepare_bundle,verify_action_sources
            active=resolve_active_model(ROOT,runtime);verified=verify_action_sources(ROOT,runtime,job,active);bundle=prepare_bundle(ROOT,runtime,job,active,verified)
            (staging/"artifacts").mkdir(parents=True);(staging/"metadata").mkdir()
            for relative,value in (("artifacts/lifecycle_decision.json",bundle["decision"]),("metadata/lifecycle_decision_commit.json",bundle["decisionCommit"]),("artifacts/model_assignment.json",bundle["assignment"]),("metadata/model_assignment_commit.json",bundle["assignmentCommit"])):atomic_json(staging/relative,value)
            with self.assertRaisesRegex(OSError,"injected_assignment_pointer_publication_failure"):
                commit_lifecycle(ROOT,runtime,path,staging,fail_pointer_publication_for_test=True)
            self.assertTrue((runtime/"model-lifecycle"/job["lifecycleDecisionId"]).is_dir());self.assertFalse((runtime/"deployments/dhaka_south/model-assignment/latest.json").exists())
            with self.assertRaises(ActiveModelError):resolve_active_model(ROOT,runtime)
            original=job["reason"];job["reason"]="Conflicting orphan recovery reason.";atomic_json(path,job)
            with self.assertRaisesRegex(ValueError,"independent_lifecycle_reconciliation_failed"):execute(path,runtime,runtime/"conflict-staging",ROOT)
            job["reason"]=original;atomic_json(path,job)
            recovered=execute(path,runtime,runtime/"unused-staging",ROOT)
            self.assertTrue(recovered["recovered"]);self.assertEqual(resolve_active_model(ROOT,runtime)["authoritySource"],"committed_assignment")

    def test_deployment_lock_prevents_assignment_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime=Path(directory);job,path=lifecycle_job(runtime,expectedProfileSha256=PROFILE_SHA);lock=runtime/"deployments/dhaka_south/model-assignment/locks/commit.lock";lock.parent.mkdir(parents=True);lock.write_text("contended")
            with self.assertRaisesRegex(ValueError,"model_assignment_commit_locked"):execute(path,runtime,runtime/"lifecycle-staging"/job["lifecycleDecisionId"],ROOT)
            self.assertFalse((runtime/"deployments/dhaka_south/model-assignment/latest.json").exists())

    def test_second_assignment_with_stale_absent_pointer_publishes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime=Path(directory);first,first_path=lifecycle_job(runtime,expectedProfileSha256=PROFILE_SHA);execute(first_path,runtime,runtime/"lifecycle-staging"/first["lifecycleDecisionId"],ROOT);pointer=(runtime/"deployments/dhaka_south/model-assignment/latest.json").read_bytes()
            second,second_path=lifecycle_job(runtime,expectedProfileSha256=PROFILE_SHA)
            with self.assertRaisesRegex(ValueError,"stale_model_assignment_pointer"):execute(second_path,runtime,runtime/"lifecycle-staging"/second["lifecycleDecisionId"],ROOT)
            self.assertEqual(pointer,(runtime/"deployments/dhaka_south/model-assignment/latest.json").read_bytes())


if __name__=="__main__":unittest.main()
