import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"analytics"))
from runtime_active_model import *
from runtime_commit import atomic_json
from runtime_model_lifecycle import execute
from tests.test_runtime_model_lifecycle import lifecycle_job


def bootstrap(runtime:Path):
    job,path=lifecycle_job(runtime,expectedProfileSha256=PROFILE_SHA);execute(path,runtime,runtime/"lifecycle-staging"/job["lifecycleDecisionId"],ROOT);return job


class ActiveModelTests(unittest.TestCase):
    def test_exact_profile_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            authority=resolve_historical_active_model_p2_v1(repository_root=ROOT,runtime_root=Path(directory));self.assertEqual(authority["authoritySource"],"historical_profile_fallback_pending_explicit_bootstrap");self.assertTrue(authority["bootstrapRequired"]);self.assertEqual(authority["parameterSha256"],PARAMETER_SHA)

    def test_history_without_pointer_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"model-lifecycle/x/metadata/model_assignment_commit.json";path.parent.mkdir(parents=True);path.write_text("{}")
            with self.assertRaises(ActiveModelError):resolve_historical_active_model_p2_v1(repository_root=ROOT,runtime_root=Path(directory))

    def test_deleted_pointer_after_valid_history_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime=Path(directory);bootstrap(runtime);(runtime/"deployments/dhaka_south/model-assignment/latest.json").unlink()
            with self.assertRaises(ActiveModelError):resolve_historical_active_model_p2_v1(repository_root=ROOT,runtime_root=runtime)

    def test_each_assignment_artifact_schema_tamper_fails_closed(self):
        relative_paths=("deployments/dhaka_south/model-assignment/latest.json","artifacts/model_assignment.json","artifacts/lifecycle_decision.json","metadata/model_assignment_commit.json","metadata/lifecycle_decision_commit.json")
        for relative in relative_paths:
            with self.subTest(relative=relative),tempfile.TemporaryDirectory() as directory:
                runtime=Path(directory);job=bootstrap(runtime);bundle=runtime/"model-lifecycle"/job["lifecycleDecisionId"]
                path=runtime/relative if relative.startswith("deployments/") else bundle/relative;value=json.loads(path.read_text());value["unexpectedIntegrityField"]=True;atomic_json(path,value)
                with self.assertRaises(ActiveModelError):resolve_historical_active_model_p2_v1(repository_root=ROOT,runtime_root=runtime)

    def test_pointer_path_traversal_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime=Path(directory);bootstrap(runtime);path=runtime/"deployments/dhaka_south/model-assignment/latest.json";value=json.loads(path.read_text());value["assignmentPath"]="../profile.json";atomic_json(path,value)
            with self.assertRaises(ActiveModelError):resolve_historical_active_model_p2_v1(repository_root=ROOT,runtime_root=runtime)

    def test_duplicate_current_assignment_bundle_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime=Path(directory);job=bootstrap(runtime);source=runtime/"model-lifecycle"/job["lifecycleDecisionId"];duplicate=runtime/"model-lifecycle"/str(__import__("uuid").uuid4());shutil.copytree(source,duplicate)
            with self.assertRaises(ActiveModelError):resolve_historical_active_model_p2_v1(repository_root=ROOT,runtime_root=runtime)

    def test_symlinked_assignment_artifact_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime=Path(directory);job=bootstrap(runtime);bundle=runtime/"model-lifecycle"/job["lifecycleDecisionId"];path=bundle/"artifacts/model_assignment.json";target=path.with_suffix(".target");path.replace(target)
            try:path.symlink_to(target)
            except OSError:
                junction_target=runtime/"junction-target";bundle.replace(junction_target)
                result=subprocess.run(["powershell","-NoProfile","-Command",f"New-Item -ItemType Junction -Path '{bundle}' -Target '{junction_target}' | Out-Null"],capture_output=True,text=True)
                if result.returncode:self.fail(f"could not create symlink or junction: {result.stderr}")
            with self.assertRaises(ActiveModelError):resolve_historical_active_model_p2_v1(repository_root=ROOT,runtime_root=runtime)

    def test_historical_canonical_quick_policy_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary=Path(directory);repository=temporary/"repository";shutil.copytree(ROOT/"config",repository/"config");runtime=temporary/"runtime";runtime.mkdir();quick=repository/"config/deployments/dhaka_south/quick_forecast_policy_p1.4f-v1.json";value=json.loads(quick.read_text());value["maturity_statement"]="Tampered but declared hash retained.";atomic_json(quick,value)
            with self.assertRaises(ActiveModelError):resolve_historical_active_model_p2_v1(repository_root=repository,runtime_root=runtime)

    def test_current_canonical_quick_policy_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary=Path(directory);repository=temporary/"repository";shutil.copytree(ROOT/"config",repository/"config");runtime=temporary/"runtime";runtime.mkdir();quick=repository/"config/deployments/dhaka_south/quick_forecast_policy.json";value=json.loads(quick.read_text());value["maturity_statement"]="Tampered but declared hash retained.";atomic_json(quick,value)
            with self.assertRaises(ActiveModelError):resolve_active_model_p2_v2(repository_root=repository,runtime_root=runtime)



if __name__=="__main__":unittest.main()
