# P0.3B — Scientific Evidence Requirements and Local Calibration Specification

- Status: Inspection complete
- Implementation status: Not started
- Current deployment gate: benchmark_only
- Evidence status: Evidence requirements defined; sources not yet populated
- Scope: Dhaka first operational calibration site, reusable multi-location engine
- Generated from: P0.3B repository inspection

## 1. Registry Status Review

The formula registry and deployment-gate enforcement currently divide formulas into deployment-safe mathematical primitives, provisional project choices, unsupported operational heuristics, and benchmark-only rules.

Current registry posture by formula group:

- Standard algorithmic items are limited to the core arithmetic and estimator mechanics that the codebase already executes.
- Project-specific choices such as feature lags, rolling windows, target horizon, and model-selection policy remain design choices that require local evidence before they can advance.
- Operational rules for exposure, anomaly adjustment, planning priority, uncertainty framing, admission fraction, bed demand, SDH, directives, and thresholds remain provisional or institution-configured.
- Synthetic benchmark assumptions remain isolated and benchmark-only.

For every registered formula, the required advancement logic is the same:

- `benchmark_only` formulas may support internal testing and synthetic scenario validation only.
- `research_candidate` formulas may support methodological comparison but not operational use.
- `locally_backtested` requires local evaluation against Dhaka surveillance, hospital, or inventory data as appropriate.
- `expert_reviewed` requires documented subject-matter approval.
- `institution_approved` requires explicit institutional sign-off and policy traceability.
- `shadow_validated` requires prospective, no-action operation against live streams.
- `operational_advisory` requires all upstream evidence, review, and validation gates to be complete.

Exact evidence needed to advance each registry entry is determined by formula class:

- Mathematical primitives advance on implementation correctness and boundary tests.
- Empirical model choices advance on temporal validation, local calibration, and error analysis.
- Institution-configured parameters advance on documented policy or approval records.
- Synthetic benchmark rules never advance beyond benchmark use.

## 2. Evidence-Source Classification

Acceptable future evidence categories for the registry are:

- standard software/library documentation
- WHO or recognized international public-health guidance
- Bangladesh national surveillance or clinical guidance
- peer-reviewed systematic review or meta-analysis
- peer-reviewed dengue forecasting study
- Bangladesh-specific epidemiological study
- Dhaka-specific empirical analysis
- meteorological authority documentation
- hospital administrative data
- inventory and procurement records
- expert consensus
- institutional policy or escalation protocol
- prospective shadow-validation results

Formula families and their acceptable evidence classes:

- Forecast-model mathematics: standard library documentation for estimator behavior, plus peer-reviewed forecasting study and Dhaka-specific empirical analysis for selection.
- Climate features and lags: meteorological authority documentation, peer-reviewed study, and Dhaka-specific empirical analysis.
- Case-history features and lag structure: Bangladesh-specific epidemiological study and Dhaka-specific empirical analysis.
- Operational admission, LOS, and load allocation: hospital administrative data, institutional policy, expert consensus, and prospective shadow-validation.
- Inventory consumption, reorder thresholds, and depletion horizons: inventory and procurement records, institutional policy, and shadow-validation.
- Priority, directive, and escalation rules: institutional policy or escalation protocol, expert consensus, and shadow-validation.
- Synthetic benchmark rules: no external evidence qualifies them for operational deployment; they remain synthetic-only.

## 3. Forecast-Model Evidence Requirements

The current forecast model mixes standard estimator behavior with project-specific design choices.

Standard estimator behavior:

- `GradientBoostingRegressor` selection as a tree-ensemble forecasting baseline
- squared-error loss behavior
- tree splitting mechanics
- deterministic `random_state` handling

Project design choices requiring evidence or governance:

- hyperparameter values
- feature selection
- climate lag selection
- case lag selection
- rolling-window selection
- monsoon and post-monsoon indicators
- two-week horizon selection
- baseline model selection
- metric selection
- model-selection rule
- negative-prediction clipping
- retraining cadence
- minimum-history requirements
- missing-data policy
- reporting-delay handling

Evidence separation:

- Standard estimator behavior needs only software documentation and regression tests.
- Project design choices need local temporal validation, domain review, and in some cases institutional approval.
- Locally estimated choices must be derived from Dhaka data or future deployment data.
- Deployment governance choices must be approved before they can influence operational output.

## 4. Candidate Model Comparison Plan

Future model comparison should remain a controlled benchmark process. Candidate families:

- seasonal naive
- previous-week naive
- moving average
- regularized linear regression
- Poisson or negative-binomial regression where suitable
- Gradient Boosting
- Random Forest
- XGBoost or LightGBM only if dependency adoption is separately approved
- SARIMA/SARIMAX

Comparison dimensions:

- required data volume
- strengths
- limitations
- interpretability
- count-data suitability
- nonlinear suitability
- missing-data sensitivity
- retraining complexity
- deployment suitability

No winner is selected by this inspection. The repository should treat model-family choice as a future evaluation problem rather than a settled scientific claim.

## 5. Temporal Validation Specification

The current single holdout is insufficient for progression because it cannot distinguish:

- seasonal stability from chance alignment
- genuine forecast skill from leakage
- robustness across outbreak and non-outbreak periods
- stability under revised data

Recommended validation structure:

- expanding-window or rolling-origin evaluation
- forecast horizon fixed to the operational target
- step size chosen to preserve seasonal coverage
- folds spanning outbreak and non-outbreak periods
- tuning separated from final evaluation
- final untouched evaluation period retained for one-way confirmation
- reporting-lag simulation included in backtests
- revised-data handling defined explicitly
- minimum viable history specified before model fitting

The current one-shot 80/20 holdout is a development check, not a sufficient evidence base for advancement.

## 6. Performance Metrics

Metrics and their role:

- MAE: absolute error magnitude
- RMSE: penalizes larger misses more strongly
- MAPE: relative error, but unstable near zero
- WAPE: aggregate relative error measure
- MASE: scaled comparison to a naive baseline
- RMSLE where appropriate: dampens extreme count differences
- outbreak peak timing error: measures timing accuracy
- peak magnitude error: measures surge intensity accuracy
- outbreak onset sensitivity: measures early-detection success
- false alert rate: measures operational burden
- missed surge rate: measures public-health risk
- calibration or coverage metrics for intervals: measures uncertainty quality
- operational utility metrics: measures usefulness to hospital or public-health practice

Thresholds that must be defined before advancement:

- public-health acceptable error ranges
- alert burden tolerances
- operational trigger tolerances
- review cadence

Thresholds that require stakeholder approval:

- outbreak alert criteria
- escalation thresholds
- resource-allocation cutoffs

Thresholds that may be estimated from baseline performance:

- relative improvement over naive baselines
- error reduction versus current practice

## 7. Climate and Epidemiological Feature Plan

For each current environmental and temporal feature, local calibration must establish:

- scientific rationale
- lag range to test
- nonlinear transformation candidates
- interaction candidates
- multicollinearity concerns
- temporal availability
- meteorological source requirements
- spatial resolution requirements
- missingness policy
- local calibration requirement

Feature families:

- rainfall: likely candidate predictor, but local lag and transformation require evaluation
- temperature: likely candidate predictor, but effect shape and lag must be locally tested
- humidity: likely candidate predictor, but direction and magnitude require local evaluation
- seasonality: useful as a temporal control, not a causal claim
- case history: useful for autoregressive structure, but lag and window choices are empirical
- reporting delay: operationally important, but handling policy must be explicit

The key distinction is that literature identifies candidate signals while local temporal evaluation determines which lags and transforms remain in the deployed model.

## 8. Dhaka Data Requirements

Minimum data specification for first real deployment:

### Surveillance data

- weekly or daily case counts
- case-definition version
- report date
- onset date if available
- residence geography
- reporting facility
- revisions
- probable or confirmed status
- deaths
- severe dengue status if available
- age and sex aggregates if permitted

### Meteorological data

- rainfall
- minimum, maximum, and mean temperature
- humidity
- observation station or gridded source
- spatial coverage
- temporal completeness
- revision or version information

### Hospital data

- admissions
- dengue diagnosis
- admission and discharge dates
- occupancy
- dedicated and surge beds
- ICU or HDU indicators if relevant
- average length of stay
- referral patterns
- catchment information
- reporting completeness

### Inventory data

- item ID
- item definition
- stock on hand
- consumption
- receipts
- stock-outs
- reorder level
- lead time
- wastage or expiry
- unit of measure

For every field, the registry should record whether it is required or optional, its unit, temporal resolution, source owner, quality checks, privacy implications, and supported formula IDs.

## 9. Operational Parameter Estimation

Future estimation methods should be selected by parameter type:

- admission fraction: descriptive hospital statistics, regression analysis, or expert consensus
- average length of stay: descriptive hospital statistics or time-to-event analysis
- admission-to-bed-load conversion: regression analysis plus hospital review
- facility allocation weights: hospital operations data plus expert consensus
- catchment allocation: hospital utilization data and institutional review
- inventory consumption per patient: inventory history and procurement records
- item-specific demand elasticity: inventory history and regression analysis
- replenishment lead time: procurement records
- reorder thresholds: official policy or inventory history with approval
- bed escalation thresholds: institutional policy and clinical or operational approval
- priority and directive triggers: expert consensus, institutional policy, and prospective validation

No values are estimated in this phase.

## 10. Institutional Approval Matrix

Approval categories by function:

- epidemiological methods
- forecasting performance
- hospital operations
- bed escalation
- inventory thresholds
- procurement triggers
- vector-control recommendations
- public communication
- data governance
- cybersecurity
- clinical safety

Each formula or policy should record:

- technical reviewer
- operational reviewer
- institutional approver
- required documentation
- approval record needed
- expiration or review requirement

No current operational threshold should be treated as approved without this record.

## 11. Geographic Expansion Architecture

Formula portability classes:

- globally reusable mathematics
- reusable methodology
- locally re-estimated
- facility-specific
- institution-configured
- geography-specific
- benchmark-only

The onboarding sequence for a new site should be:

- establish data availability
- map local surveillance definitions
- map hospital and inventory sources
- select candidate features and lags
- estimate local parameters
- backtest on local history
- shadow-validate prospectively
- obtain institutional approval
- promote only after review

Dhaka coefficients must not be assumed valid for another city or country.

## 12. Deployment Profile Specification

Recommended profile structure:

```text
config/deployments/
    dhaka_south/
    future_location/
```

Each profile should define:

- geography
- timezone
- surveillance frequency
- case definition
- data sources
- feature candidates
- selected feature configuration
- model version
- training period
- validation results
- admission parameters
- LOS parameters
- hospital mappings
- inventory items
- thresholds
- approval records
- deployment gate
- effective dates
- review dates

Recommended validation rule set:

- profile schema must be versioned
- required fields must be present
- threshold provenance must be recorded
- approval references must be explicit
- benchmark-only profiles must not masquerade as operational profiles

## 13. Evidence Registry Design

Future evidence registry should link sources to formulas using fields such as:

- evidence_id
- title
- source_type
- issuing organization or journal
- publication year
- geography
- population
- study design
- variables
- findings summary
- formula_ids_supported
- applicability
- limitations
- local transferability
- verification status
- reviewed_by
- review_date
- document location
- citation identifier

The registry should remain empty until populated with real evidence. No invented references should be stored.

## 14. Model Card and Deployment Dossier

Required documents and their roles:

- model card: what the model is and is not
- data sheet: what data were used
- formula registry report: what formulas exist and how they are governed
- validation report: what performance was observed
- hospital calibration report: what local parameters were estimated
- institutional approval log: what was approved and when
- shadow-validation report: what happened in no-action deployment
- change-control log: what changed across versions

These documents map to deployment gates cumulatively, not independently.

## 15. Shadow-Validation Plan

Prospective Dhaka shadow deployment should specify:

- duration
- forecast frequency
- data freeze timing
- prediction timestamp
- comparison with later observed data
- hospital operational comparison
- alert logging
- human review
- no-action shadow status
- incident recording
- drift monitoring
- recalibration rules
- promotion criteria
- rollback criteria

No performance threshold is created here because stakeholder approval is required before promotion criteria are fixed.

## 16. Risk Analysis

Identified risks and controls:

- surveillance reporting delay: simulate delay, track lag distributions, and separate reporting from onset where possible
- revised historical data: version inputs and freeze evaluation snapshots
- under-reporting: document completeness and use sensitivity analyses
- changing case definitions: record version changes and re-baseline after definition shifts
- hospital-selection bias: document catchment and referral patterns
- missing meteorological observations: define imputation or exclusion rules
- spatial mismatch: align geographic resolution before modeling
- concept drift: monitor residuals and recalibrate periodically
- outbreak rarity: preserve non-outbreak periods and avoid overfitting
- extreme extrapolation: cap unsupported extrapolation and flag out-of-domain use
- data leakage: separate feature availability from outcome timing
- target leakage: prevent current-week or future-week contamination
- model instability: use deterministic training settings and repeated validation
- automation bias: require human review for operational use
- false reassurance: avoid overclaiming certainty or validation
- excessive alerts: monitor alert burden and threshold churn
- institutional misuse: restrict operational labeling until approval
- cross-country parameter transfer: require local re-estimation and local approval

## 17. Smallest Safe Next Implementation

Recommended next phase: P0.3C evidence registry and deployment profile schemas.

Likely files to create:

- `config/evidence_registry.schema.json`
- `config/deployment_profile.schema.json`
- `config/model_card.schema.json`
- `config/evidence_registry.json`
- `config/deployments/dhaka_south/profile.json`
- `analytics/evidence_registry.py`
- `analytics/deployment_profiles.py`
- `tests/test_evidence_registry.py`
- `tests/test_deployment_profiles.py`
- `tests/test_model_card_schema.py`
- `tests/test_formula_evidence_links.py`

Likely files to modify in the next phase:

- `analytics/formula_registry.py`
- `analytics/run_pipeline.py`
- generated artifact writers that need registry/profile hashes
- scoped documentation that describes the governance model

This phase should not introduce new coefficients or operational claims.

## 18. Final Verdict

What can advance using published evidence:

- standard estimator mechanics
- general metric definitions
- generic temporal-validation structure
- general model-comparison methodology

What must use Dhaka data:

- feature lag selection
- rolling-window selection
- rainfall, temperature, and humidity calibration
- case-history window selection
- reporting-delay handling
- model performance on local data

What must use hospital data:

- admission fraction
- LOS
- bed-demand conversion
- bed escalation thresholds
- facility allocation
- operational trigger design

What requires institutional approval:

- thresholds
- escalation logic
- directives
- public-facing language about risk or priority
- any operational advisory label

What requires prospective shadow validation:

- promotion from candidate to operational use
- alerting behavior
- threshold stability
- human workflow fit

Which formulas can be reused globally:

- mathematical primitives
- standard ML estimator behavior
- basic arithmetic transformations
- generic validation mechanics

Which formulas must be recalibrated for every deployment:

- operational thresholds
- local lag structure
- admission and LOS parameters
- facility allocation logic
- inventory demand assumptions

Which fields should remain benchmark-only:

- all synthetic benchmark coefficients and assumptions
- all benchmark-specific scenarios and metadata
- any unsupported proxy for operational policy

## Decision Record

- Published evidence will support candidate selection and methodological rationale.
- Dhaka surveillance and meteorological data will be used for local model calibration.
- Hospital and inventory records will be used for operational parameter estimation.
- Institution-configured thresholds require documented approval.
- Dhaka parameters must not automatically transfer to another geography.
- Synthetic benchmark coefficients remain benchmark-only.
- No formula advances to operational use without its required evidence, validation, and approval.

## Next Approved Phase

P0.3C — Evidence Registry and Deployment Profile Schemas
