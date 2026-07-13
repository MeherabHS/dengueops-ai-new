import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"analytics"))
from feature_engineering import FEATURE_COLUMNS
from provenance import (
    PROVENANCE_COLUMNS, ProvenanceError, add_feature_provenance,
    assert_same_provenance, build_compact_provenance, derive_data_mode,
    load_manifest, provenance_from_feature_frame,
)


class ProvenancePropagationTest(unittest.TestCase):
    def manifest(self, root: Path):
        files=[]
        for name in ("cases.csv","climate.csv","zones.json"):
            path=root/name; path.write_text(name,encoding="utf-8")
            files.append((path,hashlib.sha256(path.read_bytes()).hexdigest()))
        def entry(source,source_class,path,digest):
            return {"selected_source":source,"detected_source":source,"source_tag":source,
                    "source_class":source_class,"files":[{"path":str(path),"sha256":digest}],
                    "geography":{"level":"city","id":"BGD-DHAKA-SOUTH","name":"Dhaka South"},
                    "validation":{"status":"passed","warnings":[]}}
        value={"schema_version":"1.0","run_id":"run-123","inputs":{
            "cases":entry("synthetic_demo","synthetic",*files[0]),
            "climate":entry("nasa_power","public_real",*files[1]),
            "operational":entry("synthetic_demo","synthetic",*files[2])},
            "cross_source_validation":{"status":"passed"},"warnings":["warning"],"overrides":["override"]}
        path=root/"input_manifest.json"; path.write_text(json.dumps(value,indent=2)+"\n",encoding="utf-8")
        return path,value

    def test_exact_manifest_bytes_and_compact_shape(self):
        with tempfile.TemporaryDirectory() as td:
            path,value=self.manifest(Path(td)); loaded,digest=load_manifest(path)
            self.assertEqual(digest,hashlib.sha256(path.read_bytes()).hexdigest())
            provenance=build_compact_provenance(loaded,digest,path)
            self.assertEqual(provenance["run_id"],"run-123")
            self.assertEqual(provenance["forecast_geography"]["id"],"BGD-DHAKA-SOUTH")
            self.assertEqual(derive_data_mode(provenance),"mixed")

    def test_feature_columns_are_consistent_and_not_model_features(self):
        with tempfile.TemporaryDirectory() as td:
            path,value=self.manifest(Path(td)); loaded,digest=load_manifest(path)
            provenance=build_compact_provenance(loaded,digest,path)
            df=add_feature_provenance(pd.DataFrame({"x":[1,2]}),provenance)
            self.assertEqual(set(PROVENANCE_COLUMNS),set(df.columns)-{"x"})
            self.assertTrue(set(PROVENANCE_COLUMNS).isdisjoint(FEATURE_COLUMNS))
            self.assertEqual(len(FEATURE_COLUMNS),18)
            self.assertEqual(provenance_from_feature_frame(df,path),provenance)
            df.loc[1,"input_run_id"]="other"
            with self.assertRaises(ProvenanceError): provenance_from_feature_frame(df,path)

    def test_missing_manifest_hash_source_and_run_mismatches_fail(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); path,value=self.manifest(root)
            with self.assertRaises(ProvenanceError): load_manifest(root/"missing.json")
            loaded,digest=load_manifest(path); p=build_compact_provenance(loaded,digest,path)
            for key in ("run_id","manifest_sha256","case_source"):
                other=json.loads(json.dumps(p)); other[key]="different"
                with self.assertRaises(ProvenanceError): assert_same_provenance(p,other)

    def test_uncertainty_preserves_current_run_provenance(self):
        uncertainty=json.loads((ROOT/"data/forecast_uncertainty.json").read_text())
        forecast=json.loads((ROOT/"data/forecast_output.json").read_text())
        self.assertEqual(uncertainty["provenance"],forecast["provenance"])


if __name__ == "__main__": unittest.main()
