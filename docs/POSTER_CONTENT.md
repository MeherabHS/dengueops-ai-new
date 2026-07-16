# DengueOps AI — Poster Content Guide

**Format:** IEEE ICADHI research poster  
**Size:** A1 or A0 landscape recommended  
**Style:** Professional health-tech; navy/white/cyan palette

---

## Title Block

**Main Title:**
DengueOps AI: Simulation-Based Dengue Surge Preparedness Decision Support for Dhaka South

**Subtitle / Track:**
IEEE ICADHI 2026 — Track 06: Health Data Analytics & Predictive Systems

**Authors:** *[Author names and affiliations]*

---

## Abstract (60–80 words)

DengueOps AI is a simulation-based public health decision-support prototype that converts
lag-aware dengue outbreak forecasts into uncertainty-aware preparedness metrics for Dhaka South.
The system computes Supply Depletion Horizons (SDH), LOS-based bed pressure estimates, spatial
exposure-based zone priorities, and operational directives — all designed for data-scarce urban
health settings. Phase 0 demonstrates the full decision-support architecture using placeholder data.

---

## Problem Panel

**Title:** Reactive Dengue Response in Dhaka South

- Surges overwhelm facilities before procurement is triggered
- NS1/RDT kit stockouts at peak epi weeks
- No zone-level resource allocation framework
- Forecast data not converted into supply or bed planning
- Data-scarce urban settings lack validated geospatial coverage

---

## Innovation Panel

**Title:** Forecast → Preparedness Intelligence

> "DengueOps AI does not claim a novel forecasting algorithm. Its contribution is the
> operational decision-support layer that converts lag-aware outbreak forecasts into
> uncertainty-aware preparedness metrics and public health action priorities."

**Workflow diagram:**

Dengue + Climate Data → Lag Features → GBR Forecast → Uncertainty Scenarios →
Spatial Allocation → SDH + Bed Load → Directives

---

## Methodology Panel

**Key Formulas:**

```
Dynamic Daily Demand = Baseline Consumption × Growth Factor
SDH = Current Stock / Dynamic Daily Demand
Projected Bed Load = Occupied Beds + (Daily Cases × Avg LOS)
Planning Priority Score = Experimental Growth Score × (1 + Vulnerability Weight)
```

**Feature Engineering:**
- 14-day and 28-day climate lags (rainfall, humidity, temperature)
- 3-week rolling case average
- Sine/cosine seasonal encoding

**Validation:**
- Walk-forward backtest (no data leakage)
- MAE: 42.3 | RMSE: 61.8 | MAPE: 14.7%

---

## Dashboard Panel

*[Screenshot of dashboard: metric cards + zone risk table + supply depletion chart]*

Caption: "Phase 0 dashboard with placeholder data demonstrating the full decision-support interface"

---

## Results Panel

| Zone | Priority Score | Bed Gap | NS1 SDH |
|------|---------------|---------|---------|
| Kamrangirchar | 1.16 | −7 beds | 5 days ⚠ |
| Mitford / Old Dhaka | 0.98 | −9 beds | 8 days ⚠ |
| Jatrabari | 0.85 | −4 beds | 11 days |
| Lalbagh | 0.74 | −4 beds | 13 days |
| Dhanmondi | 0.62 | +2 beds | 15 days ✓ |

---

## Ethics Panel

✓ Aggregated/synthetic data only — no patient-level data  
✓ Human-in-the-loop — all outputs advisory  
✓ Explicit assumption disclosure  
✓ No diagnosis or clinical decision-making  

---

## Future Work Panel

- Phase 1: DGHS/IEDCR data integration, FastAPI backend
- Phase 2: Multi-city deployment, validated spatial model
- Phase 3: Real-time pipeline, Bangla interface
- Research: Calibrated probabilistic forecasting, causal climate-dengue modelling

---

## QR Code Block

*[QR code linking to live demo / GitHub repository]*

**DengueOps AI — Phase 0 Prototype**  
IEEE ICADHI 2026
