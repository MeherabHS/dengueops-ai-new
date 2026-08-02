import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"analytics"))

from runtime_governed_monitoring import publish_current_monitoring
from runtime_quick_forecast import execute
from tests.test_product_v2_quick_forecast import _create_p2_v2_assignment,_setup_quick_run_job,build_ready_workspace


class RuntimeGovernedMonitoringIntegrationTests(unittest.TestCase):
    def test_operational_forecast_publishes_exact_current_idempotent_monitoring(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory)
            runtime=_create_p2_v2_assignment(base,ROOT,model_id="gradient_boosting")
            workspace,dataset_id,validation_sha=build_ready_workspace(runtime)
            job,job_path,staging=_setup_quick_run_job(runtime,workspace.name,dataset_id,validation_sha)
            assignment_before=(runtime/"deployments/dhaka_south/model-assignment/latest.json").read_bytes()
            result=execute(SimpleNamespace(runtime_root=str(runtime),job_record=str(job_path),workspace=str(workspace),staging=str(staging)))
            self.assertTrue(result["committed"])
            if result.get("monitoring") is None:
                publish_current_monitoring(runtime,job["runId"])
            forecast_before=(runtime/"deployments/dhaka_south/latest.json").read_bytes()
            pointer_path=runtime/"deployments/dhaka_south/degradation/latest_b9-d-v1.json"
            self.assertTrue(pointer_path.is_file())
            pointer=json.loads(pointer_path.read_text())
            evidence_path=runtime/pointer["evidencePath"]
            evidence=json.loads(evidence_path.read_text())
            self.assertEqual(evidence["authority"]["assignmentId"],json.loads(assignment_before)["assignmentId"])
            self.assertEqual(evidence["authority"]["forecastRunId"],job["runId"])
            self.assertEqual(evidence["authority"]["datasetId"],dataset_id)
            self.assertEqual(len(evidence["featureDrift"]["perFeature"]),18)
            self.assertEqual(evidence["performanceDrift"]["status"],"awaiting_outcomes")
            self.assertEqual(evidence["confidence"]["status"],"available")
            self.assertEqual(evidence["confidence"]["classification"],"forecast_evidence_confidence")
            self.assertFalse(evidence["invariants"]["confidenceScoreChangesModelSelection"])
            second=publish_current_monitoring(runtime,job["runId"])
            self.assertTrue(second["recovered"])
            self.assertEqual(second["monitoringId"],pointer["monitoringId"])
            self.assertEqual((runtime/"deployments/dhaka_south/model-assignment/latest.json").read_bytes(),assignment_before)
            self.assertEqual((runtime/"deployments/dhaka_south/latest.json").read_bytes(),forecast_before)
            self.assertFalse((runtime/"deployments/dhaka_south/operational-preparedness/latest.json").exists())


if __name__=="__main__":unittest.main()
