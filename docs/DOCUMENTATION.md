# DengueOps AI — Complete Technical Documentation

**Project:** DengueOps AI — Simulation-Based Dengue Surge Preparedness Decision Support for Dhaka South
**Conference:** IEEE ICADHI 2025 — Track 06: Health Data Analytics & Predictive Systems
**Institution:** Department of Software Engineering, Daffodil International University

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [System Architecture](#2-system-architecture)
3. [Analytics Pipeline](#3-analytics-pipeline)
4. [Feature Engineering](#4-feature-engineering)
5. [Forecasting Model](#5-forecasting-model)
6. [Model Validation](#6-model-validation)
7. [Uncertainty Scenarios](#7-uncertainty-scenarios)
8. [Spatial Allocation](#8-spatial-allocation)
9. [Supply Depletion Horizon (SDH)](#9-supply-depletion-horizon-sdh)
10. [LOS-Based Bed Pressure](#10-los-based-bed-pressure)
11. [Zone Priority Scoring](#11-zone-priority-scoring)
12. [Operational Directives](#12-operational-directives)
13. [Surge Simulation Layer](#13-surge-simulation-layer)
14. [Dashboard — Page by Page](#14-dashboard--page-by-page)
15. [Data Files Reference](#15-data-files-reference)
16. [Component Architecture](#16-component-architecture)
17. [Ethics and Data Boundaries](#17-ethics-and-data-boundaries)
18. [Assumptions and Limitations](#18-assumptions-and-limitations)
19. [Future Roadmap](#19-future-roadmap)
20. [Authors](#20-authors)

---

## 1. Project Overview

### What DengueOps AI Is

DengueOps AI is a simulation-based public health decision-support prototype. It takes dengue case trends and climate data, runs a lag-aware machine learning forecast, and translates the output into operational preparedness intelligence for five Dhaka South operational zones and eleven tracked facilities.

### Core Positioning

> DengueOps AI does not claim a novel forecasting algorithm. Its contribution is the operational decision-support layer that converts lag-aware outbreak forecasts into uncertainty-aware preparedness metrics and public health action priorities.

### What It Produces

| Output | Method | Used For |
|--------|--------|---------|
| 14-day dengue forecast | GradientBoostingRegressor | Baseline for all downstream metrics |
| Growth factor | Forecast / 4-week rolling avg | Risk level classification |
| Risk score (0–100) | Piecewise linear scale | Zone and city-level alert |
| Uncertainty band | RMSE-derived best/expected/worst | Planning range |
| SDH — NS1/RDT | Stock / dynamic demand | Supply alert threshold |
| SDH — IV fluids | Stock / dynamic demand | Supply alert threshold |
| Projected bed load | LOS-based accumulation | Bed pressure signal |
| Bed gap | Projected load − available beds | Facility alert |
| Zone priority score | Forecast risk × vulnerability weight | Zone ranking |
| Simulated planning suggestions | Rule-based prototype triggers | Not operational recommendations |

### What It Is Not

- Not a novel AI forecasting algorithm
- Not a clinical decision-support or diagnostic tool
- Not connected to real-time surveillance
- Not an autonomous decision-making system
- Not validated with official Dhaka South epidemiological data

---

## 2. System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     ANALYTICS PIPELINE (Python)              │
│                                                              │
│  generate_demo_data.py                                       │
│       ↓                                                      │
│  feature_engineering.py  →  model_features.csv              │
│       ↓                                                      │
│  forecast_model.py       →  forecast_output.json            │
│       ↓                                                      │
│  uncertainty_engine.py   →  (added to forecast_output.json) │
│       ↓                                                      │
│  validation_backtest.py  →  validation_metrics.json         │
│       ↓                                                      │
│  operational_engine.py   →  directives.json                 │
│       ↓                                                      │
│  dashboard_exporter.py   →  dashboard_summary.json          │
│                              model_comparison.json           │
│                              chart_data.json                 │
│                              pipeline_run_summary.json       │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    NEXT.JS DASHBOARD (Frontend)              │
│                                                              │
│  /dashboard         →  Main operational dashboard            │
│  /methodology       →  Technical documentation              │
│  /validation        →  Model evidence and backtest charts    │
│  /ethics            →  Responsible use statement            │
│  /assumptions       →  Transparent limitations              │
│  /about             →  Project overview and authors          │
│  /                  →  Landing page                          │
└─────────────────────────────────────────────────────────────┘
```

### Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Frontend framework | Next.js 16, App Router | Routing, SSR/SSG, layout |
| Language | TypeScript | Type safety across all components |
| Styling | Tailwind CSS | Utility-first responsive design |
| Charts | Recharts | All data visualisations |
| Icons | Lucide React | UI icons |
| Analytics | Python 3.10+ | Data generation, feature engineering, ML |
| ML library | Scikit-learn | GradientBoostingRegressor |
| Data processing | Pandas, NumPy | Feature engineering, aggregation |
| Data transport | Static JSON files | Pipeline output → dashboard |

---

## 3. Analytics Pipeline

All analytics are orchestrated by `analytics/run_pipeline.py`.

### Pipeline Steps

| Step | Script | Output |
|------|--------|--------|
| 0. **Fetch real dengue data** | `fetch_opendengue.py` | `dengue_cases.csv` — **real OpenDengue Bangladesh data** |
| 1. Generate demo data | `generate_demo_data.py` | `climate_data.csv`, `zones.json`, `facilities.json`, `inventory.json` (dengue_cases.csv skipped if Step 0 ran) |
| 2. Feature engineering | `feature_engineering.py` | `model_features.csv` |
| 3. Forecast model | `forecast_model.py` | `forecast_output.json` |
| 4. Uncertainty engine | `uncertainty_engine.py` | Updates `forecast_output.json` with scenarios |
| 5. Validation backtest | `validation_backtest.py` | `validation_metrics.json` |
| 6. Operational engine | `operational_engine.py` | `directives.json` |
| 7. Dashboard exporter | `dashboard_exporter.py` | `dashboard_summary.json`, `model_comparison.json`, `chart_data.json`, `pipeline_run_summary.json` |

### Running the Pipeline

```bash
# Full run — all 7 steps
python analytics/run_pipeline.py

# Skip data generation (preserve edited input files)
python analytics/run_pipeline.py --skip-data-generation

# Validate all outputs without re-running
python analytics/run_pipeline.py --validate-only

# Re-export dashboard JSON from existing pipeline outputs
python analytics/run_pipeline.py --export-dashboard-only
```

---

## 4. Feature Engineering

**Script:** `analytics/feature_engineering.py`
**Output:** `data/model_features.csv` (~121 rows × 29 columns)

### Why Candidate Lag Features?

The current 2- and 4-week lookbacks are provisional model candidates. The
following historical Phase 0 timing sketch is not evidence for a Dhaka-specific
coefficient and must not be interpreted as validation:

```
Mosquito breeding event (rainfall)
  → 7–14 days → Larval development
  → 7–14 days → Infectious adult mosquito
  → 4–7 days  → Human infection
  → 3–7 days  → Symptom onset and hospital presentation
```

The implemented lags require local temporal backtesting; no causal or optimal
Dhaka lag is currently claimed.

### Feature Groups

**Group 1 — Lagged Climate Features (14d and 28d lags)**
- `rainfall_lag14`, `rainfall_lag28`
- `temperature_lag14`, `temperature_lag28`
- `humidity_lag14`, `humidity_lag28`

**Group 2 — Case Trend Features**
- `cases_lag1`, `cases_lag2`, `cases_lag4` (1, 2, 4-week lags)
- `cases_rolling_4w_mean`, `cases_rolling_4w_std`
- `cases_rolling_8w_mean`
- `cases_yoy_change` (year-over-year)
- `growth_momentum` (rolling trend slope)

**Group 3 — Seasonality Features**
- `epi_week_sin`, `epi_week_cos` (cyclical encoding)
- `month_sin`, `month_cos`
- `is_monsoon` (binary flag)
- `is_peak_season` (binary flag)

**Target variable:** `target_cases_next_2w` — dengue cases in the following 2 epidemiological weeks (14 days).

**Leakage prevention:** Features are constructed using only data available at prediction time. No future case counts enter any feature.

---

## 5. Forecasting Model

**Script:** `analytics/forecast_model.py`
**Output:** `data/forecast_output.json`

### Model

`GradientBoostingRegressor` (scikit-learn) with the following parameters:
- `n_estimators`: 200
- `max_depth`: 4
- `learning_rate`: 0.05
- `min_samples_leaf`: 5

### Output Fields

| Field | Description |
|-------|-------------|
| `forecast_cases` | Point forecast — dengue cases next 14 days |
| `growth_factor` | `forecast_cases / reference_cases_4w_rolling` |
| `risk_score` | 0–100 piecewise linear score from growth factor |
| `risk_level` | Low / Moderate / High / Critical |
| `uncertainty_scenarios` | Best, expected, worst case objects |
| `uncertainty_method` | RMSE source, uncertainty %, prototype note |

### Risk Level Classification

| Growth Factor | Experimental Growth Score | Provisional Forecast-Growth Category |
|--------------|-----------------|------------|
| ≤ 1.0 | 0–20 | Low |
| 1.0–1.5 | 20–50 | Moderate |
| 1.5–2.0 | 50–75 | High |
| > 2.0 | 75–100 | Critical |

---

## 6. Model Validation

**Script:** `analytics/validation_backtest.py`
**Output:** `data/validation_metrics.json`

### Validation Design

- **Method:** Chronological train/test split — NOT random
- **Train:** First 80% of weeks (chronological order)
- **Test:** Final 20% of weeks
- **Reason:** Random splitting leaks future seasonal and outbreak information into training, artificially inflating model performance

### Models Compared

| Model | Role | MAE | RMSE | MAPE (%) |
|-------|------|-----|------|---------|
| Naive Baseline | Last-week repeat | 148.96 | 351.47 | 214.31 |
| Moving Average (4-week) | Trend smoothing | 223.66 | 422.50 | 337.38 |
| **Gradient Boosting** | **Selected ML model** | **46.96** | **67.80** | **40.52** |

### Why GBR Was Selected

GradientBoostingRegressor achieved the lowest MAE and RMSE under chronological validation. The project does not claim algorithmic novelty — the model is used as a practical forecasting component within the decision-support prototype.

### Actual vs Predicted

The `chart_data.json > actual_vs_predicted` array contains 25 test-period weeks showing actual cases alongside predictions from all three models. Displayed as a multi-line chart on the `/validation` page.

---

## 7. Uncertainty Scenarios

**Script:** `analytics/uncertainty_engine.py`
**Output:** Added to `forecast_output.json > uncertainty_scenarios`

### Formula

```
Lower sensitivity scenario = max(0, Forecast − holdout RMSE)
Expected Case = Forecast
Upper sensitivity scenario = Forecast + holdout RMSE
```

Where `RMSE = 67.8 cases` (from chronological validation).

### Current Output (Example)

| Scenario | Forecast Cases | Growth Factor | Risk Level |
|----------|---------------|---------------|------------|
| Lower sensitivity scenario | 166 | 1.063 | Low forecast growth |
| Expected Case | 234 | 1.498 | Moderate |
| Upper sensitivity scenario | 302 | 1.933 | High forecast growth |

### Important Note

This is **not** a calibrated probabilistic interval. It is a transparent prototype uncertainty band derived from validation RMSE, designed to support range-based preparedness planning.

---

## 8. Spatial Allocation

**Script:** `analytics/operational_engine.py`

City-level forecast cases are allocated to zones using an **Exposure Index heuristic**.

### Formula

```
Exposure Index =
  Population Share   × 0.40
+ Density Weight     × 0.30
+ Facility Pressure  × 0.20
+ Mobility Corridor  × 0.10
```

### Zone Allocation

```
Zone Allocated Cases = Total Forecast Cases × (Zone Exposure Index / Sum of All Exposure Indices)
```

### Five Operational Zones

| Zone | Zone ID | Profile |
|------|---------|---------|
| Kamrangirchar | Z01 | High-density informal settlement |
| Mitford / Old Dhaka | Z02 | Dense urban, referral pressure |
| Dhanmondi | Z03 | Mixed residential |
| Jatrabari / Sayedabad | Z04 | Mobility corridor |
| Lalbagh / Hazaribagh | Z05 | Dense mixed-use |

> This is a heuristic, not a learned spatial epidemiological model. It is used because ward-level dengue surveillance data may not be available in the prototype context.

---

## 9. Supply Depletion Horizon (SDH)

**Script:** `analytics/operational_engine.py`

SDH estimates how many days before a facility exhausts a supply item at current demand pace.

### Formula

```
Dynamic Daily Demand = Baseline Daily Consumption × Growth Factor (scenario-adjusted)

SDH = Current Stock / Dynamic Daily Demand
```

### Items Tracked

- NS1 / RDT test kits
- IV fluids (dengue treatment)

### Alert Thresholds

| SDH | Status |
|-----|--------|
| > item warning threshold | Above prototype warning threshold |
| ≤ 7 days NS1 or ≤ 5 days IV fluid | Prototype warning; not approved |
| ≤ 3 days | Prototype critical trigger; not approved |
| < 4 days | Critical |

### What SDH Applies To

SDH applies to consumable supplies (NS1 kits, IV fluids) — items that are used up. It does **not** apply to beds, which are cumulative capacity resources modelled separately with LOS.

---

## 10. LOS-Based Bed Pressure

**Script:** `analytics/operational_engine.py`

Bed pressure is modelled using an **average Length of Stay (LOS)** approximation, treating dengue bed occupancy as an accumulation problem.

### Formula

```
Projected Bed Load = Current Dengue Beds Occupied + (Daily Surge Cases × Avg LOS)

Bed Gap = Projected Bed Load − Available Dengue Beds
```

Where:
- **Avg LOS** = 5 days (simplified prototype assumption)
- **Daily Surge Cases** = Zone Allocated Cases / 14

### Important Notes

- Dengue bed capacity (`dengue_bed_capacity_demo`) is a **synthetic demonstration value**
- General bed capacity is a **public reference anchor** where available
- A positive Bed Gap = expected deficit (facility needs to activate contingency beds)
- LOS is simplified — real deployment requires actual admission/discharge data

---

## 11. Zone Priority Scoring

**Script:** `analytics/operational_engine.py`

### Formula

```
Experimental Planning-Priority Score = exposure × vulnerability × 200 + exposure × 80 + experimental growth score × (0.60 + vulnerability × 0.30), capped at 100
```

Capped at 100.

### Priority Categories

| Score | Category |
|-------|---------|
| 76–100 | Critical |
| 51–75 | High |
| 26–50 | Moderate |
| 0–25 | Routine |

### Vulnerability Weight

Each zone carries a `vulnerability_weight` from `zones.json`. Zones with higher density, informality, or facility pressure are weighted more.

**Design note:** The vulnerability weight is *gated* — it amplifies risk score but does not create priority from zero. A zone with low forecast risk will not dominate response priorities simply because of its vulnerability profile.

---

## 12. Operational Directives

**Script:** `analytics/operational_engine.py`
**Output:** `data/directives.json`

### Directive Generation Rules

Directives are generated per facility and then aggregated to zone level. Rules fire based on threshold conditions:

| Trigger | Directive Level |
|---------|----------------|
| Planning score > 75 or positive bed deficit | Prototype trigger condition only |
| Item SDH at governed warning threshold | Prototype trigger condition only |
| Planning score 26–50 | Simulated planning tier only |
| Below all thresholds | MONITOR |

### Directive Fields

Each directive contains:
- `zone_id`, `zone_name`, `facility_id`, `facility_name`
- `priority_category`, `priority_score`
- `zone_allocated_cases_expected`
- `bed_gap_expected`, `projected_bed_load_expected`
- `sdh_ns1_expected`, `sdh_ivf_expected`
- `directive_level`, `recommended_action`
- `key_recommendation`
- `facility_anchor_type`, `general_bed_capacity`
- `dengue_bed_capacity_demo`, `occupied_dengue_beds_demo`

### Eleven Facilities Tracked

| Zone | Facilities |
|------|-----------|
| Kamrangirchar (Z01) | Kamrangirchar 31-Bed Hospital + 2 synthetic units |
| Mitford / Old Dhaka (Z02) | Sir Salimullah Medical College + 2 synthetic units |
| Dhanmondi (Z03) | Popular Medical Centre + 2 synthetic units |
| Jatrabari / Sayedabad (Z04) | Jatrabari 250-Bed General Hospital + 1 synthetic unit |
| Lalbagh / Hazaribagh (Z05) | Lalbagh 31-Bed Hospital + 1 synthetic unit |

Facility anchor names are based on public/government references where available. All dengue-specific values are synthetic.

---

## 13. Surge Simulation Layer

**Library:** `lib/surgeScenarios.ts`

The surge simulation is a **client-side deterministic overlay**. It does not retrain the model or modify JSON files. It multiplies base zone priority scores and allocated cases by scenario-specific modifiers.

### Five Scenarios

| Scenario | Key | Affected Zones | Modifiers |
|----------|-----|----------------|-----------|
| Normal Monitoring | `normal` | None | 1.0 all |
| Old Dhaka Surge | `old_dhaka_surge` | Mitford, Lalbagh | ×1.25, ×1.10 |
| Kamrangirchar Surge | `kamrangirchar_surge` | Kamrangirchar | ×1.30 |
| Jatrabari Mobility Surge | `jatrabari_surge` | Jatrabari, Lalbagh | ×1.25, ×1.10 |
| City-Wide Critical Surge | `city_wide_critical` | All zones | ×1.25–1.40 |

### Zone Priority Heatmap

A CSS-grid schematic visualises the five zones in approximate Dhaka South layout. Zones are heat-coloured by adjusted priority score. Surge-affected zones are highlighted with a percentage badge. This is a schematic prototype preview using operational zones — it does not represent official ward boundaries or a validated geospatial map.

---

## 14. Dashboard — Page by Page

### `/` — Landing Page

Ten sections introducing the project:
Hero → Problem → Solution Workflow → Core Modules → Comparison → Data & Ethics → Evaluation Fit → User Roles → Live Preview → Final CTA → Authors

### `/dashboard` — Main Dashboard

| Section | Description |
|---------|-------------|
| Top Header | Branding, conference, pipeline info |
| Banners | Data mode, ethics, assumption notices |
| Forecast Scenario Selector | Best / Expected / Worst — drives metric cards |
| 8 Metric Cards | Cases, growth factor, risk level, supply alerts, zone, facility |
| Forecast Uncertainty | 3 scenario cards + uncertainty band chart |
| Surge Simulation | 5-scenario selector, explanation card, zone priority heatmap, before/after chart, zone impact table |
| Operational Workflow | Pipeline step summary |
| Role Separation | Explains tab separation |
| Role Tabs | Operational / Facility / Public Advisory / Technical |
| Operational Tab | Zone priority ranking + directive table |
| Facility Tab | 11-facility readiness table + SDH chart + bed gap chart |
| Public Advisory Tab | Plain-language risk summary |
| Technical Tab | Model evidence + explicit feature-importance-unavailable state + pipeline status |
| Footer | Advisory ethics notice |

### `/methodology` — Methodology Page

Fifteen sections documenting the complete analytics pipeline with formulas, diagrams, and assumptions. Includes a jump-navigation bar.

### `/validation` — Validation Page

Twelve sections covering:
- Validation design (chronological vs random split)
- Model comparison summary cards (3 models)
- Full comparison table with interpretation
- Actual vs predicted multi-line chart (25-week holdout)
- Dual error bar charts (MAE + RMSE)
- Uncertainty linkage explanation
- Limitations (7 explicit)
- Proves / Does Not Prove two-column
- Evaluator note

### `/ethics` — Ethics Page

Seven sections covering:
- Six ethical design principles
- Data ethics and boundary table (10 rows)
- Safety boundaries (7 "does not" statements)
- Responsible output design (technical → operational → decision translation)
- Five user role responsibility cards
- Future deployment governance requirements (9 items)
- Ethics summary

### `/assumptions` — Assumptions Page

Ten sections covering:
- Core assumptions table (7 rows: assumption / why / limitation / future)
- Real vs synthetic data boundary table (10 rows)
- Spatial exposure heuristic formula
- Operational workflow assumption
- Modelling limitations (6 items)
- Decision-support scope
- Misuse risk and mitigation table (6 rows)
- Future validation roadmap (8 steps)
- Final summary

### `/about` — About Page

Project overview, role design explanation, operational workflow, "what it is not" list, usefulness points, scalability roadmap, and author cards.

---

## 15. Data Files Reference

All generated data files are in `data/`. They are produced by the Python pipeline and consumed by the Next.js dashboard.

| File | Producer | Consumer | Contents |
|------|----------|----------|---------|
| `dengue_cases.csv` | Selected case producer | `feature_engineering.py` | Source is run-specific (`synthetic_demo`, `synthetic_benchmark`, or selected adapter) and recorded in the input manifest. |
| `climate_data.csv` | `generate_demo_data.py` | `feature_engineering.py` | Weekly rainfall, temperature, humidity |
| `zones.json` | `generate_demo_data.py` | `operational_engine.py` | Zone profiles, weights, exposure indices |
| `facilities.json` | `generate_demo_data.py` | `operational_engine.py` | 11 facility records |
| `inventory.json` | `generate_demo_data.py` | `operational_engine.py` | Starting stock per facility |
| `model_features.csv` | `feature_engineering.py` | `forecast_model.py`, `validation_backtest.py` | 29 engineered features, 121 rows |
| `forecast_output.json` | `forecast_model.py` + `uncertainty_engine.py` | Dashboard, `operational_engine.py` | Forecast, scenarios, uncertainty method |
| `validation_metrics.json` | `validation_backtest.py` | Dashboard, validation page | MAE/RMSE/MAPE, actual vs predicted array |
| `directives.json` | `operational_engine.py` | Dashboard, facility table | 11 facility directives with all metrics |
| `dashboard_summary.json` | `dashboard_exporter.py` | Dashboard, landing page | Headline metrics, operational summary |
| `model_comparison.json` | `dashboard_exporter.py` | Dashboard, validation page | 3-model comparison table |
| `chart_data.json` | `dashboard_exporter.py` | Dashboard charts | AVP, error bars, SDH, bed gap, zone priority |
| `pipeline_run_summary.json` | `dashboard_exporter.py` | Technical tab | Step timings, generated files, status |

---

## 16. Component Architecture

### Dashboard Components (`components/dashboard/`)

| Component | Purpose |
|-----------|---------|
| `ScenarioSelector.tsx` | Best/Expected/Worst forecast scenario toggle |
| `SurgeScenarioSelector.tsx` | 5-scenario surge simulation selector |
| `GisHeatmapPreview.tsx` | CSS-grid schematic zone heatmap |
| `ScenarioExplanationCard.tsx` | Surge scenario description and implication |
| `ScenarioImpactPanel.tsx` | Before/after zone impact table |
| `UncertaintySummary.tsx` | Three scenario summary cards |
| `ZoneRiskTable.tsx` | 5-zone priority ranking table |
| `FacilityReadinessTable.tsx` | 11-facility readiness and bed pressure table |
| `DirectiveTable.tsx` | Operational directive listing |
| `ModelEvaluationPanel.tsx` | Model comparison and AVP chart |
| `PipelineStatusPanel.tsx` | Pipeline run step timings |
| `OperationalCommandView.tsx` | Operational tab content |
| `FacilityReadinessView.tsx` | Facility tab content |
| `TechnicalValidationView.tsx` | Technical tab content |
| `DataModeBanner.tsx` | Synthetic data mode notice |
| `EthicsBanner.tsx` | Ethics and advisory notice |
| `AssumptionBanner.tsx` | Assumption disclosure banner |

### Chart Components (`components/charts/`)

| Component | Chart Type | Data Source |
|-----------|-----------|-------------|
| `ActualVsPredictedChart.tsx` | Line + area | `validation_metrics.json` |
| `UncertaintyBandChart.tsx` | Bar | `forecast_output.json` |
| `SupplyDepletionChart.tsx` | Bar | `directives.json` |
| `BedGapChart.tsx` | Bar | `directives.json` |
| `ZonePriorityChart.tsx` | Bar | `chart_data.json` |
| `FeatureImportanceChart.tsx` | Horizontal bar | `chart_data.json` |
| `ForecastTrendChart.tsx` | Line | `chart_data.json` |
| `ScenarioImpactChart.tsx` | Grouped bar | `lib/surgeScenarios.ts` |

### Validation Components (`components/validation/`)

| Component | Contents |
|-----------|---------|
| `ValidationHero.tsx` | Header, badges, evaluator note |
| `ValidationDesignSection.tsx` | Chronological split explanation + flow |
| `ModelSummaryCards.tsx` | 3 model metric cards |
| `ModelComparisonTable.tsx` | Full comparison table + why baselines |
| `ActualVsPredictedPanel.tsx` | Multi-line AVP chart (4 lines) |
| `ErrorComparisonPanel.tsx` | Dual MAE/RMSE bar charts |
| `UncertaintyLinkageSection.tsx` | RMSE → band formula + live scenarios |
| `ValidationLimitations.tsx` | Limitations + Proves/Doesn't + Evaluator note |

### Shared Lib (`lib/`)

| File | Purpose |
|------|---------|
| `types.ts` | All TypeScript interfaces |
| `constants.ts` | BRAND colours, project constants, scenario labels |
| `formatters.ts` | Date, number, epi week formatters |
| `demo-data.ts` | Typed imports of all JSON data files |
| `surgeScenarios.ts` | Surge scenario types, modifiers, `applySurge()` |

---

## 17. Ethics and Data Boundaries

### Six Ethical Design Commitments

1. **No patient-level data** — The system never collects, processes, or stores identifiable patient records
2. **Privacy-safe demonstration** — All facility readiness values are synthetic
3. **Human-in-the-loop** — Outputs are advisory; all decisions require qualified human review
4. **No clinical diagnosis** — The system does not diagnose dengue or recommend individual treatment
5. **Transparent uncertainty** — Forecast uncertainty is always shown, never hidden
6. **Bias safeguards** — Vulnerability weights are gated to prevent static factors from permanently dominating priorities

### Data Boundary Classification

| Data Element | Status |
|-------------|--------|
| Facility names | Public anchor (real names where available) |
| General bed capacity | Public reference anchor where available |
| Dengue-specific beds | Synthetic demonstration |
| Current dengue occupancy | Synthetic demonstration |
| NS1/RDT stock | Synthetic demonstration |
| IV fluid stock | Synthetic demonstration |
| Dengue case counts | Run-specific; benchmark mode is wholly synthetic and identified as `synthetic_benchmark` |
| Climate values | Synthetic/demo aggregate |
| Patient records | Not used — not stored |

---

## 18. Assumptions and Limitations

### Core Assumptions

| Assumption | Why Used | Known Limitation |
|-----------|---------|-----------------|
| Real dengue national data (OpenDengue V1.3) | Provides citable training signal | National-level only — not Dhaka South sub-district |
| Synthetic facility readiness | Real values not publicly available | Cannot validate actual shortages |
| Public hospital anchors | Geographic realism | Names only — values are synthetic |
| Spatial exposure heuristic | No ward-level data available | Not a learned spatial model |
| RMSE-based uncertainty | Simple, transparent planning range | Not calibrated probabilistic |
| Average LOS = 5 days | Dengue hospitalisation approximation | Simplified — not validated |
| Vulnerability weights | Prototype assumptions | Not calibrated with expert input |

### Modelling Limitations

- GBR selected empirically from prototype validation — not a universal dengue model claim
- ~120 weekly observations — limited sample for stable generalisation
- Cannot prove causal effects of climate on dengue transmission
- Feature importance is interpretability, not causality
- Real deployment requires external validation on official data

---

## 19. Future Roadmap

### Near-Term (Production Path)

1. Replace synthetic data with official DGDA/IEDCR aggregated surveillance
2. Validate climate lag assumptions against historical Dhaka outbreak timelines
3. Calibrate uncertainty intervals using quantile regression or Bayesian methods
4. Validate facility readiness logic with authorised hospital data
5. Implement secure scheduled ingestion pipeline
6. Add role-based access control and audit logs

### Research Extensions

1. Ward-level spatial epidemiological model using mobility and vector data
2. Calibrated probabilistic forecasting (quantile GBR or Bayesian)
3. Causal climate-dengue analysis
4. Multi-city deployment framework
5. Bangla language interface for local health workers
6. Integration with EWARN or DHIS2 reporting systems

---

## 20. Data Sources and Citations

### Real Dengue Data

**OpenDengue V1.3** — Bangladesh national dengue surveillance data (2014–2024)

> Clarke J, Lim A, Gupte P, Pigott DM, van Panhuis WG, Brady OJ.
> *A global dataset of publicly available dengue case count data.*
> Scientific Data. 2024 Mar 14;11(1):296.
> https://doi.org/10.1038/s41597-024-03120-7

> Clarke J, Lim A, Gupte P, Pigott DM, van Panhuis WG, Brady OJ.
> OpenDengue: data from the OpenDengue database. Version 1.3. figshare; 2025.
> https://doi.org/10.6084/m9.figshare.24259573
> License: CC-BY 4.0

Monthly national dengue case totals for Bangladesh (2014–2024) are downloaded automatically via `analytics/fetch_opendengue.py` and converted to approximate weekly observations using an ISO week-based proportional distribution algorithm.

### Synthetic / Demonstration Data

All other data layers (climate, zone exposure indices, facility inventory, bed occupancy, vulnerability weights) are synthetic demonstration values generated by `analytics/generate_demo_data.py`. They do not represent real operational records.

### Public Reference Anchors

Facility names and general bed capacity figures reference publicly available information about named public hospitals in Dhaka. Dengue-specific operational values (dengue bed allocation, stock levels, daily consumption) are synthetic.

---

## 21. Authors

**Meherab Hossain Shafin**
Department of Software Engineering
Daffodil International University

**Jannatul Tazri Aohona**
Department of Software Engineering
Daffodil International University

---

*DengueOps AI — Prototype only. Not for clinical or official public health deployment without validated data and institutional oversight.*
*IEEE ICADHI 2025 · Daffodil International University*
