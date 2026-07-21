from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))

from runtime_uncertainty import UncertaintyContractError, validate_uncertainty_contract


def identity():
    return {"selectedModelId":"ridge_regression","modelFamily":"Ridge","parameterSha256":"a"*64,
            "candidateRegistrySha256":"b"*64,"featureOrderSha256":"c"*64,"foldPlanSha256":"d"*64,
            "datasetId":"e"*64,"policyId":"RUNTIME.QUICK_FORECAST.COMPATIBILITY","policyVersion":"p2-v1",
            "sourceFamily":"quick_forecast_p2"}


class ProductV2UncertaintyContractTests(unittest.TestCase):
    def assert_invalid(self, value):
        with self.assertRaises(UncertaintyContractError):
            validate_uncertainty_contract(value, ROOT)

    def test_point_only_requires_reason_and_null_bounds(self):
        valid = {**identity(),"forecastPresentationMode":"point_only","calibrationStatus":"pending","lower":None,"upper":None,
                 "uncertaintyReasonCode":"model_specific_calibration_pending","calibrationProvenance":None}
        validate_uncertainty_contract(valid, ROOT)
        for mutation in (
            {**valid,"lower":1.0}, {**valid,"upper":2.0}, {**valid,"calibrationStatus":"governed_available"},
            {key:value for key,value in valid.items() if key != "uncertaintyReasonCode"},
        ):
            self.assert_invalid(mutation)

    def test_point_and_interval_requires_exact_governed_provenance(self):
        provenance = {**identity(),"modelId":"ridge_regression","calibrationEvidenceSha256":"f"*64}
        provenance.pop("selectedModelId")
        valid = {**identity(),"forecastPresentationMode":"point_and_interval","calibrationStatus":"governed_available",
                 "lower":1.0,"upper":3.0,"uncertaintyReasonCode":None,"calibrationProvenance":provenance}
        validate_uncertainty_contract(valid, ROOT)
        for mutation in ({**valid,"calibrationStatus":"pending"}, {**valid,"lower":None}, {**valid,"calibrationProvenance":None}):
            self.assert_invalid(mutation)
        crossed = copy.deepcopy(valid)
        crossed["calibrationProvenance"]["modelId"] = "random_forest"
        self.assert_invalid(crossed)

    def test_rmse_fallback_and_every_cross_identity_binding_are_rejected(self):
        base = {**identity(),"forecastPresentationMode":"point_only","calibrationStatus":"unavailable","lower":None,"upper":None,
                "uncertaintyReasonCode":"calibration_unavailable","calibrationProvenance":None}
        self.assert_invalid({**base,"rmseFallback":12.0})
        provenance = {**identity(),"modelId":"ridge_regression","calibrationEvidenceSha256":"f"*64}
        provenance.pop("selectedModelId")
        interval = {**identity(),"forecastPresentationMode":"point_and_interval","calibrationStatus":"governed_available",
                    "lower":1.0,"upper":3.0,"uncertaintyReasonCode":None,"calibrationProvenance":provenance}
        for key in ("modelFamily","parameterSha256","candidateRegistrySha256","featureOrderSha256","foldPlanSha256","datasetId","policyVersion","sourceFamily"):
            changed = copy.deepcopy(interval)
            changed["calibrationProvenance"][key] = "changed" if not key.endswith("Sha256") else "0"*64
            self.assert_invalid(changed)


if __name__ == "__main__":
    unittest.main()
