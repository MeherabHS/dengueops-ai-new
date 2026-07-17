# DengueOps AI — Analytics Pipeline

`validation_backtest.py` publishes both `validation_metrics.json` (legacy single holdout) and atomic, schema-validated `rolling_validation.json` (primary evidence). For origin row `i`, rows `0:i-1` train the model, row `i-1` is embargoed, and row `i` is evaluated. Per-fold permutation importance is unavailable; native tree importance is aggregated across the 68 independently fitted estimators.

`model_candidates.py` reuses the P1.1 GBR and baseline predictions after exact fold/hash checks, evaluates seasonal naive, fold-scaled Ridge and Poisson, and single-process Random Forest, then publishes the P1.2A comparison evidence. P1.2B independently validates that current-run evidence and constructs the frozen Random Forest through `model_factory.py`; no fallback is permitted.

## Overview

This directory contains the Python analytics pipeline for DengueOps AI.
Each phase progressively implements the full decision-support pipeline.

## Directory Structure

```
analytics/
├── generate_demo_data.py   # Phase 1 — Synthetic dataset generation (11 facilities, 5 zones)
├── feature_engineering.py  # Phase 2 — Lag-aware, leakage-free feature matrix
├── validation_backtest.py  # Phase 3a — Temporal backtest, MAE/RMSE/MAPE
├── forecast_model.py       # Phase 3b — governed RF adoption bundle + forecast
├── uncertainty_engine.py   # P1.3 — prior-only synthetic empirical forecast range
├── operational_engine.py   # Phase 5 — SDH, bed load, zone/facility directives
├── dashboard_exporter.py   # Phase 6 — Dashboard-ready JSON exporter
├── run_pipeline.py         # Phase 6 — One-command full pipeline runner
└── README.md               # This file
```

---

## Running the Pipeline

### Full pipeline (recommended)

```bash
python analytics/run_pipeline.py
```

Runs all 7 steps in order, validates outputs after each step, and saves a run log.

### Skip data generation (preserve edited inputs)

```bash
python analytics/run_pipeline.py --skip-data-generation
```

Skips `generate_demo_data.py`. Use when you have manually edited `data/dengue_cases.csv`,
`data/climate_data.csv`, `data/zones.json`, `data/facilities.json`, or `data/inventory.json`
and do not want to overwrite them.

### Validate output files only

```bash
python analytics/run_pipeline.py --validate-only
```

Checks all required output files for existence and structural validity.
Does not run any pipeline steps.

### Re-export dashboard JSON only

```bash
python analytics/run_pipeline.py --export-dashboard-only
```

Runs only `dashboard_exporter.py` using existing analytics outputs.
Use when forecast/validation/directives files are already up to date.

---

## Expected Outputs

| File | Produced by | Content |
|------|-------------|---------|
| `data/dengue_cases.csv` | generate_demo_data | 128 weekly rows, 2024–2026 W24 |
| `data/climate_data.csv` | generate_demo_data | 128 weekly climate rows |
| `data/zones.json` | generate_demo_data | 5 operational zones with exposure indices |
| `data/facilities.json` | generate_demo_data | 11 facilities, 5 public anchors |
| `data/inventory.json` | generate_demo_data | 22 NS1/IVF items |
| `data/model_features.csv` | feature_engineering | 121 rows × 29 cols |
| `data/validation_metrics.json` | validation_backtest | MAE/RMSE/MAPE, AVP chart data |
| `data/forecast_output.json` | forecast_model + uncertainty_engine | Forecast + 3 uncertainty scenarios |
| `data/directives.json` | operational_engine | 11 facility directives |
| `data/dashboard_summary.json` | dashboard_exporter | Headline metrics + model evidence |

## P1.4B uploaded-data validation

`runtime_validate.py` is a validation-only entry point for a persistent Ubuntu VPS. It requires explicit absolute paths for the two original CSVs, two canonical outputs, the workspace root, and `metadata/validation.json`. `runtime_context.py` rejects paths that escape the workspace or enter the source-controlled `data/` bundle.

The validator removes a UTF-8 BOM when present, requires the current exact canonical headers (no aliases are approved in P1.4B), writes deterministic canonical CSVs, validates schema/time/geography/alignment rules, and emits content-bound dataset identity and separate Quick Forecast/Assess Dataset eligibility. User-data invalidity is represented in structured JSON with a zero process exit; nonzero exit is reserved for runtime/system failure. It does not import or invoke `run_pipeline.py`, fit an estimator, or generate any forecast, uncertainty, or preparedness artifact.

## P1.4C-2 isolated Quick Forecast worker

The long-lived worker is started with `python analytics/runtime_worker.py` using the configured virtual-environment interpreter and `DENGUEOPS_RUNTIME_ROOT`. It atomically claims JSON jobs, permits one active analytics process globally, enforces a ten-minute timeout, and commits only runtime-specific point-forecast, null-bound uncertainty, model-card, chart, and compact dashboard artifacts. It does not call `run_pipeline.py`, candidate comparison, temporal uncertainty calibration, or the operational engine.

Uploaded output availability is explicit: the empirical range remains pending until dataset-specific temporal calibration exists, and preparedness remains unavailable until a runtime planning-scenario policy is approved. Bundled benchmark uncertainty and planning scenarios are never copied into uploaded runs.
| `data/model_comparison.json` | dashboard_exporter | Model table + selection rationale |
| `data/chart_data.json` | dashboard_exporter | All chart arrays for Next.js dashboard |
| `data/pipeline_run_summary.json` | run_pipeline | Structured run log |

---

## Visual Evidence Philosophy

> **The Python pipeline is not the evaluator-facing product. It is the analytics engine.**
> All relevant outputs are exported into dashboard-ready JSON files and visualised in the
> Next.js dashboard. Evaluators do not need to inspect terminal outputs or raw intermediate
> files — the dashboard presents forecasts, validation metrics, uncertainty bands, supply
> depletion timelines, bed gaps, and zone/facility directives in a structured visual form.

---

## Setup

```bash
pip install -r requirements.txt
```

---

## Phase 1 — Synthetic Data Generation

```bash
python analytics/generate_demo_data.py
```

Generates all input data files in `data/`:
- `dengue_cases.csv`    — weekly dengue surveillance, 2024–2026
- `climate_data.csv`   — weekly rainfall, temperature, humidity
- `zones.json`         — five Dhaka South operational zones
- `facilities.json`    — one health facility per zone
- `inventory.json`     — NS1/RDT kit and IV fluid stock per facility

---

## Phase 2 — Lag-Aware Feature Engineering

```bash
python analytics/feature_engineering.py
```

Builds `data/model_features.csv` — a leakage-free feature matrix ready for
model training and backtesting.

### Why 2-week and 4-week climate lags?

Dengue transmission does not respond to rainfall and humidity instantaneously.
The causal chain from rainfall to reported dengue cases has multiple biological
steps, each adding delay:

| Step | Duration |
|------|----------|
| Rainfall creates standing water (breeding habitat) | 0–3 days |
| Aedes aegypti egg hatching | 2–3 days |
| Larval development (4 instars) | 5–7 days |
| Pupal stage | 2–3 days |
| Adult emergence and feeding | 3–5 days |
| Extrinsic incubation in mosquito | 7–14 days |
| Human incubation period | 4–10 days |
| Reporting and confirmation delay | 5–7 days |
| **Total: lag to reported cases** | **~14–28 days** |

The 2-week lag (14 days) captures early-stage effects and transmission acceleration.
The 4-week lag (28 days) captures the full development-to-reporting pathway.
Both are retained because the dominant lag may shift by season and year.

### Why time-based leakage prevention matters

In supervised machine learning on time series data, **data leakage** occurs when
information from the future (or the present target period) is inadvertently used
as a model input. Leakage causes inflated training performance that collapses in
real deployment.

This pipeline prevents leakage in three ways:

1. **Sorted order guarantee**: The DataFrame is sorted by `(epi_year, epi_week)`
   before any `shift()` or `rolling()` operation. An unsorted DataFrame would
   produce silently incorrect lag values.

2. **Rolling means use `shift(1)` first**: At row `t`, the rolling mean is
   computed over `cases[t-N, ..., t-1]` — never over `cases[t]` itself.
   Without this shift, the 3-week rolling mean at week `t` would include the
   current week's cases, making it partially equivalent to the target variable.

3. **Target columns are output-only**: `target_cases_next_1w` and
   `target_cases_next_2w` are explicitly excluded from `FEATURE_COLUMNS`.
   The separation between inputs and labels is enforced in code, not just
   documented.

### What `model_features.csv` contains

| Column group | Columns | Count |
|-------------|---------|-------|
| Base (context) | epi_year, epi_week, date_start, city, cases, deaths, rainfall_mm, avg_temp_c, humidity_pct | 9 |
| Lagged climate | rainfall_lag_2w/4w, temp_lag_2w/4w, humidity_lag_2w/4w | 6 |
| Case lags | cases_lag_1w/2w/4w | 3 |
| Rolling means | cases_rolling_3w/4w/8w | 3 |
| Growth rates | growth_rate_1w, growth_rate_2w | 2 |
| Seasonality | epi_week_sin/cos, monsoon_flag, post_monsoon_flag | 4 |
| **Total features** | | **18** |
| Targets (labels only) | target_cases_next_1w, target_cases_next_2w | 2 |
| **Grand total columns** | | **29** |

**Row count:** 121 usable rows from 128 raw rows.
7 rows dropped: 5 for lag burn-in at the series start (8-week rolling window
requires 5 prior observations with `min_periods=5`), and 2 for missing
1-week and 2-week-ahead targets at the series end (no future observations exist).

### Target columns — training labels only

`target_cases_next_1w` and `target_cases_next_2w` are the supervised learning
**labels**. They represent what the model is trying to predict.

They must **never** be used as model inputs. In the training step (Phase 3):

```python
X = df[FEATURE_COLUMNS]             # model inputs
y1 = df["target_cases_next_1w"]     # label for 1-week forecast
y2 = df["target_cases_next_2w"]     # label for 2-week forecast
```

---

## Phase 3 — Forecasting, Backtesting, and Baseline Comparison

```bash
# Run temporal backtest → data/validation_metrics.json
python analytics/validation_backtest.py

# Train final model → data/forecast_output.json
python analytics/forecast_model.py
```

### Time-based validation

All model evaluation uses a **strict chronological holdout split** with no random
shuffling at any step.

| Split | Rows | Period |
|-------|------|--------|
| Train | 96 (80%) | 2024 W6 → 2025 W49 |
| Test  | 25 (20%) | 2025 W50 → 2026 W22 |

Why random splits are wrong for time series:
If training data includes weeks from 2026 and the test set contains 2025 weeks,
the model trains on the future and tests on the past. This produces artificially
inflated metrics that collapse immediately in real deployment. A chronological
split mimics actual operational conditions where forecasts are always made into
genuinely unseen future periods.

### Baselines used

| Baseline | Method | Purpose |
|----------|--------|---------|
| Naive | `cases_lag_1w` (last known week) | Tests if any model beats "no change" assumption |
| Moving average | `cases_rolling_4w` (4-week mean) | Tests if model beats smoothed recent trend |
| GradientBoostingRegressor | Full 18-feature lag matrix | ML model — must outperform both baselines |

### Results (test period: 2025 W50 → 2026 W22)

| Model | MAE | RMSE | MAPE (%) |
|-------|-----|------|---------|
| Naive | 149.0 | 351.5 | 214.3 |
| Moving Average | 223.7 | 422.5 | 337.4 |
| **GBR (best)** | **47.0** | **67.8** | **40.5** |

The GBR reduces MAE by **68%** versus naive and **79%** versus moving average.
High naive MAPE reflects the 2025 post-peak decline period where the naïve
"last week continues" assumption is particularly error-prone.

### Why baseline comparison matters

A model with good absolute metrics but that cannot beat a naïve baseline provides
no useful operational signal. Baseline comparison is the minimum credibility gate
for any decision-support system. It demonstrates that the lag-engineered features
carry genuine predictive information beyond simple trend continuation.

### Metrics generated

- **MAE** — Mean Absolute Error (cases): interpretable operational error in case count units
- **RMSE** — Root Mean Squared Error: penalises large errors more heavily than MAE
- **MAPE** — Mean Absolute Percentage Error: scale-independent, but sensitive to low case weeks

### Forecast output (latest run)

From the most recent available feature row (2026 W22):

| Field | Value |
|-------|-------|
| Target week | 2026 W24 |
| Forecast cases | 234 |
| Growth factor | 1.498× (vs 4-week rolling mean of 156) |
| Forecast growth category | Moderate forecast growth |
| Experimental growth score | 60 / 100 (provisional; not a probability or validated risk score) |

### Limitations of synthetic/demo data

The backtest results reflect the behaviour of the pipeline on synthetic demo data,
not validated epidemiological accuracy.

Key limitations:
- Training data was generated from a parameterised seasonal model with fixed noise seed (42)
- The GBR may overfit the synthetic noise patterns that it was "trained" on
- Real DGHS surveillance data would show different noise characteristics, reporting delays, and outbreak dynamics
- MAPE values would differ substantially on real data with genuine reporting gaps
- These results validate that the **pipeline is correctly implemented** (features, lag engineering, temporal split), not that the model is operationally deployable

---

## Phase 4 — Forecast Uncertainty Layer

```bash
# Apply uncertainty scenarios to forecast_output.json
python analytics/uncertainty_engine.py
```

### Why single-point forecasts are insufficient

A single point forecast ("expect 234 cases in week 24") is operationally dangerous
as the sole input to resource allocation decisions:

- **Under-allocation risk:** If the true case count is significantly higher than the
  forecast (within the model's RMSE range), a facility that planned only for the
  expected scenario may exhaust IV fluid stock or exceed bed capacity mid-surge.
- **Over-allocation risk:** Planning only for the worst case wastes scarce resources
  and creates alert fatigue in health system staff.
- **Decision anchoring:** A single number discourages planners from considering how
  their preparedness level changes across the plausible outcome space.

By converting the point forecast into a three-scenario band, DengueOps AI allows
operations staff to ask: *"Are we prepared for the worst case? Does our readiness
change between moderate and high forecast-growth categories?"* This is the core operational value
of the uncertainty layer.

### How P1.3 empirical forecast uncertainty is estimated

The active range uses the 68 validated Random Forest rolling-origin absolute residuals. Folds 1–20 form the warm-up; for folds 21–68, each interval uses only predecessor residuals. The governed order statistic is `min(n, ceil((n + 1) * 0.90))`, without interpolation. Historical empirical coverage is not a probability guarantee, and `is_prediction_interval` remains false.

```
score = abs(actual - raw_prediction)
q = kth ascending prior score
lower = max(0, raw_prediction - q)
upper = raw_prediction + q
```

Where RMSE is the Root Mean Squared Error of the best validation model on the
chronological 20% holdout test period (Phase 3 backtest):

| Model | RMSE | Selected |
|-------|------|---------|
| Naive | 351.5 | |
| Moving Average | 422.5 | |
| **GradientBoosting** | **67.8** | yes |

The current band width is **±67.8 cases (±29% of the 234-case forecast)**:

| Scenario | Cases | Growth Factor | Forecast Growth Category | Experimental Growth Score |
|----------|-------|--------------|------------|------------|
| Best Case | 166 | 1.063× | Low | 34 |
| Expected Case | 234 | 1.498× | Moderate | 60 |
| Worst Case | 302 | 1.933× | High | 82 |

The expected_case scenario exactly matches the original `forecast_output.json`
values, preserving consistency with Phase 3.

### Limitations of this uncertainty method

This is synthetic, post-selection temporal evidence, not a probability statement or real-world Dhaka calibration. Targets overlap, residuals are dependent, and high-incidence performance may be weaker. The legacy RF RMSE 87/120/153 triplet is retained separately as `preparedness_scenarios`; it does not define active forecast uncertainty.

1. **Not a calibrated interval:** A proper 68% prediction interval would contain the
   true value approximately 68% of the time. The RMSE band has unknown coverage
   probability — residuals from gradient boosting are not Gaussian.

2. **Symmetric assumption is wrong:** Outbreak case counts have a right-skewed error
   distribution. In practice, the worst-case bound likely underestimates surge peaks
   while the best-case bound is reasonably reliable. A log-transform or
   asymmetric envelope would be more realistic.

3. **Residual autocorrelation ignored:** Weekly epidemiological residuals are
   serially correlated. If the model under-predicts week 1 of a surge, it likely
   under-predicts week 2 as well. The RMSE band does not account for this.

4. **Synthetic data artefact:** The RMSE of 67.8 reflects prediction error on
   synthetic demo data. Real DGHS/IEDCR surveillance data would have different
   noise characteristics, reporting delays, and outbreak dynamics.

### How uncertainty will propagate to SDH and bed pressure (Phase 5+)

In later phases, each of the three scenarios will be independently propagated
through the operational engine:

```
uncertainty_scenario.forecast_cases
         │
         ▼
  SDH pressure estimate   ← LOS + occupancy rate
         │
         ▼
  Bed gap calculation      ← (forecast demand) - (available capacity)
         │
         ▼
  Supply depletion timeline ← (stock ÷ daily consumption) per scenario
         │
         ▼
  Zone priority ranking    ← exposure_index × growth_factor per scenario
         │
         ▼
  Directive generation     ← worst-case triggers pre-emptive reorder/transfer
```

This means the dashboard will display three parallel preparedness pathways:
planners can see whether their current stock is sufficient even under the
worst-case scenario, and can prioritise pre-emptive resupply accordingly.

---

## Phase 5 — Operational Decision-Support Engine

```bash
# Generate zone-level directives from forecast + uncertainty + spatial data
python analytics/operational_engine.py
```

Outputs `data/directives.json` — the core artifact the dashboard consumes for
all operational panels (zone priority table, bed gap chart, SDH depletion chart,
directive table, alert cards).

### Why single-point forecasts are insufficient for operations

A forecast saying "234 cases expected in week 24" does not answer the operational
questions health planners actually face:

- *Which zone gets the most surge? How many IV fluid kits do we need there?*
- *Will Kamrangirchar run out of NS1 kits before we can reorder?*
- *How many extra dengue beds does Jatrabari General Hospital need?*
- *Under worst-case, does any facility breach capacity?*

The operational engine converts one city-level forecast into zone-resolved,
facility-specific, scenario-aware decision signals.

### Spatial exposure allocation

City-level forecast cases are distributed to zones using a normalized spatial
exposure index. The method is transparent and heuristic — appropriate for
prototype use under sub-city data constraints.

**Exposure index components:**

| Component | Weight | Rationale |
|-----------|--------|-----------|
| population_share | 40% | More people = more absolute cases |
| density_weight | 30% | Denser areas transmit dengue faster |
| facility_pressure_weight | 20% | Existing pressure limits surge capacity |
| mobility_corridor_weight | 10% | Transport hubs seed inter-zone spread |

**Anomaly adjustment:** `adjusted_exposure = exposure_index + current_anomaly_adjustment`

The anomaly term is additive and represents current-week deviations such as
standing water from rainfall or local outbreak reports. After additive adjustment,
all values are normalized to sum to 1.

**Current run allocations (expected: 234 cases):**

| Zone | Norm. Exposure | Allocated Cases |
|------|---------------|-----------------|
| Kamrangirchar | 21.8% | 50.9 |
| Mitford / Old Dhaka | 21.0% | 49.1 |
| Jatrabari / Sayedabad | 19.9% | 46.6 |
| Lalbagh / Hazaribagh | 19.3% | 45.2 |
| Dhanmondi | 18.0% | 42.2 |

### Consumables vs. beds: why they are modelled differently

**Consumables (NS1/RDT kits, IV fluids):**
Demand scales directly with the number of patients processed.
`dynamic_daily_demand = baseline_daily_consumption × growth_factor`
`SDH = current_stock / dynamic_daily_demand`
A 1.5× growth factor = 50% more kits used per day = stock runs out faster.

**Beds (cumulative resource):**
Beds are not consumed per patient — they are held concurrently for the
duration of each patient's stay (`avg_length_of_stay` days).
`projected_bed_load = occupied_dengue_beds + (allocated_cases/14) × LOS`
`bed_gap = max(0, projected_bed_load − total_dengue_beds)`
Modelling beds as SDH would overstate depletion risk; the correct measure
is concurrent occupancy versus physical capacity.

### Vulnerability-gated priority scores

`priority_score = experimental_growth_score × (1 + vulnerability_weight)`

Zones with higher structural vulnerability (informal settlements, limited
facility access) receive elevated priority scores even at the same forecast
forecast-growth category. This gates urgency by Social Determinants of Health (SDH) principles
— equitable response means pre-empting cascade failure in the most fragile zones.

**Priority scores (expected scenario, experimental_growth_score = 60):**

| Zone | Vulnerability | Raw Score | Capped | Category |
|------|--------------|-----------|--------|----------|
| Kamrangirchar | 0.33 | 79.8 | 80 | **Critical** |
| Mitford / Old Dhaka | 0.22 | 73.2 | 73 | High |
| Jatrabari / Sayedabad | 0.20 | 72.0 | 72 | High |
| Lalbagh / Hazaribagh | 0.20 | 72.0 | 72 | High |
| Dhanmondi | 0.13 | 67.8 | 68 | High |

### Current run results (2026 W24 forecast)

| Zone | Priority | Exp. Bed Gap | NS1 SDH (exp) |
|------|----------|-------------|--------------|
| Kamrangirchar | Critical (80) | 12.4 beds | 7.4 days |
| Mitford / Old Dhaka | High (73) | 3.5 beds | 9.4 days |
| Dhanmondi | High (68) | 4.6 beds | 8.3 days |
| Jatrabari / Sayedabad | High (72) | 6.0 beds | 7.6 days |
| Lalbagh / Hazaribagh | High (72) | 8.5 beds | 7.7 days |

All five facilities show expected bed gaps — consistent with facilities already
near capacity (Kamrangirchar: 16/20 beds, Mitford: 51/65) before the surge.

**Simulated planning suggestions generated per zone (not institution-approved):**
- All zones: *Activate additional dengue beds or referral protocol.*
- Kamrangirchar: *Prioritize vector-control response in this zone.* (Critical priority)
- All zones: *Prepare contingency plan under worst-case forecast.* (RL=High across all)

### Limitations

1. **Spatial allocation is heuristic:** No ward-level surveillance data is used.
   The exposure index approximates spatial risk under data constraints.

2. **Steady-state surge assumed:** Bed load and SDH calculations assume a uniform
   daily surge rate over the 14-day horizon. Real surges are non-linear.

3. **Synthetic data:** All facility bed counts, LOS, and inventory levels are
   generated demo data. Real operational thresholds would differ.

4. **Single facility per zone:** Production would require multi-facility zone
   aggregation and facility-level referral network modelling.

5. **SDH uses growth factor, not zone-specific allocation rate:** In this prototype,
   all zones use the city-level growth factor for SDH. Future versions should
   compute zone-specific demand based on allocated case counts.

---

## Important Notes

### P0.3C governance inputs

Profiled runs validate `config/deployments/<deployment_id>/profile.json`, `config/formulas.json`, and the versioned evidence registry before any producer runs. The current evidence array is empty; no scientific evidence or institutional approvals are claimed. The `dhaka_south` profile selects all three deterministic `synthetic_benchmark` sources, remains `benchmark_only`, and produces a run-specific model card.

Profile `data_mode` records deployment maturity (`synthetic_capability_demonstration` here). Manifest-derived `observed_data_mode` separately records source reality (`synthetic`, `real`, or `mixed`). The profile is not locally calibrated or institution-approved. `TD-P03A-LEGACY-RISK-FIELDS` is preserved without runtime changes.

### P0.4 run-specific explainability

The validation stage generates native tree and holdout permutation diagnostics from its already-fitted `GradientBoostingRegressor`; it does not retrain or serialize an explainability model. Permutation diagnostics use the unseen final chronological 20% with MAE-based scoring, 20 repeats, and seed 42. The generated artifact carries the same run, manifest, formula-registry, deployment-profile, evidence-registry, and model-card identities as the other run artifacts.

The artifact explicitly explains `chronological_holdout_validation_model`. The final forecast is produced by a distinct estimator fitted on all labeled rows. Feature rankings are non-causal and have not been evaluated across temporal folds, seasons, or real data.

- No patient-level data is used at any stage.
- All input data is aggregated synthetic demo data (Phase 0–2).
- Phase 3 will add the forecast model, backtest, and operational engine.
- Validate all assumptions against local ground truth before operational use.
### Runtime assessment executor

`runtime_assessment.py` is the isolated P1.4D-2 execution entry point. It revalidates the workspace, dataset, policy, registry, and canonical hashes; constructs the governed 68-fold plan once; fits fresh learned estimators per fold (including Gradient Boosting); preserves failed-candidate records; and emits rolling, comparison, recommendation, and compact summary evidence only. `runtime_assessment_commit.py` validates reconciliation and atomically commits the bundle without touching deployment `latest.json`.

The file-backed worker dispatches `dataset_assessment` jobs with a default 1,800-second timeout configured by `DENGUEOPS_ASSESSMENT_TIMEOUT_SECONDS`. Quick Forecast jobs retain their existing branch and behavior.

### Trusted internal approved forecast

`runtime_approved_forecast.py` handles only `approved_forecast` jobs created from a committed, hash-bound decision and a reserved one-run authorization. It resolves the applicable archived Phase 1 or active Phase 2 decision policy from immutable assessment evidence, verifies the decision, authorization, assessment, candidate registry, selected parameter hash, fold plan, and 18-feature contract, then fits the selected governed learned estimator once. Phase 1 retains its exact 173-row/68-fold path; Phase 2 trains on every validated labelled row (157 or more) and records the independently rebuilt row count, full training period, selected evaluation period, and committed planned-fold count separately. It never reruns candidate comparison, uncertainty calibration, or the operational engine.

`runtime_approved_forecast_commit.py` validates the decision-bound bundle, rejects planning, facility, alert, directive, comparison, or non-null uncertainty artifacts, atomically commits the run, and only then replaces the deployment latest pointer. Authorization consumption is recorded after that commit; if the event write is interrupted, consumption is derived from the committed run. Failed execution is not automatically retried or released.
