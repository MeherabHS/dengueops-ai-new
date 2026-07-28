from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))

from model_factory import (
    TRUSTED_MODEL_ADAPTERS,
    baseline_model_ids,
    canonical_sha256,
    candidate_ids,
    learned_model_ids,
    load_and_validate_candidate_registry,
    load_historical_candidate_registry,
    selectable_learned_model_ids,
)


class CandidateRegistrationGeneralizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.authoritative, cls.authoritative_sha = load_and_validate_candidate_registry()

    def _write(self, value: dict) -> tuple[tempfile.TemporaryDirectory, Path]:
        directory = tempfile.TemporaryDirectory()
        path = Path(directory.name) / "candidate_models.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return directory, path

    def test_current_count_order_and_roles_derive_from_registry(self):
        expected = tuple(candidate["model_id"] for candidate in self.authoritative["candidates"])
        self.assertEqual(candidate_ids(self.authoritative), expected)
        self.assertEqual(
            learned_model_ids(self.authoritative),
            tuple(candidate["model_id"] for candidate in self.authoritative["candidates"]
                  if candidate["candidate_class"] == "learned_model"),
        )
        self.assertEqual(
            baseline_model_ids(self.authoritative),
            tuple(candidate["model_id"] for candidate in self.authoritative["candidates"]
                  if candidate["candidate_class"] == "comparison_baseline"),
        )
        self.assertEqual(selectable_learned_model_ids(self.authoritative), learned_model_ids(self.authoritative))
        source = (ROOT / "analytics/model_factory.py").read_text(encoding="utf-8")
        schema = json.loads((ROOT / "config/candidate_models.schema.json").read_text(encoding="utf-8"))
        self.assertNotIn("exactly eight", source.lower())
        self.assertNotIn("maxItems", schema["properties"]["candidates"])

    def test_current_portfolio_execution_metadata_matches_pre_generalization_golden(self):
        keys = (
            "model_id", "candidate_class", "selection_role", "model_family",
            "parameters_sha256", "preprocessing_identity",
            "minimum_training_rows", "estimator_library",
            "estimator_library_version", "output_domain_rule",
        )
        projection = [
            [candidate[key] for key in keys]
            for candidate in self.authoritative["candidates"][:10]
        ]
        digest = hashlib.sha256(
            json.dumps(
                projection, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        self.assertEqual(
            self.authoritative_sha,
            "e6fd8aff5d092f7a9e112647515349d7aed43b21f5d78d97b8f988d492ab0226",
        )
        self.assertEqual(
            digest,
            "1027072d35f376186dde7a2c517db08a376b191f2e2bfe61cf563dca8c820ac6",
        )
        archived = ROOT / "config/candidate_models_p2-v1.json"
        self.assertEqual(
            hashlib.sha256(archived.read_bytes()).hexdigest(),
            "74cb3635c5e211874ee5ad23196fc95bfdfbdb5c6438cc3d060f0b9ff49acfa0",
        )
        gam = self.authoritative["candidates"][-1]
        self.assertEqual(
            (
                gam["model_id"], gam["model_family"], gam["parameters_sha256"],
                gam["preprocessing_identity"], gam["minimum_training_rows"],
                gam["output_domain_rule"],
            ),
            (
                "poisson_gam", "SplinePoissonRegressor",
                "30a0591f9f8c15877c0814a99b48ce7ae859acdf7a5a68f0c591351259600911",
                "19aa8ed7749046b27b4d5488bd9098f489ff67fae75e4216d043d2de49d3d236",
                90, "negative_or_nonfinite_output_fails_fold",
            ),
        )

    def test_registry_candidate_without_trusted_adapter_fails_closed(self):
        value = copy.deepcopy(self.authoritative)
        extra = copy.deepcopy(next(candidate for candidate in value["candidates"]
                                   if candidate["model_id"] == "ridge_regression"))
        extra.update(model_id="untrusted_registry_candidate", model_family="UntrustedRegistryCandidate")
        value["candidates"].append(extra)
        directory, path = self._write(value)
        try:
            with self.assertRaisesRegex(ValueError, "no trusted model adapter"):
                load_and_validate_candidate_registry(path)
        finally:
            directory.cleanup()

    def test_trusted_adapter_absent_from_registry_is_not_active(self):
        descriptor = TRUSTED_MODEL_ADAPTERS["ridge_regression"]
        with patch.dict(TRUSTED_MODEL_ADAPTERS, {"trusted_but_inactive": descriptor}):
            registry, _ = load_and_validate_candidate_registry()
            self.assertNotIn("trusted_but_inactive", candidate_ids(registry))
            self.assertNotIn("trusted_but_inactive", learned_model_ids(registry))

    def test_parameter_hash_duplicate_is_valid_across_full_identities(self):
        value = copy.deepcopy(self.authoritative)
        source = next(candidate for candidate in value["candidates"]
                      if candidate["model_id"] == "ridge_regression")
        alias = copy.deepcopy(source)
        alias.update(model_id="trusted_ridge_alias", model_family="TrustedRidgeAlias")
        value["candidates"].append(alias)
        descriptor = replace(
            TRUSTED_MODEL_ADAPTERS["ridge_regression"],
            model_family="TrustedRidgeAlias",
        )
        directory, path = self._write(value)
        try:
            with patch.dict(TRUSTED_MODEL_ADAPTERS, {"trusted_ridge_alias": descriptor}):
                registry, _ = load_and_validate_candidate_registry(path)
            identities = {
                (
                    candidate["model_id"],
                    candidate["model_family"],
                    candidate["parameters_sha256"],
                    candidate["preprocessing_identity"],
                )
                for candidate in registry["candidates"]
            }
            self.assertEqual(len(identities), len(registry["candidates"]))
            self.assertEqual(source["parameters_sha256"], alias["parameters_sha256"])
        finally:
            directory.cleanup()

    def test_parameter_sha_and_duplicate_model_id_fail_closed(self):
        for mutation, message in (
            (lambda value: value["candidates"][0].update(parameters_sha256="0" * 64), "Parameter hash"),
            (lambda value: value["candidates"][1].update(model_id=value["candidates"][0]["model_id"]), "unique"),
        ):
            value = copy.deepcopy(self.authoritative)
            mutation(value)
            directory, path = self._write(value)
            try:
                with self.assertRaisesRegex(ValueError, message):
                    load_and_validate_candidate_registry(path)
            finally:
                directory.cleanup()

    def test_historical_population_and_identity_remain_exact(self):
        registry, digest = load_historical_candidate_registry()
        self.assertEqual(len(registry["candidates"]), 7)
        self.assertEqual(digest, "2e627f8a368a7e92cebd4ad62139b1050c7614559affd620e9a41738fd6a25d4")


if __name__ == "__main__":
    unittest.main()
