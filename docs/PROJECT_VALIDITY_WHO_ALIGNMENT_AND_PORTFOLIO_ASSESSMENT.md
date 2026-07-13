# Project Validity, WHO Alignment, Formula Evidence, and Portfolio Assessment

## Executive conclusion

DengueOps AI is a technically functioning, governed research prototype with a complete synthetic capability-demonstration workflow. It is broadly following the planned remediation sequence through P0.4, while P1.1 and later validation work remain incomplete.

The project must not currently be described as WHO-compliant, WHO-approved, locally calibrated, epidemiologically validated, hospital-approved, or authorized for operational public-health decision-making.

The formulas and algorithms are real executable calculations. Many are implementation-tested and traceable through the formula registry. That does not mean all project-specific feature choices, model assumptions, thresholds, or operational formulas have been scientifically proven for Dhaka.

As a student portfolio project, it is strong because it demonstrates responsible machine-learning engineering, governance, provenance, validation controls, explainability, and honest limitation management—not merely model fitting and dashboard presentation.

## 1. Progress against the project plan

The project has substantially implemented:

- P0.3A formula governance and safer analytical terminology.
- P0.3C evidence registry, deployment profiles, model card, and governance provenance.
- P0.4 real run-specific model diagnostics generated from a fitted validation estimator.
- An end-to-end synthetic demonstration covering data input, validation, prediction, preparedness analysis, and simulated notification.
- Formula, deployment-profile, evidence-registry, model-card, and artifact provenance controls.
- Explicit `benchmark_only` restrictions and prohibited-use statements.
- Separation of the chronological validation estimator from the separately fitted final forecast estimator.
- Non-causal explainability wording and stale-artifact prevention.

Important work still outstanding includes:

- P1.1 expanding-window or rolling-origin backtesting.
- Repeated evaluation across forecast origins and seasons.
- Real Dhaka surveillance and meteorological validation.
- Reporting-delay and revised-data simulation.
- Calibrated uncertainty.
- External validation.
- Privacy, cybersecurity, equity, and operational-risk assessment.
- Institutional and public-health authority review.
- Prospective shadow validation.

The current primary validation remains one chronological 80/20 holdout. It is a genuine development evaluation, but it is not sufficient evidence of stable real-world performance.

## 2. WHO alignment and compliance status

WHO does not provide a general software status that can safely be claimed simply as “WHO compliant.” WHO publishes ethical guidance, governance principles, regulatory considerations, and dengue early-warning guidance. Actual authorization depends on the applicable national authorities, legal requirements, data controllers, health institutions, and intended operational use.

Relevant WHO resources include:

- [Ethics and governance of artificial intelligence for health](https://www.who.int/publications/b/58847)
- [Regulatory considerations on artificial intelligence for health](https://www.who.int/publications/i/item/9789240078871)
- [Operational guide using the web-based Early Warning and Response System for dengue outbreaks](https://www.who.int/publications/i/item/9789240003750)

### Areas of design-level alignment

The project currently supports several WHO-aligned governance principles:

- Intended and prohibited uses are documented.
- Human decision-making is not replaced by autonomous clinical action.
- Notifications are explicitly simulated.
- Synthetic and observed data modes are distinguished.
- Model and formula limitations are exposed.
- Formula, profile, model, and artifact versions are traceable.
- Run artifacts share provenance identities and hashes.
- Feature diagnostics are described as non-causal.
- Institutional approval and scientific evidence are not invented.
- Governance conflicts fail explicitly.
- Clinical and official public-health use are prohibited.

### Missing evidence and assurance

The project has not demonstrated:

- Safety and effectiveness on authorized real data.
- External or independent validation.
- Representative performance or equity across affected populations.
- Bangladesh-specific legal and regulatory compliance.
- Privacy-impact and cybersecurity assessments.
- Consent, retention, access-control, and data-governance procedures for real health data.
- Institutional accountability, review, or mechanisms for challenge and redress.
- Performance monitoring during actual use.
- Robustness to reporting delays, missing reports, and revised surveillance records.
- Formal conformity with the complete WHO EWARS methodology.
- Review involving the intended public-health professionals and institutions.

The safe claim is:

> The prototype was designed with selected WHO AI governance principles in mind, including transparency, human oversight, intended-use restrictions, provenance, and explicit limitations. It has not been assessed, certified, endorsed, or approved by WHO and is not authorized for operational public-health use.

## 3. Why the project is not operationally valid

Operational validity means considerably more than having working code and a fitted model. It requires evidence that the entire system performs safely and usefully under the conditions in which real decisions will be made.

The project is not operationally valid because:

1. **Its current data are synthetic.** The model has not established performance on authorized Dhaka surveillance data.
2. **Local calibration is absent.** Feature lags, model behavior, hospital assumptions, inventory assumptions, and decision thresholds have not been estimated or confirmed locally.
3. **Validation is limited.** The current one-holdout evaluation does not establish temporal, seasonal, surge-period, or reporting-vintage stability.
4. **Uncertainty is uncalibrated.** The RMSE sensitivity band is not a calibrated probabilistic prediction interval.
5. **Operational formulas lack institutional validation.** Preparedness, bed, inventory, priority, and directive rules require local administrative data and domain review.
6. **No external validation exists.** Results have not been reproduced on an independent dataset or by an independent evaluator.
7. **No prospective shadow validation exists.** The project has not been run alongside real operations without affecting decisions to compare its outputs with subsequent outcomes.
8. **No institutional approval exists.** Hospitals, surveillance authorities, and public-health decision owners have not approved its use.
9. **Real-data governance is incomplete.** Privacy, security, access control, retention, auditing, and incident-response controls remain outside the current prototype.
10. **Human workflow safety is untested.** The way users interpret, challenge, override, and act on outputs has not been evaluated.

## 4. Will the project become operationally valid after P1.4?

No—not automatically.

P1.1 through P1.4 can make the project a stronger and more reproducible research prototype:

- P1.1 can provide repeated temporal backtesting.
- P1.2 can improve uncertainty evaluation if implemented as planned.
- P1.3 can strengthen data contracts and quality gates.
- P1.4 can strengthen automated tests and continuous integration.

These phases improve technical assurance. They do not supply real Dhaka evidence, institutional authorization, legal compliance, or prospective operational validation.

After P1.4, an accurate maturity statement would be:

> A more rigorously tested, reproducible, and governed research prototype ready for evaluation with authorized real data.

Operational validity would still require a later pathway such as:

1. Obtain authorized, well-governed historical surveillance and meteorological data.
2. Define reporting-vintage, missing-data, correction, and latency policies.
3. Re-estimate or validate locally dependent features and parameters.
4. Perform repeated temporal evaluation on real data.
5. Retain a genuinely untouched external evaluation period or dataset.
6. Validate hospital and inventory formulas with the responsible institutions.
7. Conduct privacy, security, equity, usability, and operational-risk assessments.
8. Run prospective shadow validation without allowing the system to control decisions.
9. Obtain epidemiological, institutional, legal, and public-health authority review.
10. Introduce monitored, human-controlled deployment only if the evidence and approvals support it.

Even after those steps, authorization would be limited to a defined version, geography, intended use, data contract, and operating procedure. It would not prove universal validity.

## 5. Are the formulas real?

Yes, in the software sense: they are executable calculations used by the pipeline. Predictions and preparedness outputs are not merely static dashboard placeholders.

However, “real” and “proven” are different claims.

### Implementation-verifiable calculations

These can be verified against their declared mathematical or algorithmic behavior:

- MAE, RMSE, and positive-actual MAPE.
- Case and climate lags.
- Shifted rolling means.
- Growth calculations.
- Cyclic week encoding.
- Naive and moving-average baselines.
- Gradient Boosting training and prediction.
- Native tree feature importance.
- Holdout permutation importance.
- Provenance and deterministic hashing.

Passing tests for these calculations establishes that the code implements the declared behavior. It does not establish dengue-specific predictive validity.

### Research-candidate choices

The following are genuine model choices but are not yet proven for Dhaka:

- The selected 2- and 4-week climate lags.
- The case-lag and rolling-window selections.
- The 18-feature set.
- Growth-feature definitions.
- The fixed Gradient Boosting configuration.
- The two-week forecast design as implemented for this deployment profile.

These require repeated local temporal evaluation and external review before promotion.

### Benchmark-only or operational assumptions

The least validated parts include:

- Provisional seasonal flags.
- Hospital preparedness and bed-demand assumptions.
- Inventory consumption and depletion calculations.
- Priority tiers.
- Directive and escalation rules.
- Resource-allocation suggestions.

These may be legitimate prototype formulas, but they are not established clinical protocols or approved public-health rules.

The evidence registry is intentionally empty. Consequently, the project currently has no registered scientific evidence records, Dhaka validation evidence, or institutional approval records supporting formula promotion. This is an honest governance state—not proof that the formulas are false, but proof that their external support has not yet been established in the system.

The correct claim is:

> The formulas are versioned, traceable, executable, and tested for software consistency. Their scientific applicability, local calibration, and operational suitability have not yet been established as a complete system.

## 6. Is the fitted model genuine?

Yes. The project genuinely:

- Generates the canonical 18 features from input data.
- Fits a `GradientBoostingRegressor`.
- Generates predictions from that fitted estimator.
- Compares the model with two computed baselines.
- Produces native importance from the fitted validation estimator.
- Computes permutation importance using unseen chronological-holdout rows.
- Records the estimator role, parameters, versions, and provenance.
- Distinguishes the explained validation estimator from the separately fitted final forecast estimator.

This proves that the ML pipeline is technically real. It does not prove that the learned synthetic relationships transfer to real dengue surveillance.

## 7. Student portfolio assessment

The project is portfolio-worthy because it demonstrates:

- Full-stack data-product integration.
- Time-series feature engineering.
- Reproducible synthetic benchmarks.
- Model and baseline evaluation.
- Run-specific non-causal explainability.
- JSON Schema validation.
- Provenance and exact-byte artifact hashing.
- Formula and deployment governance.
- Evidence and approval separation.
- Fail-closed validation behavior.
- TypeScript data contracts.
- Awareness of public-health risk and responsible claims.

A strong portfolio description is:

> I built a governed public-health forecasting research prototype that demonstrates a reproducible end-to-end workflow using deterministic synthetic data. It includes temporal validation, baseline comparison, run-specific model diagnostics, deployment restrictions, formula governance, model cards, and cross-artifact provenance. The system explicitly prevents benchmark results from being represented as locally validated operational advice.

Avoid claims such as:

- “WHO-compliant dengue prediction system.”
- “WHO-approved.”
- “Accurately predicts dengue in Dhaka.”
- “Hospital-ready.”
- “Clinically proven formulas.”
- “Epidemiologically validated.”
- “Feature importance identifies the causes of dengue.”

## 8. Final status table

| Question | Current answer |
|---|---|
| Is the project following the plan? | Broadly yes through P0.4; P1.1 and later assurance phases remain incomplete. |
| Is it WHO-compliant? | No demonstrated or certifiable WHO compliance; it has partial design-level alignment with selected principles. |
| Is it WHO-approved? | No. |
| Are the formulas real? | Yes, as executable and testable software calculations. |
| Are all formulas scientifically proven for Dhaka? | No. |
| Is the fitted model genuine? | Yes, but it currently learns from synthetic benchmark data. |
| Is it operationally valid? | No. |
| Will P1.4 alone make it operationally valid? | No; it will improve technical assurance and readiness for real-data evaluation. |
| Is it portfolio-worthy? | Yes, especially as a responsible-ML and governed analytics project. |

## 9. Recommended next milestone

Implement P1.1 expanding-window validation without changing the model or features. Then complete the remaining technical-assurance phases before seeking authorized real data, local calibration, institutional review, and prospective shadow validation.

The project’s strongest quality is that it makes the boundary between demonstrated technical capability and unproven real-world validity explicit.
