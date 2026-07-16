# DengueOps AI — A Story-Based User Guide

> For anyone who wants to understand what this app does and how to use it — no technical background required.

---

## The Problem: A City Caught Off Guard

Imagine it's August in Dhaka South. The monsoon rains have been heavy for three weeks. In the Kamrangirchar neighbourhood — one of the city's most densely packed areas — people are starting to fall sick. Dengue fever.

At the district health office, an analyst opens a spreadsheet. It has last week's case numbers. That's it. No forecast of what's coming. No alert about which hospitals might run out of NS1 test kits. No map showing which neighbourhoods need vector-control teams most urgently.

A decision-maker has to act — but has no system telling them *where to act first*, *how many beds to prepare*, or *how long the current supplies will last*.

**DengueOps AI was built for that exact moment.**

---

## What the App Actually Does

Think of DengueOps AI as a **preparedness translator**.

It takes raw inputs — dengue case trends, climate signals like rainfall and humidity, facility data — and converts them into plain, actionable intelligence:

> *"Cases are projected to rise 49% in the next 14 days. Kamrangirchar is your highest-priority zone. Two facilities there may run out of NS1 test kits within 8 days. Activate contingency planning."*

That's the output. Not a spreadsheet. Not a raw model number. A translated, human-readable alert.

---

## Walking Through the App — Room by Room

### 🏠 The Front Door — Landing Page (`/`)

When you first arrive, you see the **landing page**. Think of it as the project's lobby.

It answers the first question any visitor has: *"What is this and why does it matter?"*

You'll see:
- The **problem** clearly described — reactive dengue response vs. proactive preparedness
- A **6-step workflow** showing how raw data becomes operational directives
- The **core modules** explained in plain language
- **User roles** — who uses this system and how
- A **live preview** of current forecast numbers

It ends with buttons to explore the dashboard, methodology, or validation evidence.

---

### 🎛️ The Control Room — Dashboard (`/dashboard`)

This is the heart of the app. Everything happens here.

**Step 1 — Read the banners at the top.**
The coloured banners tell you upfront: *"This uses synthetic demonstration data."* That means the numbers are realistic but not real patient records. No privacy concerns.

**Step 2 — Pick your forecast scenario.**
Three buttons: **Best Case**, **Expected Case**, **Worst Case**.

This is like weather forecasting — you don't just get one number, you get a range. Switch between them and the metric cards at the top update instantly.

**Step 3 — Read the 8 metric cards.**
These cards answer the most important questions at a glance:

| Card | What it tells you |
|------|-------------------|
| Forecasted Cases | Projected dengue cases in the next 14 days |
| Growth Factor | How fast cases are rising vs the last 4-week average |
| Forecast Growth Category | Experimental forecast-growth band; not an official outbreak classification |
| Critical Supply Alerts | Items falling below a 7-day stock threshold |
| Highest Priority Zone | The zone needing the most urgent attention |
| Highest Pressure Facility | The facility with the most expected bed deficit |
| Facilities — Bed Gap | How many of the 11 facilities may face a bed shortage |
| Facilities Monitored | Total facilities in the system |

**Step 4 — Explore the Surge Simulation.**
Below the main metrics is an interactive "what-if" layer. Five buttons let you ask scenario questions:

| Scenario | What it simulates |
|----------|-------------------|
| **Normal Monitoring** | Baseline — no extra pressure |
| **Old Dhaka Surge** | Dense referral pressure in the historic centre |
| **Kamrangirchar Surge** | High-vulnerability informal settlement under stress |
| **Jatrabari Mobility Surge** | Transport corridor spillover risk |
| **City-Wide Critical Surge** | Everything under pressure simultaneously |

When you select a surge, the **heatmap** on the right lights up — each zone block changes colour from green → yellow → orange → red depending on how severe the simulated pressure is. A before/after chart shows exactly how much each zone's priority score would change.

> **Important:** This is a "what-if" planning tool — it does not change the forecast model. It helps decision-makers rehearse their response before an outbreak escalates.

**Step 5 — Switch your role using the tabs.**

Four tabs appear near the bottom:

| Tab | Who it's for | What they see |
|-----|--------------|---------------|
| **Operational** | Public health analysts | Zone priority ranking, operational directives, recommended actions |
| **Facility** | Hospital administrators | All 11 facilities, bed pressure, supply depletion timelines |
| **Public Advisory** | Communications team | Plain-language public messaging |
| **Technical Validation** | Researchers, evaluators | Model accuracy, pipeline details, feature importance |

Each tab shows the *same underlying data* — just presented for a different audience.

---

### 🔬 The Laboratory — Methodology Page (`/methodology`)

This page is for anyone who asks *"but how does it actually work?"*

It walks through the entire analytics pipeline step by step — with formulas, diagrams, and plain explanations:

1. Raw data goes in (dengue cases + climate)
2. Lag-aware features are built — because a mosquito breeding event today doesn't show up in a hospital until 2–4 weeks later
3. A machine learning model (Gradient Boosting) makes a 14-day forecast
4. That forecast gets expanded into 3 uncertainty scenarios
5. Cases are allocated to zones using an exposure formula
6. Facilities are checked for supply depletion and bed pressure
7. Zone priority scores are calculated
8. All of this becomes the directives and alerts you see in the dashboard

You don't need to read this page to use the dashboard. But it's there so nothing is a black box.

---

### 📋 The Evidence Room — Validation Page (`/validation`)

This page answers a critical question: *"Did you just pick a random model and trust it?"*

The answer is no — and this page proves it.

It shows:
- Three models were tested: Naive Baseline, Moving Average, and Gradient Boosting
- They were tested on the **final 20% of historical data** — the model never saw those weeks during training
- Gradient Boosting achieved the **lowest error** (MAE: 47, vs Naive MAE: 149)
- The validation RMSE (67.8 cases) is directly used to build the uncertainty band you see in the dashboard

The page ends with a clear statement of what this *proves* (pipeline works, baselines compared) and what it *does not prove* (clinical validity, real-world deployment accuracy).

---

### 🛡️ The Ethics Room — Ethics Page (`/ethics`)

Six simple commitments, explained clearly:

1. **No patient-level data** — ever
2. **Facility readiness numbers are synthetic** — not real hospital records
3. **A human must review every output** before any action is taken
4. **The system does not diagnose dengue**
5. **Uncertainty is always shown** — never hidden
6. **Vulnerable zones are not permanently penalised** regardless of current risk

This page also explains what each type of user is *responsible for* when using the system.

---

### 📌 The Fine Print — Assumptions Page (`/assumptions`)

Every system has limits. This page lists them openly so no one is misled:

- The dengue case data used is synthetic — not from real surveillance
- The hospital names are real geographic anchors, but the bed numbers and stock levels are illustrative
- The spatial zone allocation is a formula, not a validated geographic model
- The uncertainty band is RMSE-derived, not a calibrated probabilistic forecast

It also shows a **roadmap** — eight steps that would be needed to turn this prototype into a real operational system.

---

## The Big Picture — Who Does What

```
MIS / Data Officer
  → runs the Python pipeline, keeps data fresh

Public Health Analyst
  → checks the dashboard daily, reads zone priorities and directives

Hospital Administrator
  → monitors facility readiness tab, confirms real stock before acting

Vector-Control Team
  → uses zone priority heatmap to decide where to deploy fogging teams

Technical Evaluator / Researcher
  → reviews validation tab, methodology page, and assumptions
```

---

## Navigating the App — Quick Reference

| Page | URL | Purpose |
|------|-----|---------|
| Landing Page | `/` | Overview and entry point |
| Dashboard | `/dashboard` | Live operational view — forecasts, zones, facilities, directives |
| Methodology | `/methodology` | How the analytics pipeline works |
| Validation | `/validation` | Model accuracy evidence and limitations |
| Ethics | `/ethics` | Responsible use and data privacy commitments |
| Assumptions | `/assumptions` | Transparent boundaries and known limitations |

---

## What DengueOps AI Is — and Is Not

| It IS | It IS NOT |
|-------|-----------|
| A preparedness decision-support prototype | A live clinical system |
| Transparent about all its assumptions | Claiming to use real hospital data |
| Human-in-the-loop by design | An autonomous decision-maker |
| Built for IEEE evaluation and portfolio review | Deployment-ready without further validation |
| A demonstration of AI-assisted public health preparedness | A replacement for public health expertise |

---

## Frequently Asked Questions

**Q: Is the data real?**
No. The dengue case trends, facility stock levels, and bed occupancy figures are all synthetic demonstration values. Public hospital names are used as geographic anchors, but all operational numbers are illustrative.

**Q: Can I trust the forecast numbers?**
The numbers reflect a realistic prototype pipeline, not a validated live surveillance system. Always treat outputs as planning signals, not definitive predictions.

**Q: Do I need to run any code to use the dashboard?**
No. The analytics pipeline is run separately by technical staff. The dashboard is a read-only interface — just open it in a browser.

**Q: What does "human-in-the-loop" mean?**
It means the system never takes action on its own. It surfaces alerts and simulated planning suggestions without institutional approval. A qualified person — a public health official, hospital administrator, or analyst — always reviews and decides before anything happens in the real world.

**Q: What is the surge simulation for?**
It's a planning rehearsal tool. Instead of waiting for a crisis, public health teams can simulate *"what if Kamrangirchar sees a 30% spike?"* and see which facilities need pre-positioning, which zones need vector-control escalation, and what the bed pressure would look like.

---

## One-Sentence Summary

> DengueOps AI shows what it would look like if a city health office could open a dashboard on Monday morning and immediately know — based on last week's case trends and rainfall — which zones are at rising risk, which hospitals need to stock up, and where to send the vector-control team first.

That's the idea. The prototype makes it tangible.

---

*DengueOps AI — Simulation-Based Dengue Surge Preparedness Decision Support for Dhaka South.*
*IEEE ICADHI 2025 · Prototype only · Not for clinical or official public health use.*
