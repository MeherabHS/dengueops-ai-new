"""
feature_engineering.py
=======================
DengueOps AI — Phase 2: Lag-Aware Feature Engineering

Builds the model feature matrix from raw dengue surveillance and climate data.
Produces a temporally-ordered, leakage-free feature table ready for model training
and backtesting in Phase 3.

Pipeline overview:
    Raw dengue cases + Raw climate data
        → merge on (epi_year, epi_week)
        → sort by (epi_year, epi_week)               ← required before any lag/shift
        → add_lag_features        (climate lags)
        → add_trend_features      (case lags, rolling means, growth rates)
        → add_seasonality_features (sin/cos, monsoon flags)
        → add_targets             (future case counts)
        → drop rows with NaN      (from lags at series start, targets at end)
        → save data/model_features.csv

Leakage prevention policy:
    - All input features must use only information available BEFORE the forecast week.
    - Climate lag features use values from 2 or 4 weeks prior.
    - Rolling means are computed on shifted series (shift(1)) so the current week
      is excluded from its own feature window.
    - Target columns (target_cases_next_1w, target_cases_next_2w) are OUTPUTS only
      and must never be used as model inputs.
    - The DataFrame is sorted by (epi_year, epi_week) before any shift/rolling
      to guarantee temporal ordering across year boundaries.

Usage:
    python analytics/feature_engineering.py

Output:
    data/model_features.csv

Requirements:
    Python 3.10+, pandas, numpy (no additional installs beyond requirements.txt)
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

from provenance import (
    DEFAULT_MANIFEST_PATH,
    PROVENANCE_COLUMNS,
    add_feature_provenance,
    load_compact_provenance,
)
from formula_registry import get_parameter

# ── Paths ────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DENGUE_PATH = ROOT / "data" / "dengue_cases.csv"
DEFAULT_CLIMATE_PATH = ROOT / "data" / "climate_data.csv"
DEFAULT_OUTPUT_PATH = ROOT / "data" / "model_features.csv"

# ── Seasonality week boundaries (Bangladesh context) ─────────────────────────
# Monsoon:       epi weeks 22–38  (June–September, peak rainfall)
# Post-monsoon:  epi weeks 38–50  (October–December, peak dengue risk)
MONSOON_START = int(get_parameter("FEATURE.SEASON_FLAGS", "monsoon_start"))
MONSOON_END = int(get_parameter("FEATURE.SEASON_FLAGS", "monsoon_end"))
POST_MONSOON_START = int(get_parameter("FEATURE.SEASON_FLAGS", "post_monsoon_start"))
POST_MONSOON_END = int(get_parameter("FEATURE.SEASON_FLAGS", "post_monsoon_end"))

# ── Constants ─────────────────────────────────────────────────────────────────
EPI_WEEKS_PER_YEAR = 52


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1: Load and merge raw data
# ─────────────────────────────────────────────────────────────────────────────

def load_raw_data(
    dengue_path: str | Path = DEFAULT_DENGUE_PATH,
    climate_path: str | Path = DEFAULT_CLIMATE_PATH,
) -> pd.DataFrame:
    """
    Load dengue cases and climate data, validate columns, and merge.

    Merge key: (epi_year, epi_week).
    date_start is taken from the dengue file; climate date_start is dropped
    to avoid duplicate columns.

    The merged DataFrame is sorted ascending by (epi_year, epi_week) immediately
    after merging. This ordering is a prerequisite for all subsequent shift() and
    rolling() operations to be temporally correct.

    Returns
    -------
    pd.DataFrame
        Merged, sorted DataFrame with columns from both source files.

    Raises
    ------
    FileNotFoundError
        If either input file does not exist.
    ValueError
        If required columns are missing or duplicate (epi_year, epi_week) pairs exist.
    """
    dengue_path = Path(dengue_path)
    climate_path = Path(climate_path)

    # ── File existence checks ─────────────────────────────────────────────────
    if not dengue_path.exists():
        raise FileNotFoundError(
            f"Dengue cases file not found: {dengue_path}\n"
            "Run: python analytics/generate_demo_data.py"
        )
    if not climate_path.exists():
        raise FileNotFoundError(
            f"Climate data file not found: {climate_path}\n"
            "Run: python analytics/generate_demo_data.py"
        )

    # ── Load ─────────────────────────────────────────────────────────────────
    dengue = pd.read_csv(dengue_path)
    climate = pd.read_csv(climate_path)

    # ── Column validation ────────────────────────────────────────────────────
    required_dengue = {"epi_year", "epi_week", "date_start", "city", "cases", "deaths"}
    required_climate = {"epi_year", "epi_week", "rainfall_mm", "avg_temp_c", "humidity_pct"}

    missing_dengue = required_dengue - set(dengue.columns)
    if missing_dengue:
        raise ValueError(f"dengue_cases.csv is missing columns: {sorted(missing_dengue)}")

    missing_climate = required_climate - set(climate.columns)
    if missing_climate:
        raise ValueError(f"climate_data.csv is missing columns: {sorted(missing_climate)}")

    # ── Merge ─────────────────────────────────────────────────────────────────
    # Drop date_start from climate to avoid _x/_y suffixes
    climate_cols = ["epi_year", "epi_week", "rainfall_mm", "avg_temp_c", "humidity_pct"]
    merged = pd.merge(
        dengue,
        climate[climate_cols],
        on=["epi_year", "epi_week"],
        how="inner",
        validate="1:1",   # enforces no duplicate merge keys
    )

    # ── Duplicate check ───────────────────────────────────────────────────────
    dupes = merged.duplicated(subset=["epi_year", "epi_week"])
    if dupes.any():
        raise ValueError(
            f"Duplicate (epi_year, epi_week) rows found after merge: "
            f"{merged[dupes][['epi_year','epi_week']].values.tolist()}"
        )

    # ── Sort — CRITICAL for lag correctness ──────────────────────────────────
    # All shift() and rolling() calls below assume rows are ordered
    # chronologically (earliest first). Sorting here ensures this invariant
    # even if source files are not pre-sorted.
    merged = merged.sort_values(["epi_year", "epi_week"]).reset_index(drop=True)

    return merged


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2: Lagged climate features
# ─────────────────────────────────────────────────────────────────────────────

def add_lag_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add lagged climate features: rainfall, temperature, and humidity at 2 and 4 weeks.

    Governance note:
        Two- and four-week climate lags are provisional candidate inputs. They
        have not been established as causal, optimal, or locally validated for
        Dhaka. Their values are governed by FEATURE.CLIMATE_LAGS.

    Leakage note:
        All shifted values use only past observations. At row t, rainfall_lag_2w
        contains rainfall from row t-2, which is strictly prior to the forecast
        target period. No future climate data is introduced.

    Parameters
    ----------
    df : pd.DataFrame
        Must be sorted by (epi_year, epi_week) ascending.

    Returns
    -------
    pd.DataFrame
        Input DataFrame with six new lag columns appended.
    """
    out = df.copy()

    # Rainfall lags
    out["rainfall_lag_2w"] = out["rainfall_mm"].shift(2)
    out["rainfall_lag_4w"] = out["rainfall_mm"].shift(4)

    # Temperature lags
    out["temp_lag_2w"] = out["avg_temp_c"].shift(2)
    out["temp_lag_4w"] = out["avg_temp_c"].shift(4)

    # Humidity lags
    out["humidity_lag_2w"] = out["humidity_pct"].shift(2)
    out["humidity_lag_4w"] = out["humidity_pct"].shift(4)

    return out


# ─────────────────────────────────────────────────────────────────────────────
# STEP 3: Dengue trend features
# ─────────────────────────────────────────────────────────────────────────────

def add_trend_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add dengue case trend features: lagged case counts, rolling means, growth rates.

    Rolling mean leakage prevention:
        Rolling windows are applied to a version of the cases column that has been
        shifted by 1 week (shift(1)). This ensures that at row t:
            - cases_rolling_3w  = mean( cases[t-3], cases[t-2], cases[t-1] )
            - cases_rolling_4w  = mean( cases[t-4], ..., cases[t-1] )
            - cases_rolling_8w  = mean( cases[t-8], ..., cases[t-1] )

        If rolling were applied directly to the unshifted series, the window at row t
        would include cases[t] itself, which is the value we are trying to predict —
        a data leakage error.

    Growth rate leakage prevention:
        Growth rates are ratios of lagged values only:
            growth_rate_1w = cases_lag_1w / cases_lag_2w
            growth_rate_2w = cases_lag_1w / cases_lag_4w
        Both numerator and denominator are strictly prior-week observations.
        Division-by-zero is handled by replacing the result with 1.0 (no growth).

    Parameters
    ----------
    df : pd.DataFrame
        Must contain 'cases' column and be sorted by (epi_year, epi_week).

    Returns
    -------
    pd.DataFrame
        Input DataFrame with trend features appended.
    """
    out = df.copy()

    # ── Point lags ────────────────────────────────────────────────────────────
    out["cases_lag_1w"] = out["cases"].shift(1)
    out["cases_lag_2w"] = out["cases"].shift(2)
    out["cases_lag_4w"] = out["cases"].shift(4)

    # ── Rolling means (computed on shift(1) series to exclude current week) ───
    # Leakage-free window: all lookback values are strictly prior to week t.
    cases_shifted = out["cases"].shift(1)
    out["cases_rolling_3w"] = cases_shifted.rolling(window=3, min_periods=2).mean()
    out["cases_rolling_4w"] = cases_shifted.rolling(window=4, min_periods=3).mean()
    out["cases_rolling_8w"] = cases_shifted.rolling(window=8, min_periods=5).mean()

    # ── Growth rates ──────────────────────────────────────────────────────────
    # growth_rate_1w: week-over-week ratio (1w ago vs 2w ago)
    # growth_rate_2w: 4-week-span ratio (1w ago vs 4w ago)
    # Replace inf and NaN from zero denominators with 1.0 (neutral growth)
    with np.errstate(divide="ignore", invalid="ignore"):
        gr1 = np.where(
            out["cases_lag_2w"] > 0,
            out["cases_lag_1w"] / out["cases_lag_2w"],
            1.0,
        )
        gr2 = np.where(
            out["cases_lag_4w"] > 0,
            out["cases_lag_1w"] / out["cases_lag_4w"],
            1.0,
        )

    out["growth_rate_1w"] = np.round(gr1.astype(float), 4)
    out["growth_rate_2w"] = np.round(gr2.astype(float), 4)

    return out


# ─────────────────────────────────────────────────────────────────────────────
# STEP 4: Seasonality features
# ─────────────────────────────────────────────────────────────────────────────

def add_seasonality_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add cyclic seasonality and epidemiological calendar features.

    Sine/cosine encoding:
        Raw epi_week is an integer (1–52). Using it directly as a model input
        would imply that week 52 and week 1 are far apart — but they are
        consecutive. Sine and cosine encoding maps epi_week to a unit circle,
        ensuring week 52 and week 1 are adjacent:

            epi_week_sin = sin(2π × epi_week / 52)
            epi_week_cos = cos(2π × epi_week / 52)

        Together they provide unique 2D coordinates for each week of the year
        that preserve cyclicity. Both are required; using only the sine loses
        the distinction between rising and falling halves of the year.

    Seasonal flags:
        The configured week ranges are provisional calendar candidates, not
        validated Dhaka epidemiological thresholds.

    Leakage note:
        Seasonality features depend only on the epi_week number, which is
        known in advance (calendar-derived). No observed case or climate data
        is used here.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain 'epi_week' column.

    Returns
    -------
    pd.DataFrame
        Input DataFrame with four seasonality columns appended.
    """
    out = df.copy()

    theta = 2 * math.pi * out["epi_week"] / EPI_WEEKS_PER_YEAR
    out["epi_week_sin"] = np.sin(theta).round(6)
    out["epi_week_cos"] = np.cos(theta).round(6)

    out["monsoon_flag"] = (
        (out["epi_week"] >= MONSOON_START) & (out["epi_week"] <= MONSOON_END)
    ).astype(int)

    out["post_monsoon_flag"] = (
        (out["epi_week"] >= POST_MONSOON_START) & (out["epi_week"] <= POST_MONSOON_END)
    ).astype(int)

    return out


# ─────────────────────────────────────────────────────────────────────────────
# STEP 5: Target columns
# ─────────────────────────────────────────────────────────────────────────────

def add_targets(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add forecast target columns: case counts 1 and 2 weeks ahead.

    Target definitions:
        target_cases_next_1w = cases at week t+1
        target_cases_next_2w = cases at week t+2

    Implemented via negative shift (shift(-n) looks forward in time):
        shift(-1) at row t gives the value at row t+1.

    IMPORTANT — these are OUTPUT columns only:
        target_cases_next_1w and target_cases_next_2w must NEVER be used as
        model input features. Their purpose is to provide the supervised
        learning label during training and evaluation. The last 1–2 rows of
        the dataset will have NaN targets (no future observations available)
        and are removed in the final cleaning step.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain 'cases' column and be sorted by (epi_year, epi_week).

    Returns
    -------
    pd.DataFrame
        Input DataFrame with two target columns appended.
    """
    out = df.copy()

    # shift(-1): at row t, value from row t+1 (1 week ahead)
    out["target_cases_next_1w"] = out["cases"].shift(-1)

    # shift(-2): at row t, value from row t+2 (2 weeks ahead)
    out["target_cases_next_2w"] = out["cases"].shift(-2)

    return out


# ─────────────────────────────────────────────────────────────────────────────
# STEP 6: Master builder
# ─────────────────────────────────────────────────────────────────────────────

# Columns that constitute the model feature matrix (no targets, no raw cases)
FEATURE_COLUMNS = [
    # Lagged climate
    "rainfall_lag_2w",
    "rainfall_lag_4w",
    "temp_lag_2w",
    "temp_lag_4w",
    "humidity_lag_2w",
    "humidity_lag_4w",
    # Case lags
    "cases_lag_1w",
    "cases_lag_2w",
    "cases_lag_4w",
    # Rolling means
    "cases_rolling_3w",
    "cases_rolling_4w",
    "cases_rolling_8w",
    # Growth rates
    "growth_rate_1w",
    "growth_rate_2w",
    # Seasonality
    "epi_week_sin",
    "epi_week_cos",
    "monsoon_flag",
    "post_monsoon_flag",
]

TARGET_COLUMNS = [
    "target_cases_next_1w",
    "target_cases_next_2w",
]

BASE_COLUMNS = [
    "epi_year",
    "epi_week",
    "date_start",
    "city",
    "cases",
    "deaths",
    "rainfall_mm",
    "avg_temp_c",
    "humidity_pct",
]


def _construct_feature_frame(
    dengue_path: str | Path = DEFAULT_DENGUE_PATH,
    climate_path: str | Path = DEFAULT_CLIMATE_PATH,
) -> tuple[pd.DataFrame, int]:
    """Build the shared feature frame before supervised/inference filtering."""
    df = load_raw_data(dengue_path, climate_path)
    raw_rows = len(df)

    df = add_lag_features(df)
    df = add_trend_features(df)
    df = add_seasonality_features(df)
    df = add_targets(df)

    all_cols = BASE_COLUMNS + FEATURE_COLUMNS + TARGET_COLUMNS
    return df[all_cols], raw_rows


def _round_feature_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Apply the existing output precision consistently to every feature view."""
    out = df.copy()
    float_cols = [c for c in FEATURE_COLUMNS if c not in ("monsoon_flag", "post_monsoon_flag")]
    out[float_cols] = out[float_cols].round(4)
    out[["rainfall_mm", "avg_temp_c", "humidity_pct"]] = (
        out[["rainfall_mm", "avg_temp_c", "humidity_pct"]].round(2)
    )
    return out


def build_features(
    dengue_path: str | Path = DEFAULT_DENGUE_PATH,
    climate_path: str | Path = DEFAULT_CLIMATE_PATH,
    output_path: str | Path | None = DEFAULT_OUTPUT_PATH,
    manifest_path: str | Path | None = None,
) -> tuple[pd.DataFrame, int]:
    """
    Build the complete model feature matrix from raw data files.

    Processing steps:
        1. Load and merge dengue cases + climate data
        2. Add lagged climate features (2w, 4w)
        3. Add dengue trend features (lags, rolling means, growth rates)
        4. Add seasonality features (sin/cos, monsoon flags)
        5. Add forecast target columns
        6. Drop rows with NaN values (lag burn-in at start, missing targets at end)
        7. Reset index
        8. Optionally save to output_path

    Row count note:
        Raw rows will be reduced by the maximum lag window (8 weeks at series start)
        plus the target lookahead (2 weeks at series end). Rows dropped are never
        usable for training because either their features or targets are undefined.

    Parameters
    ----------
    dengue_path : str or Path
        Path to dengue_cases.csv.
    climate_path : str or Path
        Path to climate_data.csv.
    output_path : str, Path, or None
        If provided, save the feature matrix to this path as CSV.
        Pass None to suppress file output.

    Returns
    -------
    pd.DataFrame
        Clean feature matrix with BASE_COLUMNS + FEATURE_COLUMNS + TARGET_COLUMNS.
    """
    # ── Build pipeline ────────────────────────────────────────────────────────
    use_provenance = manifest_path is not None or (
        Path(dengue_path).resolve() == DEFAULT_DENGUE_PATH.resolve()
        and Path(climate_path).resolve() == DEFAULT_CLIMATE_PATH.resolve()
    )
    provenance = load_compact_provenance(manifest_path or DEFAULT_MANIFEST_PATH) if use_provenance else None
    df, raw_rows = _construct_feature_frame(dengue_path, climate_path)

    # ── Drop NaN rows ─────────────────────────────────────────────────────────
    # NaN sources:
    #   - Leading NaNs: lag features require 4–8 prior rows (series start burn-in)
    #   - Trailing NaNs: target columns shift forward, last 2 rows have no label
    df = df.dropna().reset_index(drop=True)

    # ── Round floats for clean CSV output ─────────────────────────────────────
    df = _round_feature_frame(df)
    if provenance is not None:
        df = add_feature_provenance(df, provenance)

    # ── Save ──────────────────────────────────────────────────────────────────
    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(output_path, index=False)

    return df, raw_rows


def build_inference_features(
    dengue_path: str | Path = DEFAULT_DENGUE_PATH,
    climate_path: str | Path = DEFAULT_CLIMATE_PATH,
    manifest_path: str | Path | None = None,
) -> pd.DataFrame:
    """
    Build target-independent rows suitable for final forecast inference.

    Unlike build_features, this path does not require future target values.
    Rows are retained when all base fields and model-input features are complete,
    allowing the latest observed week to be used as the forecast origin.
    """
    use_provenance = manifest_path is not None or (
        Path(dengue_path).resolve() == DEFAULT_DENGUE_PATH.resolve()
        and Path(climate_path).resolve() == DEFAULT_CLIMATE_PATH.resolve()
    )
    provenance = load_compact_provenance(manifest_path or DEFAULT_MANIFEST_PATH) if use_provenance else None
    df, _ = _construct_feature_frame(dengue_path, climate_path)
    required_columns = BASE_COLUMNS + FEATURE_COLUMNS
    df = df.dropna(subset=required_columns).reset_index(drop=True)
    df = _round_feature_frame(df)
    return add_feature_provenance(df, provenance) if provenance is not None else df


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    print()
    print("=" * 62)
    print("  DengueOps AI - Phase 2: Feature Engineering")
    print("=" * 62)

    df, raw_rows = build_features()
    feature_rows = len(df)
    dropped = raw_rows - feature_rows

    print(f"\n  Input")
    print(f"    Raw rows (merged):      {raw_rows}")
    print(f"    Dropped (lag burn-in,")
    print(f"    missing targets):       {dropped}")
    print(f"    Feature rows (usable):  {feature_rows}")

    print(f"\n  Feature columns ({len(FEATURE_COLUMNS)}):")
    for col in FEATURE_COLUMNS:
        series = df[col]
        print(f"    {col:<26}  min={series.min():8.3f}  max={series.max():8.3f}  "
              f"nulls={series.isna().sum()}")

    print(f"\n  Target columns ({len(TARGET_COLUMNS)}):")
    for col in TARGET_COLUMNS:
        series = df[col]
        print(f"    {col:<26}  min={series.min():8.0f}  max={series.max():8.0f}  "
              f"nulls={series.isna().sum()}")

    print(f"\n  Year coverage:")
    for yr in sorted(df["epi_year"].unique()):
        sub = df[df["epi_year"] == yr]
        print(f"    {yr}  rows={len(sub):3d}  "
              f"weeks {sub['epi_week'].min()}-{sub['epi_week'].max()}  "
              f"peak_cases={sub['cases'].max()}")

    print(f"\n  Output")
    print(f"    Path: {DEFAULT_OUTPUT_PATH}")
    print(f"    Columns: {len(df.columns)} total "
          f"({len(BASE_COLUMNS)} base + {len(FEATURE_COLUMNS)} features + {len(TARGET_COLUMNS)} targets)")
    print()
    print("  REMINDER: target_cases_next_1w and target_cases_next_2w")
    print("  are training labels only. They must NOT be used as model inputs.")
    print()
    print("=" * 62)
    print("  Feature engineering complete.")
    print("=" * 62)
    print()


if __name__ == "__main__":
    main()
