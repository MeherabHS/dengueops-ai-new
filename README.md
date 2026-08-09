# DengueOps AI

DengueOps AI is a governed dengue forecasting and preparedness research platform for Dhaka South. It combines a Next.js application with a separately supervised Python analytics worker, immutable runtime evidence, model lifecycle controls, Community-facing read APIs, and protected vector-surveillance intake.

> [!CAUTION]
> DengueOps AI is a research and capability-demonstration system. The bundled Dhaka South profile uses deterministic synthetic data. It is not locally calibrated, epidemiologically validated, hospital-approved, or authorized for clinical care, official public-health action, or automatic resource allocation.

## What is included

- A two-week dengue case forecasting workflow.
- CSV validation in isolated runtime workspaces.
- Governed comparison of 11 frozen candidate models.
- Immutable assessment, decision, authorization, forecast, monitoring, degradation, and lifecycle evidence.
- Exact-current runtime authority with hash-bound commits and pointers.
- Operational preparedness and hospital-inventory projections.
- Super User authentication and protected operational routes.
- Scoped Community read and vector-submit APIs.
- Raster-only vector image intake with bounded storage outside `public/`.
- A file-backed queue consumed by exactly one long-lived analytics worker.
- A PM2 ecosystem definition for independently supervised web and worker processes.

## System boundary

The product separates bundled demonstration evidence from mutable runtime evidence:

```text
Governed policies and schemas
          |
          +--> Bundled synthetic pipeline --> data/ --> public dashboard
          |
          +--> Runtime API --> isolated workspace / file-backed queue
                                  |
                                  v
                         Python runtime worker
                                  |
                                  v
                    immutable commits and latest pointers
                                  |
                                  +--> Super User workflows
                                  +--> curated Community read model
```

The browser never chooses model parameters, filesystem paths, authority hashes, or deployment policy. Runtime jobs become current only after their artifacts and commit bindings pass verification.

## Technology

| Layer | Stack |
| --- | --- |
| Web | Next.js 16.2.6 App Router, React 19.2, TypeScript 5 |
| UI | Tailwind CSS 4, Recharts 3, Lucide React |
| Analytics | Python, NumPy, pandas, SciPy, scikit-learn, statsmodels |
| Validation | JSON Schema Draft 2020-12, Python `unittest`, Node test runner |
| Runtime storage | File-backed workspaces, queues, immutable evidence, atomic pointers |
| Production supervision | PM2 with separate web and runtime-worker processes |

## Requirements

- Node.js 20.9 or newer
- npm
- Python 3.13 for the release-tested environment
- A Python virtual environment

Install the dependencies:

```bash
npm ci
python -m venv .venv
```

Activate the virtual environment and install Python packages:

```bash
# Linux
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Configuration

Keep local values in an ignored `.env.local`. Production values must be supplied through a restrictive server-side environment or secret store. Never commit credentials.

### Required operational values

| Variable | Requirement |
| --- | --- |
| `DENGUEOPS_RUNTIME_ROOT` | Absolute path outside the governed `data/` tree |
| `DENGUEOPS_PYTHON_EXECUTABLE` | Absolute path to the approved virtual-environment interpreter; no PATH fallback |
| `PYTHONDONTWRITEBYTECODE` | Set to `1` for runtime and release execution |
| `DENGUEOPS_SUPER_USER_USERNAME` | Super User sign-in name |
| `DENGUEOPS_SUPER_USER_PASSWORD_HASH` | Governed scrypt hash, never a plaintext password |
| `DENGUEOPS_SESSION_SECRET` | Random secret of at least 32 characters |
| `DENGUEOPS_COMMUNITY_READ_API_KEY` | Community read credential of at least 16 characters |
| `DENGUEOPS_VECTOR_SUBMIT_API_KEY` | Distinct vector-submit credential of at least 16 characters |
| `DENGUEOPS_COMMUNITY_UPLOAD_ROOT` | Absolute private upload path outside `public/` |

The Community credentials must be different. Identical, missing, or undersized keys fail closed.

### Optional runtime controls

| Variable | Default | Purpose |
| --- | ---: | --- |
| `DENGUEOPS_DEFAULT_DEPLOYMENT_ID` | `dhaka_south` | Active deployment |
| `DENGUEOPS_MAX_UPLOAD_BYTES` | `10485760` | Maximum bytes per CSV |
| `DENGUEOPS_VECTOR_IMAGE_MAX_BYTES` | `8388608` | Maximum vector image bytes |
| `DENGUEOPS_VALIDATION_TIMEOUT_MS` | `60000` | CSV validation timeout |
| `DENGUEOPS_QUICK_FORECAST_TIMEOUT_SECONDS` | `600` | Quick Forecast timeout |
| `DENGUEOPS_ASSESSMENT_TIMEOUT_SECONDS` | `1800` | Assessment timeout |
| `DENGUEOPS_APPROVED_FORECAST_TIMEOUT_SECONDS` | `600` | Approved forecast timeout |
| `DENGUEOPS_FORECAST_OUTCOME_TIMEOUT_SECONDS` | `120` | Outcome-processing timeout |
| `DENGUEOPS_WORKSPACE_MAX_AGE_SECONDS` | `86400` | Maximum accepted workspace age |
| `DENGUEOPS_DECISION_VALIDITY_SECONDS` | `2592000` | Assessment decision validity |
| `DENGUEOPS_DECISION_REASON_MAX_LENGTH` | `1000` | Maximum decision-reason length |

Internal decision, monitoring, and lifecycle ingress are disabled by default. When enabled, each requires a distinct server-only credential of at least 16 characters and a bounded operator identifier:

- `DENGUEOPS_INTERNAL_DECISION_ENABLED`
- `DENGUEOPS_INTERNAL_DECISION_SECRET`
- `DENGUEOPS_INTERNAL_OPERATOR_ID`
- `DENGUEOPS_INTERNAL_MONITORING_ENABLED`
- `DENGUEOPS_INTERNAL_MONITORING_SECRET`
- `DENGUEOPS_INTERNAL_MONITORING_OPERATOR_ID`
- `DENGUEOPS_INTERNAL_MODEL_LIFECYCLE_ENABLED`
- `DENGUEOPS_INTERNAL_MODEL_LIFECYCLE_SECRET`
- `DENGUEOPS_INTERNAL_MODEL_LIFECYCLE_OPERATOR_ID`

## Run locally

The web application and analytics worker are separate processes and must share the same runtime root.

PowerShell:

```powershell
New-Item -ItemType Directory -Force -Path '.\runtime' | Out-Null
$env:DENGUEOPS_RUNTIME_ROOT = (Resolve-Path '.\runtime')
$env:DENGUEOPS_PYTHON_EXECUTABLE = (Resolve-Path '.\.venv\Scripts\python.exe')
$env:PYTHONDONTWRITEBYTECODE = '1'

# Terminal 1
npm run dev

# Terminal 2
npm run runtime:worker
```

Linux:

```bash
mkdir -p runtime
export DENGUEOPS_RUNTIME_ROOT="$(pwd)/runtime"
export DENGUEOPS_PYTHON_EXECUTABLE="$(pwd)/.venv/bin/python"
export PYTHONDONTWRITEBYTECODE=1

# Terminal 1
npm run dev

# Terminal 2
npm run runtime:worker
```

Open [http://localhost:3000](http://localhost:3000).

The launcher refuses missing or relative Python paths. For a bounded development check that consumes at most one queued job:

```bash
"$DENGUEOPS_PYTHON_EXECUTABLE" analytics/runtime_worker.py --once
```

## Main workflows

### Quick Forecast

Validates an uploaded dengue/climate dataset against the current deployment and model authority, then queues a governed forecast. The web layer publishes no result until the worker commits an internally consistent artifact set.

### Dataset Assessment

Evaluates every current registry candidate on one precommitted rolling-origin plan. The current registry contains two comparison baselines and nine selectable learned models. Assessment evidence does not change the active model by itself.

### Decision and approved forecast

A Super User or explicitly enabled trusted service may record a bounded decision against a committed assessment. An approval reserves a one-run authorization; it does not silently adopt a deployment-wide model.

### Monitoring, degradation, and lifecycle

Observed outcomes, monitoring summaries, degradation evidence, and lifecycle decisions are stored as separate immutable evidence families. Current pointers are version-aware and fail closed on tampering or stale authority.

### Operational preparedness

Preparedness publication binds the current forecast, governed formulas, hospital inventory, and planning policy. Qualification preparedness and current operational preparedness remain distinct.

### Community and vector surveillance

- Community read access uses a dedicated bearer credential.
- Vector submission uses a different bearer credential and a lower rate limit.
- JPEG, PNG, and WebP are accepted only when MIME and magic bytes agree.
- SVG and arbitrary bytes are rejected.
- Uploads use server-generated UUID paths, bounded metadata, `0700` directories, and `0600` files.
- Images remain outside `public/` and are retrieved only through an authenticated, `nosniff` response.

## Routes

| Route | Access | Purpose |
| --- | --- | --- |
| `/` | Public | Project overview |
| `/dashboard` | Public curated view | Latest verified operational summary |
| `/forecast` | Super User | Upload, Quick Forecast, assessment, and approval workflow |
| `/validation` | Super User | Validation, comparison, monitoring, and lifecycle evidence |
| `/vector-surveillance` | Super User | Protected vector submission review |
| `/preparedness` | Public curated view | Preparedness presentation |
| `/methodology` | Public | Methods and governance |
| `/assumptions` | Public | Assumptions and limitations |
| `/ethics` | Public | Responsible-use boundaries |
| `/sign-in` | Public | Super User authentication |

Versioned integration endpoints:

| Method and route | Credential | Purpose |
| --- | --- | --- |
| `GET /api/community/v1/current` | Community read bearer | Curated current forecast and preparedness |
| `POST /api/community/v1/vector-submissions` | Vector-submit bearer | Raster evidence intake |
| `GET /api/vector-surveillance/submissions` | Super User session | Protected submission listing |
| `GET /api/vector-surveillance/submissions/:id/image` | Super User session | Protected image retrieval |

Runtime mutation routes require a valid Super User session and same-origin request unless an explicitly enabled, distinct trusted-service credential applies.

## Tests and release checks

Python regression:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
py -3.13 -m unittest discover -s tests -p "test_*.py"
```

Focused route tests:

```bash
npm run test:runtime-routes
```

Type, lint, and production build:

```bash
npx tsc --noEmit
npm run lint
npm run build
```

The complete Node regression contains server-only and general test partitions. Run the four server-only files with the React Server condition:

```bash
node --conditions=react-server --import=tsx --test --test-concurrency=1 \
  tests/product_v2_cross_version_routing.test.mjs \
  tests/runtime_active_model_resolver.test.mjs \
  tests/runtime_degradation_cross_version.test.mjs \
  tests/request_body_security.test.mjs
```

Run every other `tests/*.test.mjs` file serially with `node --import=tsx --test --test-concurrency=1`. Do not apply the React Server condition globally because several client contracts intentionally run without it.

## Production with PM2

Production requires two independently supervised processes:

1. `dengueops-web`
2. `dengueops-runtime-worker`

The committed [`ecosystem.config.cjs`](ecosystem.config.cjs) pins each process to one PM2 fork instance, enables restart supervision, binds Next.js to `127.0.0.1`, and passes the explicit Python/runtime environment to the worker.

Before starting PM2:

```bash
export DENGUEOPS_PYTHON_EXECUTABLE=/absolute/path/to/venv/bin/python
export DENGUEOPS_RUNTIME_ROOT=/absolute/private/runtime/path
export DENGUEOPS_COMMUNITY_UPLOAD_ROOT=/absolute/private/upload/path
export DENGUEOPS_WEB_PORT=3000

"$DENGUEOPS_PYTHON_EXECUTABLE" -c "import numpy, pandas, scipy, sklearn, statsmodels, jsonschema"
npm ci
npm run build
pm2 start ecosystem.config.cjs
pm2 status
pm2 save
```

Inspect the existing PM2 owner and installation before configuring startup. Review the command produced by `pm2 startup` before running it with elevated privileges. On a multi-site server, do not change global firewall, SSH, Fail2ban, aaPanel, OpenResty, or Nginx settings until unrelated services and ownership are understood.

Production acceptance requires evidence that:

- one web process and one worker are online without an SSH session;
- the worker auto-restarts after a controlled crash and does not crash-loop;
- PM2 restores both processes after reboot or its startup integration is structurally verified;
- the internal Node port is reachable only through the reverse proxy;
- runtime and upload roots are owned by the service user and are not world-writable;
- the selected virtual environment imports all required analytics dependencies;
- the idle worker does not hold `analytics.lock`;
- logs are bounded and contain no credentials;
- TLS, proxy limits, rollback, current runtime authority, Community API, and vector upload all pass production smoke tests.

Passing tests and `next build` alone does not make the deployment production-ready.

## Security model

- Super User passwords are verified with the configured scrypt contract.
- Sessions are HMAC-signed and use Secure, HttpOnly, SameSite=Strict cookies in production.
- Mutations enforce same-origin checks where browser sessions apply.
- Authentication and API credentials fail closed; there is no development fallback.
- Credential comparisons are timing-safe.
- Sign-in and Community APIs apply bounded in-memory rate limits; production should add reverse-proxy limits.
- JSON and multipart bodies are read through application-level bounded readers.
- Security headers include CSP, nosniff, Referrer-Policy, Permissions-Policy, frame protection, and production HSTS.
- Runtime and upload paths are containment-checked and kept outside public assets.
- Public errors are sanitized and correlation identifiers do not reveal credentials or filesystem paths.

## Repository layout

```text
app/                  Next.js pages and route handlers
components/           Dashboard and workflow UI
lib/auth/             Super User credentials, sessions, and authorization
lib/community/        Scoped API authentication and vector storage
lib/http/             Bounded request-body handling
lib/runtime/          Runtime contracts, readers, stores, and authority resolution
analytics/            Governed pipeline stages and long-lived worker
config/               Schemas, registries, policies, and deployment configuration
data/                 Bundled synthetic evidence and dashboard artifacts
scripts/              Process launchers
tests/                Python and Node regression suites
docs/                 Technical, methodological, ethics, and planning documents
```

## Documentation

- [Technical documentation](docs/DOCUMENTATION.md)
- [Methodology summary](docs/METHODOLOGY_SUMMARY.md)
- [Assumptions and limitations](docs/ASSUMPTIONS_AND_LIMITATIONS.md)
- [Ethics statement](docs/ETHICS_STATEMENT.md)
- [Analytics pipeline reference](analytics/README.md)
- [Data reference](data/README.md)

## Ownership and responsible use

DengueOps AI is developed and owned by Research and Management Consultants Ltd. (RMCL).

Human review is required for every output. Do not use this repository for patient-level diagnosis, automated clinical decisions, official public-health action, or real-world resource allocation without authorized data, local validation, institutional governance, and accountable operational approval.
