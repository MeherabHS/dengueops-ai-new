# DengueOps AI: Proposal and Fixes

## Purpose

This document is the working plan for turning DengueOps AI from an overclaimed
research prototype into a credible V2 forecasting and preparedness platform.

The current repository already contains a useful foundation:

- A Python pipeline for feature engineering, model training, validation,
  uncertainty scenarios, operational calculations, and JSON export
- A Next.js dashboard that visualizes forecasts, readiness metrics, and
  directives
- Strong synthetic-data and ethics disclosures in much of the application
- Deterministic demo-data generation and reproducible model parameters

V2 work must first correct analytical validity and data lineage. Backend scale,
live integrations, and richer UI features should follow only after those
foundations are reliable.

## Target V2 Outcome

DengueOps AI V2 should:

1. Produce a genuine two-week-ahead forecast from the latest available
   observation.
2. Support explicit, non-overlapping synthetic and real-data pipeline modes.
3. Validate model performance with expanding-window backtesting.
4. Generate every displayed analytical value from traceable pipeline outputs.
5. Implement one canonical set of operational formulas across code and docs.
6. Expose versioned results through a backend API instead of build-time JSON
   imports.
7. Preserve clear advisory, synthetic-data, and human-review boundaries.

## Non-Goals

The first V2 release will not:

- Diagnose or triage individual patients
- Use patient-level health records
- Trigger procurement, bed activation, or vector-control actions automatically
- Claim clinical, epidemiological, or operational validation before a formal
  external evaluation
- Treat OpenDengue national data as a substitute for Dhaka South surveillance

## Priority 0: Correctness Blockers

These issues must be resolved before adding new product features.

### P0.1 Generate a true future forecast

**Current problem:** `feature_engineering.py` drops the final rows whose future
targets are unknown. `forecast_model.py` then trains on the last remaining row
and predicts that row's already known target period. The displayed forecast is
therefore in-sample and does not extend beyond the latest raw observation.

**Required changes:**

- Separate supervised training rows from inference rows.
- Build features for the latest raw observation without requiring target values.
- Train only on rows with known targets.
- Predict two epidemiological weeks beyond the latest raw observation.
- Record the training cutoff, inference origin, target week, dataset version,
  and model version in `forecast_output.json`.

**Acceptance criteria:**

- If input data ends at 2026-W24, the forecast target is 2026-W26.
- The inference row is not included as a labeled training sample for its target.
- An automated test verifies year-boundary behavior, including W51/W52 rollover.
- The dashboard shows both latest observed week and forecast target week.

### P0.2 Repair data-source selection

**Current problem:** the standard `--use-opendengue` run fetches real data and
then `generate_demo_data.py` overwrites it with synthetic cases. Real case and
climate sources also have incompatible date coverage in common flag combinations.

**Required changes:**

- Replace step insertion with an explicit pipeline configuration:
  `case_source` and `climate_source`.
- Run exactly one producer for each input dataset.
- Never let demo generation overwrite a selected real source.
- Validate geographic level, time range, frequency, source tag, and overlap
  before feature engineering.
- Fail clearly when the joined history is below a configured minimum.

**Acceptance criteria:**

- Synthetic mode produces only `synthetic_demo` source tags.
- OpenDengue mode preserves `opendengue` source tags through final artifacts.
- NASA POWER mode preserves `nasa_power` source tags.
- Unsupported or insufficient source combinations fail before model training.
- Integration tests cover all supported source combinations.

### P0.3 Establish one canonical formula contract

**Current problem:** README, documentation, methodology UI, and Python code use
conflicting priority, exposure, bed-gap, risk-score, and SDH alert definitions.
The anomaly adjustment is also applied twice using incompatible operations.

**Required changes:**

- Create a versioned formula specification covering inputs, units, signs,
  thresholds, caps, and missing-value behavior.
- Decide whether anomaly adjustment is additive or multiplicative and apply it
  exactly once.
- Standardize positive bed gap as deficit or surplus and use the same convention
  everywhere.
- Standardize SDH alert levels and item-specific thresholds.
- Align risk-score breakpoints and priority categories.
- Update code, dashboard labels, README, and docs from the approved contract.

**Acceptance criteria:**

- Unit tests cover boundary values for every formula.
- Formula examples in documentation match test fixtures exactly.
- No active page displays an obsolete formula.
- Allocated zone cases sum to the city forecast within a defined rounding
  tolerance.

### P0.4 Remove placeholder analytical evidence

**Current problem:** feature importance is a fixed placeholder while the UI
presents it beside real pipeline metrics. Some documentation also reports stale
validation figures and unsupported R-squared or walk-forward claims.

**Required changes:**

- Generate permutation importance or model-derived feature importance from the
  fitted validation model.
- Include method, model version, dataset version, fold, and generation timestamp.
- Remove placeholder validation imports from `lib/demo-data.ts`.
- Remove unused placeholder analytical files from active application paths.
- Reconcile all metrics and methodology claims with generated artifacts.

**Acceptance criteria:**

- Changing training data can change the generated feature importance values.
- The dashboard imports feature importance only from a pipeline artifact.
- MAE, RMSE, MAPE, AVP, uncertainty, and importance share the same run ID.
- Documentation contains no fixed performance claims without an artifact link or
  run identifier.

## Priority 1: Validation and Reproducibility

### P1.1 Expanding-window backtesting

- Replace the single 80/20 holdout with multiple forecast origins.
- Keep naive, seasonal-naive, and moving-average baselines.
- Report aggregate and per-fold MAE, RMSE, MAPE or WAPE, bias, and sample count.
- Separate model selection data from final evaluation data.
- Report performance by season and surge/non-surge periods.

### P1.2 Calibrated uncertainty

- Retain the RMSE band only as a clearly labeled legacy heuristic.
- Add conformal prediction, quantile regression, or another calibrated method.
- Measure empirical interval coverage and average interval width.
- Backtest best/expected/worst operational outcomes, not only point forecasts.

### P1.3 Data contracts and quality gates

- Define schemas for cases, climate, zones, facilities, and inventory.
- Validate types, value ranges, duplicates, missing weeks, date/week agreement,
  geography, units, source tags, and minimum history.
- Preserve raw inputs separately from normalized and modeled datasets.
- Generate a provenance manifest with hashes and transformation versions.

### P1.4 Automated tests and CI

- Add unit tests for features, targets, formulas, source adapters, and date logic.
- Add integration tests for each pipeline mode.
- Add artifact-schema tests for every dashboard JSON contract.
- Add frontend component and end-to-end tests for critical dashboard workflows.
- Run Python tests, linting, TypeScript checks, and Next.js builds in CI.

## Priority 2: Runtime Platform

### P2.1 Backend and job execution

- Add a FastAPI service for datasets, pipeline runs, forecasts, and directives.
- Execute pipeline runs through a background job queue.
- Store raw uploads, normalized datasets, artifacts, logs, and failures by run ID.
- Use atomic publication so the dashboard never reads partially written outputs.

### P2.2 Database and artifact storage

- Use PostgreSQL for metadata, users, facilities, inventory, and run history.
- Use object storage for uploaded files, trained models, and generated artifacts.
- Add retention, backup, restore, and deletion policies.

### P2.3 Runtime dashboard data

- Replace build-time JSON imports with typed API queries.
- Add loading, empty, stale, failed, and partial-data states.
- Display dataset source, geography, period, run status, model version, and
  freshness beside every decision-relevant result.
- Keep the demo mode available but visually and technically isolated.

### P2.4 Real CSV upload workflow

- Upload files to the backend rather than only reading them with `FileReader`.
- Perform server-side schema and content validation.
- Show validation errors by row and column.
- Require explicit confirmation before starting a pipeline job.
- Track job progress and publish results only after all checks pass.

## Priority 3: Operational Readiness

- Add authentication, role-based authorization, and session management.
- Maintain immutable audit logs for uploads, runs, reviews, and approvals.
- Add human approval states for directives.
- Integrate authorized facility capacity and inventory sources.
- Replace the schematic zone grid with validated geographic boundaries.
- Add data freshness, pipeline failure, model drift, and distribution-shift
  monitoring.
- Add Bangla localization and accessibility testing.
- Conduct prospective silent-mode evaluation before exposing recommendations to
  operational users.

## Proposed Architecture

```text
Authorized sources / CSV uploads
              |
              v
     Ingestion and validation API
              |
              v
      Raw immutable data store
              |
              v
       Versioned pipeline job
       | feature engineering
       | backtesting and training
       | calibrated uncertainty
       | operational calculations
       | explainability
              |
              v
   Versioned model and artifact store
              |
              v
        Typed forecast API
              |
              v
       Next.js dashboard
              |
              v
    Human review and approval log
```

## Recommended Work Sequence

1. Add a focused regression test that exposes the current W24/W26 forecast bug.
2. Refactor feature building into training and inference paths.
3. Correct the forecast origin and target metadata.
4. Replace pipeline step insertion with explicit source configuration.
5. Add source compatibility and data-quality validation.
6. Approve and implement the canonical formula contract.
7. Add expanding-window backtesting and generated feature importance.
8. Remove placeholder analytical evidence and reconcile documentation.
9. Add full automated pipeline and frontend contract tests.
10. Design and implement the backend only after correctness gates pass.

## Definition of Credible V2

V2 may be described as a credible forecasting prototype when all of the
following are true:

- Forecasts target periods strictly after the latest observed data.
- Every displayed analytical value is traceable to a versioned pipeline run.
- Real and synthetic sources cannot be silently mixed or overwritten.
- Validation uses multiple chronological forecast origins and honest baselines.
- Uncertainty coverage is measured.
- Operational formulas are consistent, tested, and documented.
- Synthetic/demo status remains visible at every relevant decision surface.
- Automated tests prevent regression of these guarantees.

It should not be described as operationally deployment-ready until authorized
local data, external validation, security controls, monitoring, institutional
governance, and prospective evaluation are complete.

## Working Decision Log

Use this section to record approved implementation decisions before code changes.

| Date | Decision | Rationale | Owner | Status |
|---|---|---|---|---|
| TBD | Canonical anomaly adjustment | Pending review | TBD | Open |
| TBD | Bed-gap sign convention | Recommend positive = deficit | TBD | Open |
| TBD | SDH thresholds | Pending operational review | TBD | Open |
| TBD | Primary uncertainty method | Recommend conformal evaluation | TBD | Open |
| TBD | Supported V2 data sources | Pending data availability review | TBD | Open |

## Technical Debt Register

### TD-P03A-LEGACY-RISK-FIELDS — Legacy compatibility fields

Current maturity: **Technically functioning, scenario-tested, formula-governed research prototype.**

The project is not yet a **locally calibrated, epidemiologically validated,
hospital-approved operational system.**

The artifact and frontend fields `risk_level`, `risk_score`, and
`recommendations` are retained temporarily for backward compatibility only.
They are not authoritative. The canonical governed fields are
`forecast_growth_category`, `experimental_growth_score`,
`planning_priority_tier`, and `planning_suggestions`.

This debt must be resolved before live uploads, external API exposure, or any
third-party integration. The migration gate must select and complete one of:

- schema deprecation with a documented compatibility lifetime;
- nesting the retained fields under `legacy_compatibility`; or
- removal through a versioned API migration.

Until that gate is complete, the legacy fields must not be presented as the
canonical contract or used as evidence of operational readiness. They must not
be removed or renamed without the selected versioned migration.

Status: **Open**. Resolution gate: **before live-data/API/integration exposure**.

## Initial Implementation Start Point

Start with **P0.1: Generate a true future forecast**. It is the highest-impact
correctness defect and can be addressed independently of backend architecture.
The first code change should be preceded by tests that demonstrate the current
forecast-origin failure and define the expected W+2 behavior.
