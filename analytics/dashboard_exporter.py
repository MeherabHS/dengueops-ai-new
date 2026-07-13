"""
dashboard_exporter.py
=====================
DengueOps AI — Phase 6: Dashboard-Ready JSON Exporter

Reads all analytics pipeline outputs and produces three clean,
frontend-friendly JSON files for the Next.js dashboard.

Philosophy:
    The Python pipeline is not the evaluator-facing product. It is the
    analytics engine. All relevant outputs are exported into dashboard-ready
    JSON files and visualised in the Next.js dashboard. Evaluators do not
    need to inspect terminal logs or raw intermediate files.

Inputs  (must exist before running):
    data/forecast_output.json
    data/validation_metrics.json
    data/directives.json
    data/zones.json
    data/facilities.json
    data/inventory.json
    data/dengue_cases.csv       (optional, for case_trend chart)
    data/climate_data.csv       (optional, for case_trend rainfall overlay)
    data/model_features.csv     (optional, feature coverage info)

Outputs:
    data/dashboard_summary.json  — headline metrics + uncertainty + model evidence
    data/model_comparison.json   — model table with roles + selection rationale
    data/chart_data.json         — all chart arrays for dashboard visualisation

Usage:
    python analytics/dashboard_exporter.py
"""

from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from provenance import artifact_provenance, assert_same_provenance, derive_data_mode
from formula_registry import get_parameter
from explainability_engine import validate_model_explainability, validate_selected_model_explainability
from validation_backtest import validate_rolling_validation
from model_candidates import (OUTPUT_PATH as CANDIDATE_COMPARISON_PATH,
    REGISTRY_PATH as CANDIDATE_REGISTRY_PATH, validate_comparison_artifact)

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT         = Path(__file__).resolve().parent.parent
DATA_DIR     = ROOT / "data"

FORECAST_PATH   = DATA_DIR / "forecast_output.json"
VALIDATION_PATH = DATA_DIR / "validation_metrics.json"
DIRECTIVES_PATH = DATA_DIR / "directives.json"
ZONES_PATH      = DATA_DIR / "zones.json"
FACILITIES_PATH = DATA_DIR / "facilities.json"
INVENTORY_PATH  = DATA_DIR / "inventory.json"
CASES_PATH      = DATA_DIR / "dengue_cases.csv"
CLIMATE_PATH    = DATA_DIR / "climate_data.csv"
FEATURES_PATH   = DATA_DIR / "model_features.csv"

DASHBOARD_SUMMARY_PATH = DATA_DIR / "dashboard_summary.json"
MODEL_COMPARISON_PATH  = DATA_DIR / "model_comparison.json"
CHART_DATA_PATH        = DATA_DIR / "chart_data.json"
MODEL_CARD_PATH        = DATA_DIR / "model_card.json"
EXPLAINABILITY_PATH    = DATA_DIR / "model_explainability.json"
SELECTED_EXPLAINABILITY_PATH = DATA_DIR / "selected_model_explainability.json"
ROLLING_VALIDATION_PATH = DATA_DIR / "rolling_validation.json"

# ── Required inputs ───────────────────────────────────────────────────────────
REQUIRED_INPUTS = [
    FORECAST_PATH,
    VALIDATION_PATH,
    DIRECTIVES_PATH,
]

# ── I/O helpers ───────────────────────────────────────────────────────────────

def load_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(
            f"Required input not found: {path}\n"
            "Run the full pipeline first:\n"
            "  python analytics/run_pipeline.py"
        )
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_csv_safe(path: Path) -> pd.DataFrame | None:
    """Load a CSV, returning None if absent (optional inputs)."""
    if not path.exists():
        return None
    return pd.read_csv(path)


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ── Output 1: dashboard_summary.json ─────────────────────────────────────────

def build_dashboard_summary(
    forecast: dict,
    validation: dict,
    directives: dict,
    model_card: dict | None = None,
    explainability: dict | None = None,
    rolling: dict | None = None,
    candidate_comparison: dict | None = None,
) -> dict:
    """
    Build the headline-level summary consumed by the dashboard's hero section,
    scenario selector, and model evidence panels.
    """
    scenarios = forecast.get("preparedness_scenarios", {})
    expected  = scenarios.get("expected_case", {})
    best      = scenarios.get("best_case", {})
    worst     = scenarios.get("worst_case", {})

    # ── Model evidence calculations ───────────────────────────────────────────
    metrics      = validation.get("metrics", {})
    naive_mae    = float(metrics.get("naive", {}).get("mae", 0))
    ma_mae       = float(metrics.get("moving_average", {}).get("mae", 0))
    gbr_mae      = float(metrics.get("gradient_boosting", {}).get("mae", 0))
    gbr_rmse     = float(metrics.get("gradient_boosting", {}).get("rmse", 0))
    active_metrics = (candidate_comparison or {}).get("aggregate_metrics", {}).get("random_forest", {})
    active_mae = float(active_metrics.get("mae", 0))
    active_rmse = float(active_metrics.get("rmse", 0))

    mae_vs_naive = round((1 - gbr_mae / naive_mae) * 100, 1) if naive_mae > 0 else None
    mae_vs_ma    = round((1 - gbr_mae / ma_mae) * 100, 1)    if ma_mae > 0    else None

    # ── Directives summary ────────────────────────────────────────────────────
    s = directives.get("summary", {})

    provenance = forecast.get("provenance")
    data_mode = derive_data_mode(provenance) if provenance else "synthetic"
    mode_label = {"synthetic": "Synthetic Data", "real": "Real Data", "mixed": "Mixed-Source Data"}[data_mode]
    source_status = (
        f"Case source: {provenance['case_source']}; climate source: {provenance['climate_source']}; "
        f"operational source: {provenance['operational_source']}. No patient-level data used."
        if provenance else "No patient-level data used."
    )
    validation_disclaimer = {
        "synthetic": "Validation uses synthetic inputs and demonstrates prototype pipeline behaviour, not real-world accuracy.",
        "real": "Validation uses non-synthetic sources recorded in the input manifest; deployment-grade accuracy is not claimed.",
        "mixed": "Validation uses mixed synthetic and non-synthetic sources recorded in the input manifest; deployment-grade accuracy is not claimed.",
    }[data_mode]
    result = {
        "provenance": provenance,
        "project": {
            "title":       "DengueOps AI",
            "subtitle":    "Simulation-Based Dengue Surge Preparedness Decision Support"
                           " for Dhaka South",
            "track":       "Health Data Analytics & Predictive Systems",
            "conference":  "IEEE ICADHI",
            "mode":        mode_label,
            "last_updated": forecast.get("date_generated", ""),
            "data_status": source_status,
        },
        "headline_metrics": {
            "forecast_cases":                int(forecast.get("forecast_cases", 0)),
            "growth_factor":                 float(forecast.get("growth_factor", 1.0)),
            # TD-P03A-LEGACY-RISK-FIELDS: compatibility only; canonical fields follow.
            "risk_level":                    forecast.get("risk_level", ""),
            "risk_score":                    int(forecast.get("risk_score", 0)),
            "experimental_growth_score":      int(forecast.get("experimental_growth_score", forecast.get("risk_score", 0))),
            "forecast_growth_category":       forecast.get("forecast_growth_category", ""),
            "target_epi_week":               forecast.get("target_epi_week"),
            "target_epi_year":               forecast.get("target_epi_year"),
            "highest_priority_zone":         s.get("highest_priority_zone", ""),
            "highest_pressure_facility":     s.get("highest_pressure_facility", ""),
            "critical_supply_alerts":        int(s.get("critical_supply_alerts", 0)),
            "facilities_with_expected_bed_gap": int(s.get("facilities_with_expected_bed_gap", 0)),
            "total_facilities":              int(s.get("total_facilities", 0)),
            "total_public_government_anchors": int(s.get("total_public_government_anchors", 0)),
            "critical_priority_zones":       int(s.get("critical_priority_zones", 0)),
        },
        "uncertainty": {
            **forecast.get("forecast_uncertainty", {}),
            "covered_fold_count": (model_card or {}).get("covered_fold_count"),
            "calibration_warmup_fold_count": (model_card or {}).get("calibration_warmup_fold_count"),
            "lower_miss_count": (model_card or {}).get("lower_miss_count"),
            "upper_miss_count": (model_card or {}).get("upper_miss_count"),
            "interval_width_summary": (model_card or {}).get("interval_width_summary"),
            "average_interval_width": ((model_card or {}).get("interval_width_summary") or {}).get("average_interval_width"),
            "median_interval_width": ((model_card or {}).get("interval_width_summary") or {}).get("median_interval_width"),
            "minimum_interval_width": ((model_card or {}).get("interval_width_summary") or {}).get("minimum_interval_width"),
            "maximum_interval_width": ((model_card or {}).get("interval_width_summary") or {}).get("maximum_interval_width"),
            "uncertainty_method": (model_card or {}).get("uncertainty_method"),
            "uncertainty_method_version": (model_card or {}).get("uncertainty_method_version"),
            "residual_source_artifact_path": (model_card or {}).get("residual_source_artifact_path"),
            "method_label": "Prequential expanding absolute-residual quantile",
            "range_label": "Empirical forecast range",
            "method_note": (
                "Temporally evaluated on deterministic synthetic RF rolling residuals. "
                "Historical empirical coverage is not a probability guarantee; this is not a prediction interval."
            ),
        },
        "preparedness_scenarios": {
            "best_case": best, "expected_case": expected, "worst_case": worst,
            "method": forecast.get("preparedness_scenario_method"),
            "status": "legacy_rf_rmse_planning_sensitivity_separate_from_forecast_uncertainty",
        },
        "workflow_metadata": {
            "runtime_connector_status": "pending_p1.4",
            "current_approved_model_id": forecast.get("current_forecast_model"),
            "current_approved_model_label": "Random Forest",
            "deployment_context": (model_card or {}).get("data_mode", data_mode),
            "deployment_gate": forecast.get("deployment_gate"),
            "forecast_horizon_days": forecast.get("horizon_days"),
            "dataset_reassessment_required": True,
            "validation_status": (forecast.get("provenance") or {}).get("validation_status"),
            "accepted_period": (model_card or {}).get("training_period"),
        },
        "model_evidence": {
            "best_model":                     "random_forest",
            "best_model_display":             "Random Forest",
            "best_model_reason":              "Lowest eligible MAE under the declared P1.2A rolling-origin rule.",
            "validation_design":              "68-fold expanding-window rolling-origin candidate comparison",
            "train_rows":                     173,
            "test_rows":                      68,
            "active_model_mae":               active_mae,
            "active_model_rmse":              active_rmse,
            "active_rolling_metrics_source":  "candidate_model_comparison.json",
            "legacy_gbr_holdout":             {"mae": gbr_mae, "rmse": gbr_rmse, "status": "historical_compatibility_only"},
            "mae_reduction_vs_naive_pct":     mae_vs_naive,
            "mae_reduction_vs_moving_average_pct": mae_vs_ma,
            "disclaimer": validation_disclaimer,
        },
        "operational_summary": {
            "total_recommendations":          int(s.get("total_recommendations", 0)),
            "critical_priority_zones":        int(s.get("critical_priority_zones", 0)),
            "facilities_with_expected_bed_gap": int(s.get("facilities_with_expected_bed_gap", 0)),
            "facilities_with_worst_case_bed_gap": int(s.get("facilities_with_worst_case_bed_gap", 0)),
            "critical_supply_alerts":         int(s.get("critical_supply_alerts", 0)),
            "highest_priority_zone":          s.get("highest_priority_zone", ""),
            "highest_pressure_facility":      s.get("highest_pressure_facility", ""),
        },
        "ethics_and_assumptions": [
            f"Input data mode is {data_mode}; exact sources are recorded in artifact provenance.",
            "No patient-level data is collected or processed.",
            "Facility identity and readiness status are source-specific; synthetic benchmark facilities are wholly synthetic.",
            "Facility stock and bed readiness values are synthetic demonstration values.",
            "Spatial case allocation is a heuristic; zone-level counts are not "
            "precision estimates.",
            "Outputs are simulated planning suggestions and are not approved operational recommendations.",
        ],
    }
    if rolling is not None:
        winner = min(rolling["model_comparison"], key=lambda item: item["mae"])
        result["rolling_validation"] = {
            "primary_validation": False, "evidence_status": "historical_compatibility_only", "active_model_evidence": False,
            "validation_method": rolling["validation_method"], "fold_count": rolling["fold_count"],
            "initial_training_window": rolling["initial_training_window"], "horizon_weeks": rolling["horizon_weeks"],
            "step_weeks": rolling["step_weeks"], "label_availability_policy": rolling["label_availability_policy"],
            "aggregate_metrics": rolling["aggregate_metrics"], "model_comparison": rolling["model_comparison"],
            "historical_winner": winner["model_name"],
            "variability_summary": rolling["variability_summary"], "period_summary": rolling["period_summary"],
            "permutation_stability_status": rolling["permutation_stability_status"], "limitations": rolling["limitations"],
            "legacy_holdout": {"validation_role": validation.get("validation_role"), "validation_method": validation.get("validation_design"),
                               "metrics": validation.get("metrics"), "uncertainty_input": "not_used_for_active_uncertainty"},
        }
    if candidate_comparison is None:
        result["candidate_model_comparison"] = {
            "model_selection_status": "not_run_current_pipeline", "comparison_selected_model": None,
            "current_forecast_model": "gradient_boosting", "adoption_status": "not_adopted_p1.2a",
            "message": "Candidate comparison was not run in the current pipeline; prior metrics and winner are not displayed.",
        }
    else:
        result["candidate_model_comparison"] = {
            "model_selection_status": "comparison_complete_and_adopted",
            "comparison_selected_model": candidate_comparison["comparison_selected_model"],
            "comparison_selected_model_reason": candidate_comparison["comparison_selected_model_reason"],
            "current_forecast_model": forecast["current_forecast_model"],
            "adoption_status": forecast["adoption_status"], "adoption_policy_version": forecast["adoption_policy_version"],
            "selection_policy": candidate_comparison["selection_policy"],
            "primary_metric": candidate_comparison["primary_metric"],
            "aggregate_metrics": candidate_comparison["aggregate_metrics"], "wins_ties_losses": candidate_comparison["wins_ties_losses"],
            "selection_eligibility": candidate_comparison["selection_eligibility"], "model_failures": candidate_comparison["model_failures"],
            "limitations": candidate_comparison["limitations"],
            "warning": "Models were compared on the same deterministic synthetic rolling-origin folds. The selected model is the best-performing demonstration candidate under the declared rule, not a proven real-world dengue model.",
            "active_model_rolling_metrics": candidate_comparison["aggregate_metrics"]["random_forest"],
            "uncertainty_source": "Temporally evaluated synthetic empirical forecast range from prior-only Random Forest rolling residuals",
        }
    for key in (
        "formula_registry_version", "formula_registry_sha256", "formula_ids_used",
        "deployment_gate", "formula_validation_status", "formula_policy",
    ):
        result[key] = directives.get(key, forecast.get(key, validation.get(key)))
    if explainability is None:
        result["feature_importance"] = {
            "status": "not_generated",
            "message": "Run-specific feature diagnostics were not generated for this run. No placeholder or prior-run values are displayed.",
            "formula_id": "EVIDENCE.FEATURE_IMPORTANCE",
        }
    else:
        ordered = sorted(explainability["feature_ranking"], key=lambda item: (-item["permutation_mean"], item["feature_index"]))
        rankings = [{**item, "impurity_importance": item["native_importance"],
                     "rank_by_permutation": rank, "rank_by_impurity": rank,
                     "rank_disagreement": False, "permutation_is_zero": item["permutation_mean"] == 0}
                    for rank, item in enumerate(ordered, start=1)]
        result["feature_importance"] = {
            "status": explainability["availability_status"],
            "title": "Selected Random Forest Feature Diagnostics",
            "formula_id": "EVIDENCE.FEATURE_IMPORTANCE",
            "estimator_role": explainability["estimator_role"],
            "model_id": explainability["selected_model_id"],
            "model_family": explainability["model_family"],
            "model_version": explainability["selected_model_explainability_version"],
            "methods": {
                "primary": {"id": "holdout_permutation_importance", "label": "Holdout permutation importance", **explainability["permutation_settings"]},
                "secondary": {"id": "native_random_forest_impurity_importance", "label": "Native Random Forest impurity importance"},
            },
            "evaluation_split": explainability["evaluation_split"],
            "validation_period": explainability["validation_period"],
            "stability_status": explainability["rolling_importance_stability_status"],
            "feature_ranking": rankings,
            "non_causal_warning": explainability["limitations"][1],
            "split_warning": explainability["limitations"][0],
            "stability_warning": "Random Forest rolling importance stability was not evaluated across temporal folds.",
            "synthetic_warning": "Rankings may reflect relationships embedded in the synthetic benchmark data and may not transfer to real surveillance data.",
            "negative_importance_policy": explainability["negative_importance_policy"],
            "correlated_feature_warning": "Correlated lag features may divide, mask, or substitute for one another in both diagnostic methods.",
            "causal_interpretation_allowed": explainability["causal_interpretation_allowed"],
            "provenance": explainability["provenance"],
            "historical_gbr_evidence": {"artifact_path": "data/model_explainability.json", "status": "historical_compatibility_only", "active_model_evidence": False},
        }
    if model_card is not None:
        statements = model_card["maturity_statements"]
        result["deployment_profile"] = {
            "profile_id": model_card["deployment_id"],
            "profile_status": provenance.get("deployment_profile_status"),
            "demonstration_status": model_card["data_mode"],
            "maturity_statement": statements["maturity"],
            "demonstration_statement": statements["demonstration"],
            "prohibited_claim": statements["prohibited_claim"],
            "notification_wording": statements["notification"],
            "deployment_gate": model_card["deployment_gate"],
            "evidence_status": "empty_registry" if not model_card["evidence_ids"] else "linked_evidence",
            "approval_status": model_card["approval_status"],
        }
        result["historical_gbr_evidence"] = model_card.get("retained_legacy_gbr_evidence")
    return result


# ── Output 2: model_comparison.json ───────────────────────────────────────────

MODEL_META: dict[str, dict] = {
    "naive": {
        "model_name": "Naive Baseline",
        "role":       "Predicts next value = last observed value. "
                      "Establishes the minimum bar any model must exceed.",
    },
    "moving_average": {
        "model_name": "Moving Average Baseline (4-week)",
        "role":       "Predicts next value = rolling 4-week mean. "
                      "Tests whether trend smoothing adds value over naive.",
    },
    "gradient_boosting": {
        "model_name": "Gradient Boosting Regressor (scikit-learn)",
        "role":       "Selected tabular ML model. Trained on lag features, "
                      "rolling statistics, and seasonal encodings.",
    },
}


def build_model_comparison(validation: dict, rolling: dict | None = None) -> dict:
    """
    Build a clean model comparison table with rationale text.
    Used by the Technical Validation view and ModelEvaluationPanel.
    """
    if rolling is not None:
        winner = min(rolling["model_comparison"], key=lambda item: item["mae"])["model_name"]
        models = []
        for row in rolling["model_comparison"]:
            key = row["model_name"]
            models.append({"model_key": key, "model_name": MODEL_META[key]["model_name"], "role": MODEL_META[key]["role"],
                           "is_selected": key == winner, **{k: v for k, v in row.items() if k != "model_name"},
                           "mape": rolling["aggregate_metrics"][key]["mape"]})
        return {"provenance": rolling["provenance"], "target": rolling["target"], "horizon": "14 days (2 weeks ahead)",
                "validation_design": rolling["validation_method"], "best_model": winner, "models": models,
                "selection_explanation": f"{winner} has the lowest aggregate MAE across the rolling-origin folds.",
                "leakage_prevention": "A one-row label-availability embargo excludes the row whose target is unavailable at each origin.",
                "notes": rolling["limitations"]}
    metrics  = validation.get("metrics", {})
    best_key = validation.get("best_model", "gradient_boosting")

    models_out = []
    for key, meta in MODEL_META.items():
        m = metrics.get(key, {})
        models_out.append({
            "model_key":  key,
            "model_name": meta["model_name"],
            "role":       meta["role"],
            "is_selected": key == best_key,
            "mae":  round(float(m.get("mae",  0)), 2),
            "rmse": round(float(m.get("rmse", 0)), 2),
            "mape": round(float(m.get("mape", 0)), 2),
        })

    # Compute improvement ratios
    gbr = metrics.get("gradient_boosting", {})
    naive = metrics.get("naive", {})
    gbr_mae  = float(gbr.get("mae", 1))
    naive_mae = float(naive.get("mae", 1))

    return {
        "provenance": validation.get("provenance"),
        "target":            validation.get("target", "target_cases_next_2w"),
        "horizon":           "14 days (2 weeks ahead)",
        "validation_design": validation.get("validation_design", "time_based_holdout"),
        "train_period":      validation.get("train_period", {}),
        "test_period":       validation.get("test_period", {}),
        "best_model":        best_key,
        "models":            models_out,
        "selection_explanation": (
            "GradientBoostingRegressor was selected because it achieved the lowest MAE "
            f"({round(gbr_mae, 1)}) and RMSE under chronological time-based validation — "
            f"{round((1 - gbr_mae / naive_mae) * 100, 1)}% lower MAE than the Naive baseline. "
            "The project does not claim algorithmic novelty; the model is used as a "
            "practical forecasting component in a decision-support prototype."
        ),
        "leakage_prevention": (
            "All features use shift(1) before rolling windows. Target columns are "
            "excluded from training features. Train/test split is strictly chronological."
        ),
        "notes": validation.get("notes", []),
    }


# ── Output 3: chart_data.json ─────────────────────────────────────────────────

def build_chart_data(
    forecast: dict,
    validation: dict,
    directives: dict,
    cases_df: pd.DataFrame | None,
    climate_df: pd.DataFrame | None,
    rolling: dict | None = None,
) -> dict:
    """
    Build all chart data arrays. Each key maps to a flat array of records
    that a Recharts component can consume directly.
    """
    directive_list = directives.get("directives", [])
    metrics        = rolling.get("aggregate_metrics", {}) if rolling else validation.get("metrics", {})
    scenarios      = forecast.get("preparedness_scenarios", {})

    # ── 1. Actual vs Predicted ────────────────────────────────────────────────
    avp_raw = validation.get("actual_vs_predicted", [])
    actual_vs_predicted = ([{"label": fold["origin_period"],
        "actual": fold["predictions"]["gradient_boosting"]["actual"],
        "naive": fold["predictions"]["naive"]["prediction"],
        "moving_average": fold["predictions"]["moving_average"]["prediction"],
        "gradient_boosting": fold["predictions"]["gradient_boosting"]["prediction"]} for fold in rolling["folds"]] if rolling else [
        {
            "label":            f"{row['epi_year']}-W{int(row['epi_week']):02d}",
            "actual":           int(row["actual"]),
            "naive":            int(row.get("naive_pred", 0)),
            "moving_average":   int(row.get("moving_average_pred", 0)),
            "gradient_boosting": int(row.get("ml_pred", 0)),
        }
        for row in avp_raw
    ])

    # ── 2. Model error bars ───────────────────────────────────────────────────
    model_error_bars = [
        {
            "model": MODEL_META.get(key, {}).get("model_name", key),
            "mae":   round(float(m.get("mae",  0)), 1),
            "rmse":  round(float(m.get("rmse", 0)), 1),
        }
        for key, m in metrics.items()
    ]

    # ── 3. Uncertainty scenarios ──────────────────────────────────────────────
    uncertainty_scenarios = [
        {
            "scenario":       v.get("label", k),
            "forecast_cases": int(v.get("forecast_cases", 0)),
            "growth_factor":  round(float(v.get("growth_factor", 1)), 3),
            "risk_score":     int(v.get("risk_score", 0)),
            "risk_level":     v.get("risk_level", ""),
        }
        for k, v in scenarios.items()
    ]

    # ── 4. Zone priority (deduplicated, one row per zone) ─────────────────────
    seen_zones: dict[str, dict] = {}
    for d in directive_list:
        zid = d["zone_id"]
        if zid not in seen_zones:
            seen_zones[zid] = {
                "zone_name":       d["zone_name"],
                "priority_score":  int(d["priority_score"]),
                # Use zone-total allocated cases (not facility share)
                "allocated_cases": round(
                    float(d.get("zone_allocated_cases_expected",
                                d.get("allocated_cases_expected", 0))), 1
                ),
                "risk_category":   d["priority_category"],
            }
    zone_priority = sorted(
        seen_zones.values(),
        key=lambda x: x["priority_score"],
        reverse=True,
    )

    # ── 5. Supply depletion (NS1 and IVF per facility) ────────────────────────
    supply_depletion: list[dict] = []
    seen_fac_items: set[str] = set()
    for d in directive_list:
        fid = d["facility_id"]

        # NS1
        key_ns1 = f"{fid}:NS1"
        if key_ns1 not in seen_fac_items and d.get("sdh_ns1_expected") is not None:
            seen_fac_items.add(key_ns1)
            supply_depletion.append({
                "facility_name":  d["facility_name"],
                "facility_id":    fid,
                "zone_name":      d["zone_name"],
                "item_name":      "NS1/RDT Kit",
                "sdh_best":       d.get("sdh_ns1_best"),
                "sdh_expected":   d["sdh_ns1_expected"],
                "sdh_worst":      d.get("sdh_ns1_worst"),
                "threshold_days": int(get_parameter("OPS.STOCK.THRESHOLDS", "ns1_warning_days")),
            })

        # IV Fluid
        key_ivf = f"{fid}:IVF"
        if key_ivf not in seen_fac_items and d.get("sdh_iv_fluid_expected") is not None:
            seen_fac_items.add(key_ivf)
            supply_depletion.append({
                "facility_name":  d["facility_name"],
                "facility_id":    fid,
                "zone_name":      d["zone_name"],
                "item_name":      "IV Fluid (500ml)",
                "sdh_best":       d.get("sdh_iv_fluid_best"),
                "sdh_expected":   d["sdh_iv_fluid_expected"],
                "sdh_worst":      d.get("sdh_iv_fluid_worst"),
                "threshold_days": int(get_parameter("OPS.STOCK.THRESHOLDS", "iv_fluid_warning_days")),
            })

    # Sort by expected SDH ascending (most stressed first)
    supply_depletion.sort(key=lambda x: x["sdh_expected"] or 999)

    # ── 6. Bed gap (per facility) ─────────────────────────────────────────────
    seen_fac_bed: set[str] = set()
    bed_gap: list[dict] = []
    for d in directive_list:
        fid = d["facility_id"]
        if fid in seen_fac_bed:
            continue
        seen_fac_bed.add(fid)
        bed_gap.append({
            "facility_name":     d["facility_name"],
            "facility_id":       fid,
            "zone_name":         d["zone_name"],
            "total_beds":        int(d.get("total_dengue_beds", 0)),
            "occupied_beds":     int(d.get("occupied_dengue_beds", 0)),
            "bed_gap_best":      round(float(d.get("bed_gap_best", 0)), 1),
            "bed_gap_expected":  round(float(d.get("bed_gap_expected", 0)), 1),
            "bed_gap_worst":     round(float(d.get("bed_gap_worst", 0)), 1),
        })
    # Sort by expected bed gap descending
    bed_gap.sort(key=lambda x: x["bed_gap_expected"], reverse=True)

    # ── 7. Facility pressure (projected bed load per facility) ────────────────
    seen_fac_pbl: set[str] = set()
    facility_pressure: list[dict] = []
    for d in directive_list:
        fid = d["facility_id"]
        if fid in seen_fac_pbl:
            continue
        seen_fac_pbl.add(fid)
        facility_pressure.append({
            "facility_name":                d["facility_name"],
            "facility_id":                  fid,
            "zone_name":                    d["zone_name"],
            "priority_score":               int(d.get("priority_score", 0)),
            "total_beds":                   int(d.get("total_dengue_beds", 0)),
            "projected_bed_load_expected":  round(float(d.get("projected_bed_load_expected", 0)), 1),
            "projected_bed_load_worst":     round(float(d.get("projected_bed_load_worst", 0)), 1),
            "facility_anchor_type":         d.get("facility_anchor_type", ""),
        })
    facility_pressure.sort(
        key=lambda x: x["projected_bed_load_expected"],
        reverse=True,
    )

    # ── 8. Case trend (last 26 available weeks with rainfall overlay) ─────────
    case_trend: list[dict] = []
    if cases_df is not None and len(cases_df) > 0:
        recent = cases_df.tail(26).copy()
        for _, row in recent.iterrows():
            label = f"{int(row['epi_year'])}-W{int(row['epi_week']):02d}"
            rain: float | None = None
            if climate_df is not None:
                match = climate_df[
                    (climate_df["epi_year"] == row["epi_year"]) &
                    (climate_df["epi_week"] == row["epi_week"])
                ]
                if len(match) > 0:
                    rain = round(float(match["rainfall_mm"].iloc[0]), 1)
            case_trend.append({
                "label":       label,
                "cases":       int(row["cases"]),
                "rainfall_mm": rain,
            })

    return {
        "provenance": directives.get("provenance"),
        "generated_at":        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        "formula_registry_version": directives.get("formula_registry_version"),
        "formula_registry_sha256": directives.get("formula_registry_sha256"),
        "deployment_gate": directives.get("deployment_gate"),
        "formula_validation_status": directives.get("formula_validation_status"),
        "formula_policy": directives.get("formula_policy", {}),
        "actual_vs_predicted": actual_vs_predicted,
        "model_error_bars":    model_error_bars,
        "uncertainty_scenarios": uncertainty_scenarios,
        "zone_priority":       zone_priority,
        "supply_depletion":    supply_depletion,
        "bed_gap":             bed_gap,
        "facility_pressure":   facility_pressure,
        "case_trend":          case_trend,
    }


# ── Validation ────────────────────────────────────────────────────────────────

def validate_outputs() -> list[str]:
    """
    Check that all three output files exist and are well-formed.
    Returns a list of validation error strings (empty = all good).
    """
    errors: list[str] = []

    for path in [DASHBOARD_SUMMARY_PATH, MODEL_COMPARISON_PATH, CHART_DATA_PATH]:
        if not path.exists():
            errors.append(f"Missing output: {path.name}")
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            errors.append(f"Invalid JSON in {path.name}: {e}")
            continue

        # Spot-check key presence
        if path == DASHBOARD_SUMMARY_PATH:
            for key in ("headline_metrics", "uncertainty", "model_evidence"):
                if key not in data:
                    errors.append(f"{path.name}: missing key '{key}'")
        elif path == MODEL_COMPARISON_PATH:
            if "models" not in data or not data["models"]:
                errors.append(f"{path.name}: 'models' array is empty or missing")
        elif path == CHART_DATA_PATH:
            for key in ("actual_vs_predicted", "zone_priority", "bed_gap"):
                if key not in data or not data[key]:
                    errors.append(f"{path.name}: chart array '{key}' is empty or missing")

    return errors


# ── CLI entry point ───────────────────────────────────────────────────────────

def main() -> None:
    print()
    print("=" * 66)
    print("  DengueOps AI - Phase 6: Dashboard Exporter")
    print("=" * 66)

    # ── Validate required inputs ──────────────────────────────────────────────
    print("\n  Checking required inputs...")
    missing = [p for p in REQUIRED_INPUTS if not p.exists()]
    if missing:
        print("\n  [ERROR] Missing required input files:")
        for p in missing:
            print(f"    - {p}")
        print("\n  Run the full pipeline first:")
        print("    python analytics/run_pipeline.py")
        raise SystemExit(1)
    print("    All required inputs present.")

    # ── Load inputs ───────────────────────────────────────────────────────────
    print("\n  Loading analytics outputs...")
    forecast   = load_json(FORECAST_PATH)
    validation = load_json(VALIDATION_PATH)
    directives = load_json(DIRECTIVES_PATH)
    model_card = load_json(MODEL_CARD_PATH) if MODEL_CARD_PATH.exists() else None
    legacy_explainability = load_json(EXPLAINABILITY_PATH) if EXPLAINABILITY_PATH.exists() else None
    explainability = load_json(SELECTED_EXPLAINABILITY_PATH) if SELECTED_EXPLAINABILITY_PATH.exists() else None
    rolling = load_json(ROLLING_VALIDATION_PATH) if ROLLING_VALIDATION_PATH.exists() else None
    candidate_comparison = load_json(CANDIDATE_COMPARISON_PATH) if CANDIDATE_COMPARISON_PATH.exists() else None
    assert_same_provenance(
        artifact_provenance(forecast, "forecast_output.json"),
        artifact_provenance(validation, "validation_metrics.json"),
        artifact_provenance(directives, "directives.json"),
        labels=("forecast_output.json", "validation_metrics.json", "directives.json"),
    )
    profiled_run = bool(forecast.get("provenance", {}).get("deployment_profile_id"))
    if not profiled_run:
        model_card = None
    if profiled_run:
        if model_card is None:
            raise ValueError("Profiled run is missing model_card.json.")
        assert_same_provenance(
            artifact_provenance(forecast, "forecast_output.json"),
            artifact_provenance(model_card, "model_card.json"),
            labels=("forecast_output.json", "model_card.json"),
        )
        if explainability is None:
            raise ValueError("Profiled run is missing model_explainability.json.")
        if rolling is None:
            raise ValueError("Profiled run is missing rolling_validation.json.")
        rolling_bytes = ROLLING_VALIDATION_PATH.read_bytes()
        features_for_rolling = load_csv_safe(FEATURES_PATH)
        validate_rolling_validation(rolling, expected_df=features_for_rolling,
            expected_provenance=artifact_provenance(forecast, "forecast_output.json"), expected_model_card=model_card,
            expected_artifact_sha256=hashlib.sha256(rolling_bytes).hexdigest())
        if model_card.get("model_selection_status") == "comparison_complete_and_adopted":
            if candidate_comparison is None: raise ValueError("Model card requires missing candidate comparison artifact.")
            comparison_bytes = CANDIDATE_COMPARISON_PATH.read_bytes()
            validate_comparison_artifact(candidate_comparison,
                expected_registry_sha256=hashlib.sha256(CANDIDATE_REGISTRY_PATH.read_bytes()).hexdigest(),
                expected_rolling_sha256=hashlib.sha256(rolling_bytes).hexdigest(), expected_rolling=rolling, expected_model_card=model_card,
                expected_artifact_sha256=hashlib.sha256(comparison_bytes).hexdigest())
        elif candidate_comparison is not None:
            raise ValueError("Stale candidate comparison must not be exported for a not-run current pipeline.")
    if explainability is not None:
        if model_card is None:
            raise ValueError("Explainability artifact exists without a model card.")
        features_df = load_csv_safe(FEATURES_PATH)
        if features_df is None:
            raise ValueError("Explainability validation requires model_features.csv.")
        cutoff = int(len(features_df) * 0.80)
        explainability_bytes = SELECTED_EXPLAINABILITY_PATH.read_bytes()
        validate_selected_model_explainability(
            explainability,
            expected_provenance=artifact_provenance(forecast, "forecast_output.json"),
            expected_feature_names=validation["features_used"],
            expected_validation_df=features_df.iloc[cutoff:].copy(),
            expected_comparison_sha256=model_card["comparison_artifact_sha256"],
            expected_registry_sha256=model_card["candidate_registry_sha256"],
        )
        if hashlib.sha256(explainability_bytes).hexdigest() != model_card["selected_model_explainability_artifact_sha256"]:
            raise ValueError("Selected-model explainability bytes differ from the model-card commit record.")
        if hashlib.sha256(FORECAST_PATH.read_bytes()).hexdigest() != model_card["forecast_artifact_sha256"]:
            raise ValueError("Forecast bytes differ from the model-card commit record.")
        if legacy_explainability is None:
            raise ValueError("Historical P0.4 GBR explainability evidence is missing.")
        validate_model_explainability(
            legacy_explainability,
            expected_provenance=artifact_provenance(forecast, "forecast_output.json"),
            expected_feature_names=validation["features_used"], expected_validation_df=features_df.iloc[cutoff:].copy(),
            expected_target=validation["target"],
        )
    cases_df   = load_csv_safe(CASES_PATH)
    climate_df = load_csv_safe(CLIMATE_PATH)

    n_directives = len(directives.get("directives", []))
    n_avp        = len(validation.get("actual_vs_predicted", []))
    n_cases      = len(cases_df) if cases_df is not None else 0
    print(f"    Directives: {n_directives}  |  AVP rows: {n_avp}  |  Case rows: {n_cases}")

    # ── Build outputs ─────────────────────────────────────────────────────────
    print("\n  Building dashboard outputs...")

    dashboard_summary = build_dashboard_summary(forecast, validation, directives, model_card, explainability, rolling, candidate_comparison)
    save_json(DASHBOARD_SUMMARY_PATH, dashboard_summary)
    print(f"    [OK] dashboard_summary.json")

    model_comparison = build_model_comparison(validation, rolling)
    save_json(MODEL_COMPARISON_PATH, model_comparison)
    print(f"    [OK] model_comparison.json")

    chart_data = build_chart_data(forecast, validation, directives, cases_df, climate_df, rolling)
    save_json(CHART_DATA_PATH, chart_data)
    print(
        f"    [OK] chart_data.json  "
        f"(avp={len(chart_data['actual_vs_predicted'])}  "
        f"zones={len(chart_data['zone_priority'])}  "
        f"sdh={len(chart_data['supply_depletion'])}  "
        f"beds={len(chart_data['bed_gap'])}  "
        f"trend={len(chart_data['case_trend'])})"
    )

    # ── Validate outputs ──────────────────────────────────────────────────────
    print("\n  Validating outputs...")
    errors = validate_outputs()
    if errors:
        print("\n  [WARNING] Validation issues found:")
        for e in errors:
            print(f"    - {e}")
    else:
        print("    All output files valid.")

    # ── Summary ───────────────────────────────────────────────────────────────
    hm = dashboard_summary["headline_metrics"]
    sc = forecast.get("preparedness_scenarios", {})

    print()
    print(f"  {'-'*62}")
    print(f"  Dashboard Export Complete")
    print(f"    Forecast    : {hm['forecast_cases']} cases | {hm['risk_level']} (score {hm['risk_score']})")
    print(f"    Planning L/B/H: {sc.get('best_case',{}).get('forecast_cases','?')} / "
          f"{sc.get('expected_case',{}).get('forecast_cases','?')} / "
          f"{sc.get('worst_case',{}).get('forecast_cases','?')} (planning sensitivity)")
    print(f"    Active model: RandomForestRegressor | rolling RMSE {dashboard_summary['model_evidence']['active_model_rmse']}")
    print(f"    Priority zone : {hm['highest_priority_zone']}")
    print(f"    Pressure facility: {hm['highest_pressure_facility'][:50]}")
    print(f"  {'-'*62}")
    print()
    print(f"  Dashboard files ready:")
    print(f"    - {DASHBOARD_SUMMARY_PATH}")
    print(f"    - {MODEL_COMPARISON_PATH}")
    print(f"    - {CHART_DATA_PATH}")
    print()
    print("=" * 66)
    print("  Export complete.")
    print("=" * 66)
    print()


if __name__ == "__main__":
    main()
