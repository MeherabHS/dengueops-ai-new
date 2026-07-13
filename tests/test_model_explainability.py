from __future__ import annotations

import copy
import json
import math
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))

from deployment_profiles import load_deployment_profile  # noqa: E402
from explainability_engine import (  # noqa: E402
    ExplainabilityError, _ranks, build_model_explainability, feature_formula_id,
    validate_model_explainability,
)
from feature_engineering import FEATURE_COLUMNS  # noqa: E402
from validation_backtest import (  # noqa: E402
    GBR_PARAMS, TARGET_COL, _run_backtest_context, load_feature_matrix, run_backtest,
)


class ModelExplainabilityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df = load_feature_matrix()
        cls.context = _run_backtest_context(cls.df)
        cls.profile = load_deployment_profile("dhaka_south")
        cls.artifact = build_model_explainability(
            cls.context.validation_model, cls.context.train_df, cls.context.test_df,
            cls.context.feature_names, cls.context.target, cls.context.model_parameters,
            cls.context.provenance, cls.profile,
        )

    def test_public_backtest_contract_is_preserved(self):
        self.assertIsInstance(run_backtest(self.df), dict)

    def test_real_native_importance_comes_from_same_fitted_validation_model(self):
        expected = self.context.validation_model.feature_importances_.tolist()
        self.assertEqual(self.artifact["impurity_importance"], expected)
        self.assertEqual(self.artifact["estimator_role"], "chronological_holdout_validation_model")
        self.assertEqual(len(self.artifact["feature_names"]), 18)
        self.assertEqual(self.artifact["feature_names"], FEATURE_COLUMNS)
        self.assertTrue(all(math.isfinite(value) and value >= 0 for value in expected))
        self.assertTrue(math.isclose(sum(expected), 1.0, abs_tol=1e-9) or all(value == 0 for value in expected))

    def test_permutation_is_deterministic_and_policy_is_recorded(self):
        repeated = build_model_explainability(
            self.context.validation_model, self.context.train_df, self.context.test_df,
            self.context.feature_names, self.context.target, self.context.model_parameters,
            self.context.provenance, self.profile,
        )
        self.assertEqual(self.artifact["permutation_importance"], repeated["permutation_importance"])
        self.assertEqual(self.artifact["permutation_std"], repeated["permutation_std"])
        self.assertEqual(self.artifact["permutation_repeats"], 20)
        self.assertEqual(self.artifact["permutation_scoring"], "neg_mean_absolute_error")
        self.assertEqual(self.artifact["permutation_random_state"], 42)

    def test_no_placeholder_values_and_all_formula_mappings_exist(self):
        serialized = json.dumps(self.artifact).lower()
        self.assertNotIn("placeholder", serialized)
        self.assertEqual(
            [row["formula_id"] for row in self.artifact["feature_ranking"]],
            [feature_formula_id(feature) for feature in FEATURE_COLUMNS],
        )

    def test_negative_zero_all_zero_and_tie_behavior_are_supported(self):
        class ZeroModel:
            feature_importances_ = np.zeros(18)

        fake = SimpleNamespace(
            importances_mean=np.array([-1.0, 0.0, *([2.0] * 16)]),
            importances_std=np.zeros(18),
        )
        with patch("explainability_engine.permutation_importance", return_value=fake):
            artifact = build_model_explainability(
                ZeroModel(), self.context.train_df, self.context.test_df,
                self.context.feature_names, TARGET_COL, GBR_PARAMS,
                self.context.provenance, self.profile,
            )
        self.assertTrue(artifact["feature_ranking"][0]["permutation_is_negative"])
        self.assertTrue(artifact["feature_ranking"][1]["permutation_is_zero"])
        self.assertEqual(sum(artifact["impurity_importance"]), 0)
        self.assertEqual(_ranks([1.0, 1.0, 0.0]), [1, 2, 3])
        for row in artifact["feature_ranking"]:
            self.assertEqual(
                row["rank_disagreement"],
                abs(row["rank_by_permutation"] - row["rank_by_impurity"]) >= 5,
            )

    def test_periods_and_holdout_match_validation_split(self):
        self.assertEqual(self.artifact["validation_rows"], len(self.context.test_df))
        self.assertEqual(self.artifact["training_period"]["end"], {"epi_year": 2023, "epi_week": 39})
        self.assertEqual(self.artifact["validation_period"]["start"], {"epi_year": 2023, "epi_week": 40})
        self.assertEqual(self.artifact["validation_period"]["end"], {"epi_year": 2024, "epi_week": 22})

    def test_reordered_features_and_altered_validation_matrix_fail(self):
        reordered = list(FEATURE_COLUMNS); reordered[0], reordered[1] = reordered[1], reordered[0]
        with self.assertRaisesRegex(ExplainabilityError, "Feature order"):
            build_model_explainability(
                self.context.validation_model, self.context.train_df, self.context.test_df,
                reordered, TARGET_COL, GBR_PARAMS, self.context.provenance, self.profile,
            )
        changed = self.context.test_df.copy()
        changed.loc[changed.index[0], FEATURE_COLUMNS[0]] += 1
        with self.assertRaisesRegex(ExplainabilityError, "validation_matrix"):
            validate_model_explainability(
                self.artifact, expected_feature_names=FEATURE_COLUMNS,
                expected_validation_df=changed, expected_target=TARGET_COL,
            )


if __name__ == "__main__":
    unittest.main()
