# DengueOps AI — Project Summary

**Full Title:** DengueOps AI: Simulation-Based Dengue Surge Preparedness Decision Support for Dhaka South

**Submission:** IEEE ICADHI 2026 — Track 06: Health Data Analytics & Predictive Systems

**Project Type:** Research prototype / IEEE showcase / MSc scholarship portfolio

---

## Core Positioning

> DengueOps AI does not claim a novel forecasting algorithm. Its contribution is the **operational decision-support layer** that converts lag-aware outbreak forecasts into uncertainty-aware preparedness metrics and public health action priorities.

---

## Problem Statement

Dhaka South faces recurring dengue surges, yet preparedness responses — bed activation, supply procurement, vector control — are typically triggered reactively, after cases are already overwhelming facilities.

Existing public health surveillance data is underutilised for operational planning. The gap is not the absence of forecasts, but the absence of a framework to convert forecasts into actionable preparedness intelligence.

---

## System Overview

DengueOps AI is a simulation-based decision-support prototype that:

1. Takes a city-level dengue case forecast (2-week horizon)
2. Generates uncertainty-aware scenarios (best/expected/worst case)
3. Allocates forecast cases to operational zones via a spatial exposure heuristic
4. Computes supply depletion horizons (SDH) per facility
5. Estimates projected bed load and bed gap using LOS approximation
6. Generates tiered operational directives per zone and facility

---

## Technical Stack

- **Frontend:** Next.js App Router, TypeScript, Tailwind CSS, Recharts, Lucide React
- **Analytics:** Python, scikit-learn (GradientBoostingRegressor), pandas, numpy
- **Data Phase 0:** Static JSON placeholder files
- **Data Phase 1:** DGHS/IEDCR aggregate surveillance + Bangladesh Meteorological Department climate data

---

## Key Metrics Produced

| Metric | Formula | Threshold |
|--------|---------|-----------|
| Illustrative Supply Depletion Horizon (SDH) | Current Stock / Provisional Dynamic Daily Demand | Prototype critical ≤3d; NS1 warning ≤7d; IV-fluid warning ≤5d; not approved |
| Illustrative Projected Bed Load | Occupied Beds + (Expected Daily Admissions × Avg LOS) | Positive Bed Deficit = max(0, Projected Load − Dengue Capacity) |
| Experimental Planning-Priority Score | Governed structural + forecast-growth heuristic | Synthetic benchmark only; not an official priority |
| Forecast Growth Factor | Forecast Cases / 4-week prior-case mean | Provisional categories; not outbreak-risk thresholds |

---

## Phase 0 Deliverables

- Complete project scaffold (Next.js + TypeScript)
- All route pages with placeholder content
- Recharts dashboard with placeholder data
- Placeholder JSON data files (5 zones, 5 facilities, 10 inventory items)
- Python analytics pipeline stubs (10 modules)
- Full documentation skeleton

---

## Authors & Affiliation

*[To be completed before submission]*

---

## Ethics Commitment

- Aggregated/synthetic data only — no patient-level data
- Human-in-the-loop by design — all outputs are advisory
- Explicit assumption and limitation disclosure
