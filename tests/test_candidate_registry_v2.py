from __future__ import annotations

import copy
import json
import tempfile
import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))

from model_factory import canonical_sha256, load_and_validate_candidate_registry
from runtime_active_model import FEATURE_SHA

REGISTRY = ROOT / "config/candidate_models.json"

LEARNED = {
    "random_forest", "ridge_regression", "poisson_regression", "gradient_boosting",
    "elastic_net", "negative_binomial_regression", "extra_trees", "hist_gradient_boosting",
}
BASELINES = {"moving_average_4w", "seasonal_naive_52w"}


class CandidateRegistryV2Tests(unittest.TestCase):
    def setUp(self):
        self.registry = json.loads(REGISTRY.read_text(encoding="utf-8"))

    def _rejects(self, mutate):
        value = copy.deepcopy(self.registry)
        mutate(value)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_and_validate_candidate_registry(path)

    def test_active_registry_is_exact_closed_v2_set(self):
        registry, _ = load_and_validate_candidate_registry()
        self.assertEqual(registry["candidate_registry_schema_version"], "2.0")
        self.assertEqual(registry["candidate_registry_version"], "p2-v1")
        candidates = registry["candidates"]
        self.assertEqual(len(candidates), 10)
        self.assertEqual({c["model_id"] for c in candidates if c["candidate_class"] == "learned_model"}, LEARNED)
        self.assertEqual({c["model_id"] for c in candidates if c["candidate_class"] == "comparison_baseline"}, BASELINES)
        self.assertNotIn("previous_week_naive", {c["model_id"] for c in candidates})
        self.assertEqual(registry["feature_order_sha256"], FEATURE_SHA)
        for candidate in candidates:
            self.assertEqual(candidate["parameters_sha256"], canonical_sha256(candidate["parameters"]))
            self.assertEqual(candidate["feature_order_sha256"], FEATURE_SHA)
            self.assertEqual(candidate["target"], "target_cases_next_2w")
            self.assertEqual(candidate["horizon_weeks"], 2)
            if candidate["candidate_class"] == "comparison_baseline":
                self.assertFalse(candidate["selectable"])
                self.assertEqual(candidate["selection_role"], "baseline_only")

    def test_registry_semantics_fail_closed(self):
        mutations = {
            "duplicate_id": lambda v: v["candidates"].__setitem__(1, {**v["candidates"][1], "model_id": v["candidates"][0]["model_id"]}),
            "duplicate_parameters": lambda v: v["candidates"][1].update(parameters=v["candidates"][0]["parameters"], parameters_sha256=v["candidates"][0]["parameters_sha256"]),
            "unknown_property": lambda v: v["candidates"][0].update(browser_parameters={}),
            "tuning_field": lambda v: v["candidates"][0].update(parameter_grid={"x": [1, 2]}),
            "baseline_selectable": lambda v: next(c for c in v["candidates"] if c["candidate_class"] == "comparison_baseline").update(selectable=True),
            "parameter_hash": lambda v: v["candidates"][0].update(parameters_sha256="0" * 64),
            "changed_frozen_parameter": lambda v: (
                next(c for c in v["candidates"] if c["model_id"] == "elastic_net")["parameters"].update(alpha=0.2),
                next(c for c in v["candidates"] if c["model_id"] == "elastic_net").update(
                    parameters_sha256=canonical_sha256(next(c for c in v["candidates"] if c["model_id"] == "elastic_net")["parameters"])
                ),
            ),
            "model_family": lambda v: v["candidates"][2].update(model_family="SubstitutedEstimator"),
            "estimator_library": lambda v: v["candidates"][2].update(estimator_library="substituted-library"),
            "estimator_library_version": lambda v: v["candidates"][2].update(estimator_library_version="0.0.0"),
            "feature_order": lambda v: v["candidates"][0].update(feature_order_sha256="0" * 64),
        }
        for label, mutate in mutations.items():
            with self.subTest(case=label):
                self._rejects(mutate)


if __name__ == "__main__":
    unittest.main()
