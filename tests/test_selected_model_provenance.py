import hashlib, json, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SelectedModelProvenanceTests(unittest.TestCase):
    def test_commit_record_binds_complete_bundle(self):
        card = json.loads((ROOT / "data/model_card.json").read_text())
        forecast = json.loads((ROOT / "data/forecast_output.json").read_text())
        selected = json.loads((ROOT / "data/selected_model_explainability.json").read_text())
        comparison_hash = hashlib.sha256((ROOT / "data/candidate_model_comparison.json").read_bytes()).hexdigest()
        self.assertEqual(card["forecast_artifact_sha256"], hashlib.sha256((ROOT / "data/forecast_output.json").read_bytes()).hexdigest())
        self.assertEqual(card["selected_model_explainability_artifact_sha256"], hashlib.sha256((ROOT / "data/selected_model_explainability.json").read_bytes()).hexdigest())
        self.assertEqual(card["comparison_artifact_sha256"], comparison_hash)
        self.assertEqual(forecast["comparison_artifact_sha256"], comparison_hash)
        self.assertEqual(selected["comparison_artifact_sha256"], comparison_hash)
        run_ids = {value["provenance"]["run_id"] for value in (card, forecast, selected)}
        manifests = {value["provenance"]["manifest_sha256"] for value in (card, forecast, selected)}
        self.assertEqual(len(run_ids), 1); self.assertEqual(len(manifests), 1)
        self.assertEqual(card["current_forecast_model"], "random_forest")


if __name__ == "__main__": unittest.main()
