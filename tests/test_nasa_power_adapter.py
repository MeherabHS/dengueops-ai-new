import datetime as dt
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analytics"))
import fetch_nasa_power_climate as adapter


class NasaPowerAdapterTest(unittest.TestCase):
    def daily(self, start="2021-01-04", days=14):
        dates=pd.date_range(start, periods=days, freq="D")
        df=pd.DataFrame({"date": dates})
        for p in adapter.PARAMETERS: df[p]=range(1, days+1)
        return df

    def write_cache(self, root: Path, df: pd.DataFrame, **changes):
        cache=root/"cache.csv"; df.to_csv(cache,index=False)
        now=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        meta=adapter._cache_metadata(adapter._validate_daily(df), cache, adapter.sha256_file(cache), df.date.min().date().isoformat(), df.date.max().date().isoformat(), now)
        meta.update(changes); metadata=root/"metadata.json"; metadata.write_text(json.dumps(meta))
        return cache, metadata, meta

    def test_weekly_contract_and_aggregation(self):
        weekly, excluded, warnings=adapter.aggregate_to_weekly(self.daily(days=7))
        self.assertEqual(list(weekly.columns), adapter.CANONICAL_COLUMNS)
        row=weekly.iloc[0]
        self.assertEqual(row.coverage_days,7); self.assertEqual(row.rainfall_mm,28)
        self.assertEqual(row.avg_temp_c,4); self.assertEqual(row.humidity_pct,4)
        self.assertEqual(row.geography_level,"point")
        self.assertEqual(row.associated_geography_id,"BGD-DHAKA-SOUTH")

    def test_partial_boundary_and_incomplete_interior(self):
        weekly, excluded, warnings=adapter.aggregate_to_weekly(self.daily("2021-01-06",12))
        self.assertTrue(excluded); self.assertEqual(len(weekly),1)
        df=self.daily(days=21).drop(index=10).reset_index(drop=True)
        with self.assertRaises(adapter.AdapterError): adapter.aggregate_to_weekly(df)
        df=self.daily(days=7); df.loc[3,"T2M"]=float("nan")
        with self.assertRaises(adapter.AdapterError): adapter.aggregate_to_weekly(df)

    def test_cache_exact_superset_and_metadata_mismatches(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); df=self.daily(days=21); cache,metadata,meta=self.write_cache(root,df)
            sliced,_,_=adapter.validate_cache(cache,metadata,"2021-01-04","2021-01-24")
            self.assertEqual(len(sliced),21)
            sliced,_,_=adapter.validate_cache(cache,metadata,"2021-01-11","2021-01-17")
            self.assertEqual(len(sliced),7)
            for key,value in (("coordinates",{"latitude":0,"longitude":0}),("parameters",["T2M"]),("units",{}),("cache_file_sha256","bad")):
                bad=dict(meta); bad[key]=value; metadata.write_text(json.dumps(bad))
                with self.assertRaises(adapter.AdapterError): adapter.validate_cache(cache,metadata,"2021-01-04","2021-01-24")
            metadata.write_text(json.dumps(meta))

    def test_offline_success_w53_and_failed_refresh_preserve_output(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); cache,metadata,_=self.write_cache(root,self.daily(days=14)); output=root/"climate.csv"
            self.assertEqual(adapter.main("2021-01-04","2021-01-17",False,cache,metadata,output,True),0)
            result=pd.read_csv(output); self.assertEqual(list(result.columns),adapter.CANONICAL_COLUMNS)
            old=output.read_bytes()
            with patch.object(adapter,"fetch_from_nasa",side_effect=adapter.AdapterError("offline")):
                self.assertEqual(adapter.main("2020-01-01","2020-01-07",True,cache,metadata,output,False),1)
            self.assertEqual(output.read_bytes(),old)
            w53=self.daily("2020-12-28",7)
            with self.assertRaises(adapter.AdapterError): adapter.aggregate_to_weekly(w53)


if __name__ == "__main__": unittest.main()
