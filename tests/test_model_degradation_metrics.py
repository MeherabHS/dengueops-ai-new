import math,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"analytics"))
from model_degradation_metrics import *

SHA="0"*64
def record(index,actual=10,forecast=8,period=None):
    return {"schemaVersion":"2.0","outcomeId":f"00000000-0000-4000-8000-{index:012d}","sourceForecastRunId":f"10000000-0000-4000-8000-{index:012d}","forecastTargetPeriod":period or f"2024-W{index:02d}","outcomeEvidenceSha256":f"{index:064x}","deploymentId":"dhaka_south","geography":{"level":"city","id":"BGD-DHAKA-SOUTH","name":"Dhaka South"},"targetColumn":"target_cases_next_2w","forecastHorizonWeeks":2,"sourceFamily":"quick_forecast_p1","monitoringPolicy":{"policyId":"RUNTIME.FORECAST_OUTCOME.MONITORING","policyVersion":"p2-v1","policySha256":SHA},"sourcePolicy":{"policyId":"RUNTIME.QUICK_FORECAST.COMPATIBILITY","policyVersion":"p1.4f-v1","policySha256":SHA},"modelId":"random_forest","modelFamily":"RandomForestRegressor","modelParametersSha256":SHA,"featureOrderSha256":SHA,"candidateRegistrySha256":SHA,"empiricalRangeStatus":"available","coverageOutcome":"covered","forecastRaw":forecast,"observedRaw":actual}

class ModelDegradationMetricsTests(unittest.TestCase):
    def test_explicit_window_is_ordered_disjoint_and_hashed(self):
        values=[record(i) for i in range(1,7)];result=select_monitoring_windows(list(reversed(values)),2)
        self.assertEqual(result["status"],"computable_descriptive_evidence");self.assertEqual([v["outcomeId"] for v in result["reference"]],[values[2]["outcomeId"],values[3]["outcomeId"]]);self.assertEqual([v["outcomeId"] for v in result["recent"]],[values[4]["outcomeId"],values[5]["outcomeId"]]);self.assertEqual(result["excludedPrefixCount"],2)
        verify_disjoint_windows(result["reference"],result["recent"])
    def test_window_insufficiency_and_warnings(self):
        self.assertEqual(select_monitoring_windows([record(1)],2)["status"],"insufficient_recent_outcomes")
        self.assertEqual(select_monitoring_windows([record(1),record(2),record(3)],2)["status"],"insufficient_reference_outcomes")
        self.assertIn("duplicate_target_periods_present",period_warnings([record(1,period="2024-W01"),record(2,period="2024-W01")]))
        self.assertIn("calendar_gaps_present",period_warnings([record(1,period="2024-W01"),record(2,period="2024-W03")]))
    def test_metrics_preserve_observed_minus_raw_and_zero_eligibility(self):
        metrics=aggregate_metrics([record(1,10,8),record(2,0,2)])
        self.assertEqual(metrics["mae"],2);self.assertEqual(metrics["rmse"],2);self.assertEqual(metrics["signedBias"],0);self.assertEqual(metrics["absoluteBias"],0);self.assertEqual(metrics["percentageEligibleCount"],1);self.assertEqual(metrics["mpe"],20);self.assertEqual(metrics["mape"],20);self.assertEqual(metrics["empiricalCoverage"],1)
        self.assertIsNone(metric_ratio(0,2));self.assertEqual(metric_delta(3,5),2)
    def test_nonfinite_and_overlap_fail_closed(self):
        bad=record(1);bad["forecastRaw"]=math.inf
        with self.assertRaises(ModelDegradationMetricError):aggregate_metrics([bad])
        with self.assertRaises(ModelDegradationMetricError):verify_disjoint_windows([record(1)],[record(1)])
    def test_strict_identity_separates_parameters_and_sources(self):
        first=record(1);second=record(2);second["modelParametersSha256"]="1"*64
        self.assertNotEqual(strict_cohort_key(first),strict_cohort_key(second))

if __name__=="__main__":unittest.main()
