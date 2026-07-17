from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))

from feature_engineering import FEATURE_COLUMNS
from runtime_assessment import build_common_fold_plan
from runtime_assessment_policy import (
    RuntimeAssessmentPolicyError,
    load_and_validate_assessment_policy,
    select_planned_validation_indexes,
)


TARGET = "target_cases_next_2w"


def labelled_frame(row_count: int) -> pd.DataFrame:
    start = date.fromisocalendar(2021, 1, 1)
    records = []
    for index in range(row_count):
        monday = start + timedelta(weeks=index)
        iso_year, iso_week, _ = monday.isocalendar()
        record = {
            "epi_year": iso_year,
            "epi_week": iso_week,
            "cases": float(100 + index),
            TARGET: float(102 + index),
        }
        for feature_index, column in enumerate(FEATURE_COLUMNS, 1):
            record[column] = float(index + feature_index) / 10.0
        records.append(record)
    return pd.DataFrame.from_records(records)


class RuntimeFlexibleAssessmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.phase_two, _ = load_and_validate_assessment_policy("dhaka_south", "p2-v1")
        cls.phase_one, _ = load_and_validate_assessment_policy("dhaka_south", "p1.4d-1-v1")

    def test_minimum_and_dynamic_fold_counts(self):
        with self.assertRaises(RuntimeAssessmentPolicyError):
            select_planned_validation_indexes(156, 104, 1, 52, 68)
        for rows, expected_count in ((157, 52), (158, 53), (172, 67), (173, 68)):
            with self.subTest(rows=rows):
                plan, _ = build_common_fold_plan(labelled_frame(rows), self.phase_two)
                self.assertEqual(len(plan), expected_count)
                self.assertEqual([fold["sequence"] for fold in plan], list(range(1, expected_count + 1)))
                self.assertEqual(plan[0]["validationIndex"], 105)
                self.assertEqual(plan[-1]["validationIndex"], rows - 1)

    def test_recent_cap_retains_older_rows_in_expanding_training(self):
        for rows, expected_start in ((174, 106), (250, 182)):
            with self.subTest(rows=rows):
                plan, _ = build_common_fold_plan(labelled_frame(rows), self.phase_two)
                self.assertEqual(len(plan), 68)
                self.assertEqual(plan[0]["validationIndex"], expected_start)
                self.assertEqual(plan[-1]["validationIndex"], rows - 1)
                self.assertEqual(plan[0]["trainStartIndex"], 0)
                self.assertEqual(plan[0]["trainingRowCount"], expected_start - 1)
                self.assertEqual(plan[0]["trainEndExclusive"], expected_start - 1)
                self.assertEqual(plan[0]["embargoIndex"], expected_start - 1)

    def test_173_rows_preserve_exact_phase_one_fold_plan(self):
        frame = labelled_frame(173)
        phase_one_plan, phase_one_hash = build_common_fold_plan(frame, self.phase_one)
        phase_two_plan, phase_two_hash = build_common_fold_plan(frame, self.phase_two)
        self.assertEqual(phase_two_plan, phase_one_plan)
        self.assertEqual(phase_two_hash, phase_one_hash)

    def test_fold_selection_is_deterministic(self):
        frame = labelled_frame(250)
        first, first_hash = build_common_fold_plan(frame, self.phase_two)
        second, second_hash = build_common_fold_plan(frame.copy(), self.phase_two)
        self.assertEqual(first, second)
        self.assertEqual(first_hash, second_hash)
        self.assertEqual(
            tuple(fold["validationIndex"] for fold in first),
            select_planned_validation_indexes(250, 104, 1, 52, 68),
        )

    def test_temporal_and_numeric_contracts_fail_closed(self):
        duplicate = labelled_frame(157)
        duplicate.loc[1, ["epi_year", "epi_week"]] = duplicate.loc[0, ["epi_year", "epi_week"]]
        gap = labelled_frame(157)
        gap.loc[120:, "epi_week"] = gap.loc[120:, "epi_week"] + 1
        week_53 = labelled_frame(157)
        week_53.loc[0, ["epi_year", "epi_week"]] = [2020, 53]
        nonfinite = labelled_frame(157)
        nonfinite.loc[120, FEATURE_COLUMNS[0]] = np.inf
        with self.assertRaises(ValueError):
            build_common_fold_plan(duplicate, self.phase_two)
        with self.assertRaises(ValueError):
            build_common_fold_plan(gap, self.phase_two)
        with self.assertRaises(ValueError):
            build_common_fold_plan(week_53, self.phase_two)
        # Fold construction hashes matrices and must reject non-standard numeric evidence.
        with self.assertRaises((ValueError, OverflowError)):
            build_common_fold_plan(nonfinite, self.phase_two)


if __name__ == "__main__":
    unittest.main()
