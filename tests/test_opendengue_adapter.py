import csv
import hashlib
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analytics"))
import fetch_opendengue as adapter


class OpenDengueAdapterTest(unittest.TestCase):
    def make_zip(self, path: Path, rows: list[dict], columns=None) -> None:
        columns = columns or ["adm_0_name", "T_res", "Year", "dengue_total", "calendar_start_date"]
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=columns); writer.writeheader(); writer.writerows(rows)
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("National_extract.csv", stream.getvalue())

    def rows(self):
        return [
            {"adm_0_name": "BANGLADESH", "T_res": "Month", "Year": "2021", "dengue_total": "310", "calendar_start_date": "2021-02-01"},
            {"adm_0_name": "BANGLADESH", "T_res": "Month", "Year": "2021", "dengue_total": "280", "calendar_start_date": "2021-03-01"},
        ]

    def test_canonical_output_nullable_deaths_and_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); source=root/"source.zip"; self.make_zip(source, self.rows())
            self.assertEqual(adapter.main(source, 2021, 2021, root/"out"), 0)
            output=root/"out"/"dengue_cases.csv"
            with output.open(encoding="utf-8", newline="") as handle:
                rows=list(csv.DictReader(handle))
            self.assertEqual(list(rows[0]), adapter.CANONICAL_COLUMNS)
            self.assertEqual(rows[0]["geography_level"], "national")
            self.assertEqual(rows[0]["geography_id"], "BGD")
            self.assertEqual(rows[0]["source_type"], "opendengue")
            self.assertEqual(rows[0]["deaths"], "")
            self.assertEqual(rows[0]["deaths_data_status"], "unavailable_from_source")
            self.assertEqual(rows[0]["approximation_method"], adapter.APPROXIMATION_METHOD)
            meta=json.loads((root/"out"/"raw"/"opendengue_bangladesh_metadata.json").read_text())
            raw=root/"out"/"opendengue_bangladesh_raw.csv"
            self.assertEqual(meta["raw_file_sha256"], hashlib.sha256(raw.read_bytes()).hexdigest())
            self.assertEqual(meta["output_rows"], len(rows))

    def test_existing_overlap_conversion_is_preserved(self):
        first=adapter.month_to_epi_weeks(2021, 1, 310)
        self.assertEqual(first[0]["epi_week"], 53)
        self.assertEqual(sum(r["dengue_cases"] for r in first), 307)

    def test_invalid_empty_missing_and_w53_fail_without_replacement(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); out=root/"out"; out.mkdir(); existing=out/"dengue_cases.csv"; existing.write_text("old\n")
            bad=root/"bad.zip"; bad.write_bytes(b"not zip")
            self.assertEqual(adapter.main(bad, 2021, 2021, out), 1); self.assertEqual(existing.read_text(), "old\n")
            missing=root/"missing.zip"
            with zipfile.ZipFile(missing,"w") as z: z.writestr("readme.txt","x")
            self.assertEqual(adapter.main(missing, 2021, 2021, out), 1)
            empty=root/"empty.zip"; self.make_zip(empty,[{"adm_0_name":"INDIA","T_res":"Month","Year":"2021","dengue_total":"1","calendar_start_date":"2021-01-01"}])
            self.assertEqual(adapter.main(empty, 2021, 2021, out), 1)
            cols=["adm_0_name","T_res","Year","dengue_total"]
            missing_col=root/"missing_col.zip"; self.make_zip(missing_col,[],cols)
            self.assertEqual(adapter.main(missing_col, 2021, 2021, out), 1)
            w53=root/"w53.zip"; self.make_zip(w53,[{"adm_0_name":"BANGLADESH","T_res":"Month","Year":"2020","dengue_total":"100","calendar_start_date":"2020-12-01"}])
            self.assertEqual(adapter.main(w53, 2020, 2020, out), 1); self.assertEqual(existing.read_text(), "old\n")


if __name__ == "__main__": unittest.main()
