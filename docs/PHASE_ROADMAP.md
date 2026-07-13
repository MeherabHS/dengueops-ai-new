# DengueOps AI — Phase Roadmap

## Phase 0: Scaffold & Showcase (Current)

**Status:** Complete  
**Purpose:** IEEE ICADHI showcase, MSc portfolio demonstration

### Deliverables
- [x] Next.js App Router scaffold
- [x] TypeScript component architecture
- [x] Tailwind CSS UI system
- [x] Recharts dashboard with placeholder data
- [x] All route pages (/, /dashboard, /methodology, /validation, /ethics, /assumptions, /about)
- [x] Placeholder JSON data contracts (7 files)
- [x] Python analytics pipeline stubs (10 modules)
- [x] Full documentation skeleton
- [x] Ethics and assumptions transparency layer

### Constraints
- Static JSON data only
- No backend, no database, no authentication
- Synthetic/demo data throughout
- No real-time capabilities

---

## Phase 1: Data Integration & Full Analytics

**Status:** Planned  
**Purpose:** Working prototype with validated data

### Deliverables
- [ ] DGHS/IEDCR aggregate surveillance data integration
- [ ] Bangladesh Meteorological Department climate data pipeline
- [ ] Full `feature_engineering.py` implementation
- [ ] Full `forecast_model.py` training pipeline
- [ ] Full `validation_backtest.py` with real backtest results
- [ ] Full `uncertainty_engine.py` with calibrated bounds
- [ ] Full `spatial_exposure_engine.py` with validated zone weights
- [ ] Full `operational_engine.py` with real facility data
- [ ] FastAPI backend (REST API for forecast + directives)
- [ ] PostgreSQL or SQLite database
- [ ] Validated backtest results replacing placeholder metrics
- [ ] Real facility + inventory data from health authority

### Requirements
- Data sharing agreement with DGHS/IEDCR or DSCC
- Validated facility capacity and inventory data
- IRB/ethics clearance for data use (if required)

---

## Phase 2: Operational Deployment & Scale-Up

**Status:** Future  
**Purpose:** Multi-city pilot deployment

### Planned Features
- Multi-city support (Dhaka North, Chittagong, Sylhet)
- Ward-level spatial model (validated geospatial boundaries)
- Real-time inventory API integration
- Automated directive generation pipeline
- Health authority dashboard access
- Mobile-responsive field use interface

---

## Phase 3: Advanced Capabilities

**Status:** Research horizon  
**Purpose:** Academic extension and policy impact

### Planned Research
- Calibrated probabilistic forecast intervals (quantile regression / conformal prediction)
- Causal climate-dengue modelling (beyond correlation)
- SHAP-based instance-level explainability
- Bangla language interface
- Integration with EWARN or similar early warning systems
- Scenario planning for climate change projections

---

## Technology Upgrade Path

| Phase | Frontend | Backend | Database | Data | Analytics |
|-------|----------|---------|----------|------|-----------|
| 0 | Next.js + static JSON | None | None | Synthetic | Stubs |
| 1 | Next.js + FastAPI | FastAPI | PostgreSQL | DGHS/BMD aggregate | Full scikit-learn |
| 2 | Next.js + FastAPI | FastAPI + Celery | PostgreSQL + Redis | Multi-source | Advanced ML |
| 3 | Next.js + Mobile | FastAPI | Distributed | Real-time feeds | Research models |

---

*Last updated: Phase 0 — May 2026*
