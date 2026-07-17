# DengueOps AI

**Simulation-Based Dengue Surge Preparedness Decision Support for Dhaka South**

DengueOps AI is a research prototype that turns a two-week dengue case forecast into transparent preparedness signals: planning scenarios, zone priorities, projected bed pressure, supply depletion horizons, and suggested operational actions. A Next.js dashboard presents the outputs; a governed Python pipeline produces the underlying evidence and artifacts.

The repository also contains a trusted-internal runtime workflow for validating uploaded datasets, running an eligible point forecast, comparing governed candidate models, recording a one-run model-use decision, and committing an approved forecast without overwriting the bundled benchmark until a complete run passes its integrity checks.

> **Important:** this is a synthetic, benchmark-only capability demonstration. It is not locally calibrated, epidemiologically validated, hospital-approved, or authorized for clinical or operational use. It does not diagnose dengue or recommend patient-level treatment.

## What the system provides

- A two-week, lag-aware dengue case forecast.
- Deterministic temporal validation and governed candidate-model comparison.
- A prior-only empirical forecast range for the bundled synthetic benchmark.
- Preparedness scenarios for low, base, and high planning conditions.
- Zone-level exposure allocation and an Experimental Growth Score used only as a provisional analytical indicator.
- Facility-level bed-load, bed-deficit, and supply-depletion estimates.
- Role-oriented dashboard views for operations, facilities, and technical review.
- Run-specific provenance, formula-registry bindings, model cards, and explainability artifacts.
- Isolated CSV upload workspaces and file-backed runtime job execution.
- Immutable dataset assessments and trusted-internal, one-run forecast authorization.

All readiness values, inventory levels, sub-city operational inputs, alerts, directives, and notification outputs in the bundled demonstration are synthetic. The Experimental Growth Score and related planning-priority outputs are provisional and not institution-approved for clinical or operational decision-making. No patient-level records are used or stored.

## Current governed benchmark

The committed `dhaka_south` profile is a deterministic `synthetic_benchmark` deployment with a `benchmark_only` gate.

| Item | Current implementation |
| --- | --- |
| Forecast horizon | 2 weeks |
| Feature contract | 18 lag, rolling, trend, seasonality, and climate features |
| Primary validation | Expanding-window rolling origin with 104 initial training rows, a 1-row embargo, and 68 one-row folds |
| Candidate set | Previous-week naive, 4-week moving average, 52-week seasonal naive, Ridge, Poisson, Random Forest, Gradient Boosting |
| Selected benchmark model | Frozen `RandomForestRegressor`, selected by lowest eligible rolling-origin MAE |
| Forecast range | Prior-only expanding absolute-residual empirical range: 20 warm-up folds and 48 evaluated folds |
| Operational layer | Spatial exposure allocation, bed pressure, supply depletion, planning priority, directives |
| Governance | Versioned JSON Schemas, formula registry, evidence registry, deployment profile, provenance hashes, model card |

The empirical range is synthetic temporal evidence—not a confidence interval, prediction interval, or probability guarantee. The separate low/base/high preparedness scenarios are compatibility planning inputs and do not define forecast uncertainty.

## Architecture

```text
Governed configuration
  config/formulas.json
  config/candidate_models.json
  config/deployments/dhaka_south/*
              |
              v
Python analytics pipeline
  input production and validation
    -> 18-feature matrix
    -> temporal validation and model comparison
    -> selected-model forecast and diagnostics
    -> empirical range
    -> operational preparedness engine
    -> dashboard export
              |
              v
Bundled artifacts in data/
              |
              v
Next.js App Router dashboard

Uploaded CSVs -> isolated runtime workspace -> queued file-backed worker
  -> Quick Forecast -> atomic runtime run -> deployment latest pointer
  -> Dataset Assessment -> immutable evidence -> internal one-run decision
     -> approved point forecast -> atomic runtime run -> latest pointer
```

The bundled pipeline writes governed artifacts to `data/`. Uploaded files and their results live under a separate absolute runtime root; runtime processing never writes uploaded inputs into `data/`. The dashboard API serves the bundled benchmark until a runtime forecast has been fully validated, atomically committed, and assigned as the deployment's latest run.

## Technology

| Layer | Stack |
| --- | --- |
| Web application | Next.js 16.2.6 App Router, React 19.2, TypeScript 5 |
| UI | Tailwind CSS 4, Recharts 3, Lucide React |
| Analytics | Python 3.10+, pandas, NumPy, SciPy, scikit-learn |
| Validation | Python `unittest`, Node.js test runner, JSON Schema Draft 2020-12 |
| Storage | Source-controlled benchmark artifacts plus isolated file-backed runtime workspaces and jobs |

## Quick start

### Requirements

- Node.js 20.9 or newer
- npm
- Python 3.10 or newer
- `pip`

On Windows, replace `python` with `py -3` in the commands below if the Python launcher is installed but `python.exe` resolves to the Microsoft Store alias.

### Install and run the bundled dashboard

```bash
npm install
pip install -r requirements.txt
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). The repository already includes a complete governed benchmark artifact set, so regenerating the analytics output is optional for viewing the application.

### Regenerate the governed benchmark

```bash
python analytics/run_pipeline.py \
  --deployment-profile dhaka_south \
  --run-model-comparison
```

This regenerates the deterministic synthetic benchmark, runs the seven-candidate comparison, adopts the governed winner for that run, produces the empirical forecast range and operational outputs, validates cross-artifact provenance, and refreshes the dashboard exports.

Useful pipeline commands:

```bash
# Default controlled synthetic-demo pipeline without the profiled candidate adoption
python analytics/run_pipeline.py

# Reuse existing inputs
python analytics/run_pipeline.py --skip-data-generation

# Validate the committed output bundle without running producers
python analytics/run_pipeline.py --validate-only

# Rebuild only dashboard-facing exports from existing artifacts
python analytics/run_pipeline.py --export-dashboard-only
```

Run `python analytics/run_pipeline.py --help` for all source, benchmark-scenario, acknowledgment, and deployment-gate options.

## Data modes

| Mode | Purpose | Status |
| --- | --- | --- |
| `synthetic_benchmark` | Deterministic, wholly synthetic governed capability benchmark | Active `dhaka_south` profile |
| `synthetic_demo` | Controlled 2024–2026 demonstration data | Default unprofiled pipeline |
| OpenDengue | Bangladesh national aggregate case data | Experimental adapter |
| NASA POWER | Point-based meteorological inputs used as a Dhaka South proxy | Experimental adapter |

Experimental source commands:

```bash
python analytics/run_pipeline.py --use-opendengue
python analytics/run_pipeline.py --use-nasa-power-climate
python analytics/run_pipeline.py --use-opendengue --use-nasa-power-climate
```

Mixing source types or treating point climate data as a city-level proxy may require explicit acknowledgment flags. The pipeline rejects unsupported combinations rather than silently treating them as equivalent. Real epidemiology or climate inputs do not make the synthetic operational readiness layer real, calibrated, or approved.

See [`data/README.md`](data/README.md) for input columns, provenance fields, source coverage, and artifact descriptions.

## Runtime forecasting and assessment

The `/forecast` workflow is separate from the bundled analytics pipeline. It accepts dengue and climate CSVs, stores them in an isolated workspace, normalizes and validates their contracts, and exposes only workflows allowed by the active deployment policies.

### Quick Forecast

Quick Forecast is available only when an upload matches the active `dhaka_south` compatibility policy. It:

- requires the governed geography, source, temporal, and 18-feature contracts;
- fits only the frozen approved Random Forest configuration;
- produces a point forecast for the two-week horizon;
- does not compare candidate models or calibrate upload-specific uncertainty;
- publishes null uncertainty bounds with `pending_dataset_specific_calibration`;
- disables scenarios, facilities, alerts, and directives because no uploaded-data planning policy is approved.

### Dataset Assessment

An eligible Phase 2 assessment upload must produce at least 157 labelled rows and 52–68 governed folds; histories with more available folds use the most recent contiguous 68-fold evaluation plan while retaining older validated rows in expanding training. The worker evaluates the same seven candidates on identical precommitted folds and commits rolling validation, comparison, recommendation, and summary evidence. A separate trusted-internal decision under decision policy `p2-v1` may authorize one selected learned model for one forecast run; assessment evidence alone never authorizes forecasting or changes the deployment model.

Recommendation-strength thresholds are not governed, so a technical winner remains `evidence_only` with strength `not_available`.

### One-run model decision and approved forecast

When trusted-internal decisions are enabled, an operator may record one of four immutable outcomes for a committed assessment: approve the technical winner, keep the current model, defer, or reject the assessment. An approving decision can create one authorization for one point-forecast run.

An approved forecast is bound to the assessment inputs, selected candidate parameters, decision commit, and authorization. It does not change the deployment-wide active model, rerun comparison, calibrate uncertainty, produce preparedness outputs, verify the operator's identity, or constitute institutional approval.

## Running the runtime worker locally

The web process validates uploads and queues jobs; a separate long-lived Python worker executes them. Both processes must use the same absolute runtime root.

PowerShell example:

```powershell
$env:DENGUEOPS_RUNTIME_ROOT = 'G:\dengueops-runtime'
$env:DENGUEOPS_PYTHON_EXECUTABLE = (Resolve-Path '.venv\Scripts\python.exe')

# Terminal 1
npm run dev

# Terminal 2
npm run runtime:worker
```

Linux/macOS example:

```bash
export DENGUEOPS_RUNTIME_ROOT=/var/lib/dengueops-ai
export DENGUEOPS_PYTHON_EXECUTABLE=/absolute/path/to/.venv/bin/python

# Run in separate terminals or services
npm run dev
npm run runtime:worker
```

The runtime root must be absolute and must not be the governed `data/` directory. Run `python analytics/runtime_worker.py --once` to process at most one queued job, which is useful for controlled development and testing.

### Runtime environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `DENGUEOPS_RUNTIME_ROOT` | `<repository>/runtime` | Absolute workspace, job, assessment, decision, and runtime-run storage root |
| `DENGUEOPS_PYTHON_EXECUTABLE` | None | Required absolute Python interpreter path for upload validation from the web process |
| `DENGUEOPS_MAX_UPLOAD_BYTES` | `10485760` | Maximum bytes per uploaded CSV |
| `DENGUEOPS_VALIDATION_TIMEOUT_MS` | `60000` | Upload validation timeout |
| `DENGUEOPS_QUICK_FORECAST_TIMEOUT_SECONDS` | `600` | Quick Forecast worker timeout |
| `DENGUEOPS_ASSESSMENT_TIMEOUT_SECONDS` | `1800` | Dataset Assessment worker timeout |
| `DENGUEOPS_APPROVED_FORECAST_TIMEOUT_SECONDS` | `600` | Approved forecast worker timeout |
| `DENGUEOPS_WORKSPACE_MAX_AGE_SECONDS` | `86400` | Maximum workspace age accepted when starting a job |
| `DENGUEOPS_DEFAULT_DEPLOYMENT_ID` | `dhaka_south` | Deployment served by the runtime dashboard API |
| `DENGUEOPS_INTERNAL_DECISION_ENABLED` | `false` | Enables trusted-internal assessment decisions |
| `DENGUEOPS_INTERNAL_DECISION_SECRET` | None | Server-side decision credential; must be at least 16 characters when enabled |
| `DENGUEOPS_INTERNAL_OPERATOR_ID` | None | Server-configured unverified internal operator identifier |
| `DENGUEOPS_DECISION_VALIDITY_SECONDS` | `2592000` | Maximum accepted assessment age for a decision |
| `DENGUEOPS_DECISION_REASON_MAX_LENGTH` | `1000` | Maximum decision-reason length |

Internal decision POST routes expect the protected `x-dengueops-internal-decision-secret` header. The secret must remain server-side and must never be exposed to browser JavaScript.

## Web routes

| Route | Purpose |
| --- | --- |
| `/` | Project positioning, workflow, roles, and prototype overview |
| `/dashboard` | Latest committed operational overview with role-based views |
| `/forecast` | Upload validation, Quick Forecast, Dataset Assessment, and internal approval workflow |
| `/preparedness` | Preparedness-focused facility and operational views |
| `/validation` | Rolling validation, candidate comparison, errors, and uncertainty evidence |
| `/methodology` | Inputs, feature engineering, formulas, and operational logic |
| `/assumptions` | Data boundaries, assumptions, limitations, and validation roadmap |
| `/ethics` | Safety boundaries, ethical principles, and user responsibilities |
| `/about` | Project and author information |

### API routes

| Method and route | Purpose |
| --- | --- |
| `GET /api/dashboard/latest` | Return the latest committed runtime dashboard or fall back to the bundled benchmark |
| `POST /api/runtime/validate` | Store, normalize, and validate dengue and climate CSVs in an isolated workspace |
| `POST /api/runtime/runs/quick` | Queue an eligible Quick Forecast |
| `POST /api/runtime/assessments` | Queue an eligible Dataset Assessment |
| `GET /api/runtime/assessments/:assessmentId` | Read a committed assessment summary |
| `GET /api/runtime/jobs/:jobId` | Poll a runtime job |
| `POST /api/runtime/assessments/:assessmentId/decisions` | Record a protected trusted-internal model-use decision |
| `GET /api/runtime/decisions/:decisionId` | Read a protected decision record |
| `POST /api/runtime/decisions/:decisionId/forecast` | Reserve authorization and queue the approved one-run forecast |

## Testing and quality checks

The Python suite uses the standard-library `unittest` runner; the API route suite uses Node's built-in test runner.

```bash
# Python analytics, schemas, governance, provenance, runtime, and frontend contracts
python -m unittest discover -s tests -p test_*.py

# Next.js route contract tests
npm run test:runtime-routes

# Frontend lint and production build
npm run lint
npm run build
```

Many Python tests exercise deterministic model fitting and full runtime commit paths and can take several minutes.

## Repository layout

```text
app/                         Next.js pages and API route handlers
components/                  Dashboard, forecast workflow, charts, and shared UI
lib/                         Frontend view models, contracts, utilities, and runtime storage
analytics/                   Pipeline stages, adapters, model evaluation, and runtime worker
analytics/benchmark/         Deterministic synthetic benchmark generator and scenarios
config/                      Schemas, model/formula registries, and deployment policies
config/deployments/          Deployment-specific profiles and runtime policies
data/                        Bundled inputs, evidence, model cards, and dashboard artifacts
docs/                        Methodology, ethics, limitations, roadmap, and project materials
tests/                       Python and Node contract/regression tests
```

Important governance files:

- [`config/deployments/dhaka_south/profile.json`](config/deployments/dhaka_south/profile.json) — benchmark deployment scope, maturity, and prohibited claims.
- [`config/candidate_models.json`](config/candidate_models.json) — frozen seven-model candidate registry.
- [`config/formulas.json`](config/formulas.json) — versioned operational formula and threshold registry.
- [`config/evidence_registry.json`](config/evidence_registry.json) — linked scientific and institutional evidence records; currently empty.
- [`data/model_card.json`](data/model_card.json) — run-bound model, validation, uncertainty, provenance, and maturity statements.
- [`data/pipeline_run_summary.json`](data/pipeline_run_summary.json) — latest bundled pipeline status and output summary.

## Production boundary

The runtime design targets a persistent Linux host with two long-lived unprivileged services: `next start` and `python analytics/runtime_worker.py`. A reverse proxy should enforce HTTPS, an upload limit no larger than the application limit, request and rate limits, and a private network or IP allowlist for trusted-internal decision routes.

The current secret-header mechanism is not a complete authentication or authorization system. Public exposure requires real identity, authentication, authorization, audit, secret management, retention, backup, monitoring, and incident-response controls. A production deployment also requires official and timely surveillance data, validated facility and inventory data, local calibration, epidemiological review, hospital and public-health approval, and institution-owned action thresholds.

## Documentation

- [`docs/DOCUMENTATION.md`](docs/DOCUMENTATION.md) — comprehensive technical and user documentation.
- [`docs/METHODOLOGY_SUMMARY.md`](docs/METHODOLOGY_SUMMARY.md) — concise methods and formulas.
- [`docs/ASSUMPTIONS_AND_LIMITATIONS.md`](docs/ASSUMPTIONS_AND_LIMITATIONS.md) — assumptions, evidence boundaries, and known limitations.
- [`docs/ETHICS_STATEMENT.md`](docs/ETHICS_STATEMENT.md) — ethical commitments and safety constraints.
- [`docs/PHASE_ROADMAP.md`](docs/PHASE_ROADMAP.md) — implementation and validation roadmap.
- [`analytics/README.md`](analytics/README.md) — stage-level analytics notes and artifact behavior.
- [`data/README.md`](data/README.md) — input and output data reference.

## Product ownership

DengueOps AI is a research, forecasting, and preparedness decision-support product developed and owned by Research and Management Consultants Ltd. (RMCL).

---

For research and educational demonstration only. Human review is required for every output. Do not use this prototype for clinical care, automated public-health action, or operational resource allocation without validated data and institutional oversight.

