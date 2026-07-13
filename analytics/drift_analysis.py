"""
drift_analysis.py
=================
Phase 0 stub: Detects year-over-year seasonality drift and peak-week shifts
in historical dengue case data.

Analyses:
    1. Peak week drift      : which epi week had maximum cases each year
    2. Peak intensity drift : year-over-year change in peak case count
    3. Season onset drift   : when cases first exceed a threshold each year
    4. Inter-annual trend   : linear regression on annual total cases

Motivation:
    Climate change, urbanisation, and vector control interventions can shift
    dengue seasonality patterns. Capturing drift improves forecast accuracy
    and motivates the use of year-specific seasonal encodings.

Output:
    seasonality_drift array added to validation_metrics.json.

Phase 1 replacement:
    Full drift analysis on validated historical epi data (2018–present).
"""

from __future__ import annotations

ONSET_THRESHOLD_CASES = 100  # cases/week to define season onset


def find_peak_week(weekly_cases: list[int]) -> tuple[int, int]:
    """Return (peak_epi_week, peak_cases) for a single year."""
    if not weekly_cases:
        return (0, 0)
    peak_idx = max(range(len(weekly_cases)), key=lambda i: weekly_cases[i])
    return (peak_idx + 1, weekly_cases[peak_idx])


def find_season_onset(weekly_cases: list[int], threshold: int = ONSET_THRESHOLD_CASES) -> int | None:
    """Return first epi week where cases exceed threshold."""
    for i, cases in enumerate(weekly_cases):
        if cases >= threshold:
            return i + 1
    return None


def compute_annual_totals(yearly_data: dict[int, list[int]]) -> dict[int, int]:
    """Sum cases per year."""
    return {year: sum(weeks) for year, weeks in yearly_data.items()}


def analyse_drift(yearly_data: dict[int, list[int]]) -> list[dict]:
    """
    Phase 0 stub: Compute drift metrics for each year.
    Phase 1: Will process real data.
    """
    results = []
    for year, weekly_cases in sorted(yearly_data.items()):
        peak_week, peak_cases = find_peak_week(weekly_cases)
        onset_week = find_season_onset(weekly_cases)
        results.append({
            "year": year,
            "peak_week": peak_week,
            "peak_cases": peak_cases,
            "season_onset_week": onset_week,
            "annual_total": sum(weekly_cases),
        })
    return results


if __name__ == "__main__":
    print("[drift_analysis] Phase 0 stub.")
    print(f"[drift_analysis] Season onset threshold: {ONSET_THRESHOLD_CASES} cases/week")
