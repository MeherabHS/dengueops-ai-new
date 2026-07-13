# DengueOps AI

Primary model evidence uses deterministic expanding-window rolling-origin validation: 104 initial eligible training rows, a mandatory one-row label-availability embargo, a two-week horizon, and a one-week step across 68 synthetic benchmark folds. The legacy chronological 80/20 holdout remains available for P0.4 permutation diagnostics, regression comparison, and the current RMSE sensitivity-band input. Rolling results do not establish real-world Dhaka performance.

P1.2A compares seven fixed candidates on those exact folds with `--run-model-comparison`. P1.2B independently recomputes the winner and adopts the frozen Random Forest as the active synthetic demonstration model. P1.3 derives one prior-only expanding absolute-residual empirical range from the 68 RF rolling folds: 20 warm-up folds and 48 historical evaluation folds. The range is synthetic temporal evidence, not a prediction interval or probability guarantee. The legacy RF holdout-RMSE triplet remains only as separate preparedness planning compatibility. P0.4 and P1.1 GBR artifacts remain historical evidence only.

### Simulation-Based Dengue Surge Preparedness Decision Support for Dhaka South

> **IEEE ICADHI 2025 — Track 06: Health Data Analytics & Predictive Systems**

---

## The Problem

Dengue response in Dhaka South has historically been reactive. By the time a hospital runs out of NS1 test kits or a ward fills its dengue beds, the surge has already arrived. There is no operational layer that converts outbreak forecasts into preparedness signals — no tool telling a health officer *where* the next pressure will emerge, *how long* supplies will last, or *which zone* needs vector-control teams first.

**DengueOps AI is built for that gap.**

---

## What It Does

DengueOps AI is a **simulation-based public health decision-support prototype**. It ingests dengue case trends and climate signals, runs a lag-aware machine learning forecast, and translates the output into a set of operational preparedness metrics:

| Output | What it answers |
|--------|----------------|
| **Uncertainty Scenarios** | How many cases should we plan for — best, expected, worst? |
| **Supply Depletion Horizon (SDH)** | How many days before NS1 kits or IV fluids run out? |
| **LOS-Based Bed Pressure** | How many dengue beds will be occupied? Where is the gap? |
| **Zone Priority Score** | Which of the five operational zones needs attention most urgently? |
| **Operational Directives** | What action should each zone and facility take right now? |
| **Surge Simulation** | What would happen if a specific area surged by 25–40%? |

Everything is surfaced through an interactive dashboard — not a spreadsheet, not a terminal. A dashboard that a public health analyst, hospital administrator, or city health officer can actually read and act on.

---

## Why It Is Different

Most dengue dashboards stop at case counts and trend lines. DengueOps AI goes further:

- **Forecast → preparedness translation.** The ML forecast is not the product. The operational directives derived from it are.
- **Uncertainty is shown, not hidden.** Every forecast is presented as three scenarios (best/expected/worst) built from validation RMSE.
- **Role-based outputs.** A hospital administrator sees bed gaps and SDH. A public health analyst sees zone priorities. A technical evaluator sees MAE, RMSE, and feature importance. The same data, presented appropriately.
- **Scenario simulation.** Five surge scenarios let planners rehearse response before a crisis, not during one.
- **Transparent by design.** Every assumption, limitation, and ethical boundary is documented and displayed in the app itself.

---

## Live Routes

| Route | Purpose |
|-------|---------|
| `/` | Landing page — problem, solution, workflow, roles |
| `/dashboard` | Main operational dashboard |
| `/methodology` | Full technical documentation — formulas, pipeline, logic |
| `/validation` | Model evidence — backtesting, MAE/RMSE/MAPE, AVP charts |
| `/ethics` | Ethical design principles and data boundaries |
| `/assumptions` | All assumptions, limitations, and future validation roadmap |
| `/about` | Project overview and authors |

---

## Quick Start

**Requirements:** Node.js 18+, Python 3.10+

```bash
# 1. Install dependencies
npm install
pip install -r requirements.txt

# 2. Run the analytics pipeline
#    Default: uses controlled synthetic Dhaka South demo data (2024–2026)
python analytics/run_pipeline.py

# 3. Start the dashboard
npm run dev
```

**Optional real-data pathways (experimental — not the active demo mode)**

```bash
# Replace synthetic dengue_cases.csv with real OpenDengue Bangladesh national data
python analytics/run_pipeline.py --use-opendengue

# Replace synthetic climate_data.csv with NASA POWER data
python analytics/run_pipeline.py --use-nasa-power-climate

# Use both real data sources
python analytics/run_pipeline.py --use-opendengue --use-nasa-power-climate
```

Open [http://localhost:3000](http://localhost:3000)

> The Python pipeline generates JSON outputs in `data/`. The Next.js dashboard reads those files. The terminal output is not the product — the dashboard is.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 16, App Router |
| Language | TypeScript |
| Styling | Tailwind CSS |
| Charts | Recharts |
| Icons | Lucide React |
| Analytics | Python — Pandas, NumPy, Scikit-learn |
| Data | Static JSON (pipeline output) |

---

## Key Formulas at a Glance

```
Growth Factor         = Forecast Cases / 4-Week Rolling Average

Experimental Growth Score = Provisional piecewise scale (0–100) from growth factor; not risk or probability

SDH                   = Current Stock / Dynamic Daily Demand

Projected Bed Load    = Current Dengue Beds Occupied + (Daily Surge Cases × Avg LOS)

Bed Gap               = Projected Bed Load − Available Dengue Beds

Exposure Index        = Population × 0.40 + Density × 0.30 + Facility Pressure × 0.20 + Mobility × 0.10

Experimental Planning-Priority Score (0–100) = structural + forecast_driven
                        structural     = exposure × vulnerability × 200 + exposure × 80
                        forecast_driven = risk_score × (0.60 + vulnerability × 0.30)
                        Categories: 0–25 Routine, 26–50 Moderate, 51–75 High, 76–100 Critical

Sensitivity Band      = Lower: max(0, Forecast − holdout RMSE)
                        Point: Forecast
                        Upper: Forecast + holdout RMSE
                        Uncalibrated; not a probabilistic prediction interval
```

---

## Data Transparency

The default demonstration uses controlled synthetic data. The separate `synthetic_benchmark` source provides deterministic, wholly synthetic benchmark facilities and linked inputs. Exact sources and formula-governance metadata are recorded in each generated artifact.

| Data Layer | Source | Status |
|-----------|--------|--------|
| Dengue case data | **Synthetic/demo** — `generate_demo_data.py` | Controlled weekly Dhaka South pattern, 2024–2026. Seasonal surge + early 2026 warning. |
| Climate data | **Synthetic/demo** — `generate_demo_data.py` | Weekly rainfall, temperature, humidity. Aligned to 2024–2026 dengue period for lagged features. |
| Facility names | Public anchor | Real public hospital names as credible location anchors |
| Bed capacity (general) | Public reference | General published figures only |
| Dengue beds, stock, occupancy | Synthetic demonstration | Not real operational data |
| Patient-level records | Not used, not stored | — |

**Optional real-data integration (experimental — not active by default):**

| Optional Source | Flag | Coverage |
|----------------|------|----------|
| OpenDengue V1.3 (Clarke et al. 2024, *Sci Data*) | `--use-opendengue` | Bangladesh national, 2014–2024 |
| NASA POWER (meteorological API) | `--use-nasa-power-climate` | Dhaka South, configurable date range |

---

## Authors

**Meherab Hossain Shafin**
Department of Software Engineering, Daffodil International University

**Jannatul Tazri Aohona**
Department of Software Engineering, Daffodil International University

---

## Important Disclaimers

- This is a **prototype** — not a validated clinical or operational system. Growth categories, planning-priority scores, SDH thresholds, and planning suggestions are provisional and not institution-approved.
- All outputs are **advisory** — human review is required before any action
- The system does **not diagnose dengue** or recommend individual treatment
- Real deployment requires official data, institutional approval, and validation

---

## Documentation

Full technical documentation is in [`docs/DOCUMENTATION.md`](docs/DOCUMENTATION.md)

| Doc | Contents |
|-----|---------|
| `docs/DOCUMENTATION.md` | Complete technical, architectural, and user documentation |
| `docs/GUIDELINE.md` | Story-based user guide for non-technical readers |
| `docs/ASSUMPTIONS_AND_LIMITATIONS.md` | Detailed assumption disclosures |
| `data/README.md` | Data directory and schema reference |

## Deployment Governance (P0.3C)

The `dhaka_south` deployment profile is a `benchmark_only` synthetic capability demonstration. It binds the exact formula-registry and empty evidence-registry hashes to each run and generates `data/model_card.json`. `observed_data_mode` describes whether run inputs are synthetic, real, or mixed; it does not imply deployment maturity, local calibration, evidence, or approval.

### P1.4B runtime validation boundary

P1.4B adds validation-only CSV intake for a persistent Ubuntu VPS running long-lived Node.js and Python processes. The Node route stores uploads under the absolute `DENGUEOPS_RUNTIME_ROOT` (default repository-local `runtime/`) and invokes the configured `DENGUEOPS_PYTHON_EXECUTABLE` with explicit workspace paths. Each CSV is limited to 10 MiB by default; an Nginx deployment should enforce a matching or smaller `client_max_body_size` before requests reach Next.js.

Uploaded case and climate files are normalized and validated inside an isolated `runtime/workspaces/<workspace_id>/` directory. They are never written into the governed benchmark `data/` directory. P1.4B does not forecast, compare models, calibrate uncertainty, generate preparedness outputs, commit a run, or replace the dashboard. The bundled synthetic benchmark therefore remains the current Overview. In particular, the synthetic P1.3 empirical range and the 87/120/153 planning scenarios are not reused for uploads.

### P1.4C-2 isolated Quick Forecast runtime

An upload that passes the active `RUNTIME.QUICK_FORECAST.COMPATIBILITY` policy may queue a point-only Quick Forecast. A separate long-lived Python worker claims file-backed jobs, rebuilds the exact 18-feature contract, fits only the approved frozen Random Forest configuration, and publishes a runtime-specific artifact bundle under `DENGUEOPS_RUNTIME_ROOT`. It never invokes candidate comparison, uncertainty calibration, or the operational engine.

Runtime runs are committed by atomic staging-directory rename. The deployment-scoped `runtime/deployments/dhaka_south/latest.json` pointer is replaced only after all runtime schemas and cross-artifact identities pass; until the first valid runtime commit, the dashboard API returns the bundled benchmark. Uploaded runs explicitly carry `pending_dataset_specific_calibration` with null bounds and `unavailable_missing_planning_policy` with no scenarios, facilities, alerts, or directives.

Production requires two long-lived Ubuntu services: `next start` for the web process and `python analytics/runtime_worker.py` from the configured virtual environment for the worker. Run both as a dedicated unprivileged user with `/var/lib/dengueops-ai` owned by that user, configuration supplied through a protected environment file, restart-on-failure under systemd, and Nginx request/rate limits. This phase is trusted/internal only; public exposure requires authentication and authorization.

### P1.4D-3/P1.4E trusted internal one-run decisions

Committed dataset assessments may now support a separate, immutable internal model-use decision and a separate one-run forecast authorization. Enable this only with `DENGUEOPS_INTERNAL_DECISION_ENABLED=true`, a protected `DENGUEOPS_INTERNAL_DECISION_SECRET` of at least 16 characters, and a server-configured `DENGUEOPS_INTERNAL_OPERATOR_ID`. Optional controls include `DENGUEOPS_DECISION_VALIDITY_SECONDS`, `DENGUEOPS_DECISION_REASON_MAX_LENGTH`, and `DENGUEOPS_APPROVED_FORECAST_TIMEOUT_SECONDS`.

Nginx must restrict the decision and approved-forecast POST routes to an internal IP allowlist, require HTTPS, rate-limit requests, and inject or validate the protected `x-dengueops-internal-decision-secret` header without exposing the secret to browser JavaScript. This is not a replacement for authentication: the recorded operator type is `trusted_internal_unverified`, and institutional approval is always false.

An approved decision authorizes at most one point-forecast run. It does not mutate the source-controlled deployment profile or adopt a deployment-wide model. Approved forecasts use immutable assessment inputs, do not rerun comparison, retain null uncertainty bounds as `pending_selected_model_calibration`, and keep preparedness unavailable because no runtime planning-scenario policy exists.

Technically functioning, scenario-tested, formula-governed research prototype. The profile is not locally calibrated, epidemiologically validated, hospital-approved, or authorized for operational decision-making. Simulated preparedness notifications are workflow artifacts and are not sent to real recipients.

`TD-P03A-LEGACY-RISK-FIELDS` remains open: `risk_level`, `risk_score`, and `recommendations` are deprecated compatibility fields, while the canonical fields remain `forecast_growth_category`, `experimental_growth_score`, `planning_priority_tier`, and `planning_suggestions`.

## Run-Specific Model Diagnostics (P0.4)

Each profiled benchmark run generates `data/model_explainability.json` from the fitted chronological-holdout validation model while that exact estimator remains in memory. Holdout permutation importance (`neg_mean_absolute_error`, 20 repeats, seed 42) is the primary ranking signal; native tree importance is secondary. Negative permutation values are preserved.

These diagnostics describe the validation-model instance, not the separately fitted all-data forecast-model instance. They are model diagnostics only: they do not establish causality, biological mechanism, clinical importance, seasonal stability, or transferability to real surveillance data.

---

*For research and educational demonstration purposes only.
Not for clinical or operational deployment without validated data and institutional oversight.*
### P1.4D-2 runtime dataset assessment

Validated `assess_dataset` workspaces that satisfy the active 173-labelled-row policy can be queued for an isolated, file-backed temporal assessment. The worker precommits one 68-fold expanding-window plan and evaluates the seven governed candidates on those identical folds. Evidence is committed immutably under `runtime/assessments/<assessment_id>` and is available through the compact assessment API.

The result is technical evidence only: recommendation strength is unavailable, approval controls are disabled, and no model is adopted. Assessment execution does not generate a forecast, uncertainty bounds, preparedness outputs, a model card, or a deployment latest-pointer update. The runtime remains trusted/internal and requires reverse-proxy access controls before public exposure.
