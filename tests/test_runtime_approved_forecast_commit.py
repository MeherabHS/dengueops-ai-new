import sys,tempfile,unittest,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'analytics'))
from runtime_approved_forecast_commit import ApprovedForecastCommitError,commit_approved_forecast
class ApprovedCommitTests(unittest.TestCase):
 def test_incomplete_bundle_cannot_change_latest(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory).resolve();run_id=str(uuid.uuid4());staging=root/'staging'/run_id;(staging/'artifacts').mkdir(parents=True);job={'runId':run_id}
   with self.assertRaises(ApprovedForecastCommitError):commit_approved_forecast(root,staging,job)
   self.assertFalse((root/'deployments/dhaka_south/latest.json').exists())
if __name__=='__main__':unittest.main()
