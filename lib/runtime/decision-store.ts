import { createHash, randomUUID } from "node:crypto";
import {
  chmod,
  lstat,
  mkdir,
  open,
  readFile,
  readdir,
  rename,
  rm,
} from "node:fs/promises";
import path from "node:path";
import type { RuntimeConfig } from "./config";
import { loadDecisionPolicy } from "./decision-policy";
import { RuntimePublicError } from "./errors";
import {
  assessmentDecisionPaths,
  assessmentPaths,
  authorizationPaths,
  decisionPaths,
  runtimeCollectionPaths,
} from "./paths";
import { writeJsonAtomic } from "./store";

const sha256 = (value: Buffer) =>
  createHash("sha256").update(value).digest("hex");
const now = () => new Date().toISOString();
const DEPLOYABLE = new Set([
  "ridge_regression",
  "poisson_regression",
  "random_forest",
  "gradient_boosting",
]);
export type DecisionChoice =
  | "approve_technical_winner"
  | "keep_current_model"
  | "defer"
  | "reject_assessment";

async function jsonBytes(
  file: string,
): Promise<{ bytes: Buffer; value: Record<string, any> }> {
  const bytes = await readFile(file);
  return { bytes, value: JSON.parse(bytes.toString("utf8")) };
}
async function acquire(file: string): Promise<ReturnType<typeof open>> {
  await mkdir(path.dirname(file), { recursive: true, mode: 0o700 });
  try {
    return await open(file, "wx", 0o600);
  } catch {
    throw new RuntimePublicError(
      "decision_locked",
      "storage",
      "Another model-use decision is being recorded.",
      409,
      true,
    );
  }
}
async function immutableDirectory(root: string): Promise<void> {
  if (process.platform === "win32") return;
  const files = [
    path.join(root, "decision.json"),
    path.join(root, "commit.json"),
    path.join(root, "authorization.json"),
  ];
  for (const file of files) await chmod(file, 0o444).catch(() => undefined);
  await chmod(root, 0o555).catch(() => undefined);
}

export async function readVerifiedAssessment(
  config: RuntimeConfig,
  assessmentId: string,
  expectedSummary?: string,
) {
  const root = assessmentPaths(config.runtimeRoot, assessmentId).committed;
  const stat = await lstat(root).catch(() => null);
  if (!stat?.isDirectory() || stat.isSymbolicLink())
    throw new RuntimePublicError(
      "assessment_not_found",
      "validation",
      "The committed assessment was not found.",
      404,
    );
  const commitFile = await jsonBytes(
    path.join(root, "metadata", "commit.json"),
  );
  const commit = commitFile.value;
  if (
    commit.status !== "committed" ||
    commit.assessmentId !== assessmentId ||
    commit.latestPointerUpdated !== false
  )
    throw new RuntimePublicError(
      "assessment_integrity_error",
      "storage",
      "The committed assessment failed integrity verification.",
      409,
    );
  const artifacts: Record<string, Buffer> = {};
  for (const [name, digest] of Object.entries(
    commit.artifactHashes as Record<string, string>,
  )) {
    const bytes = await readFile(path.join(root, "artifacts", name));
    if (sha256(bytes) !== digest)
      throw new RuntimePublicError(
        "assessment_integrity_error",
        "storage",
        "The committed assessment artifact hashes do not match.",
        409,
      );
    artifacts[name] = bytes;
  }
  const summaryHash = sha256(artifacts["assessment_summary.json"]);
  if (expectedSummary && expectedSummary !== summaryHash)
    throw new RuntimePublicError(
      "assessment_summary_changed",
      "validation",
      "The assessment summary differs from the reviewed evidence.",
      409,
    );
  const summary = JSON.parse(
    artifacts["assessment_summary.json"].toString("utf8"),
  );
  const comparison = JSON.parse(
    artifacts["candidate_model_comparison.json"].toString("utf8"),
  );
  const rolling = JSON.parse(
    artifacts["rolling_validation.json"].toString("utf8"),
  );
  const recommendation = JSON.parse(
    artifacts["recommendation.json"].toString("utf8"),
  );
  if (
    summary.evidenceHashes?.candidateComparisonSha256 !==
      sha256(artifacts["candidate_model_comparison.json"]) ||
    summary.evidenceHashes?.rollingValidationSha256 !==
      sha256(artifacts["rolling_validation.json"]) ||
    summary.evidenceHashes?.recommendationSha256 !==
      sha256(artifacts["recommendation.json"]) ||
    comparison.foldPlanSha256 !== summary.foldPlanSha256 ||
    rolling.foldPlanSha256 !== summary.foldPlanSha256 ||
    recommendation.foldPlanSha256 !== summary.foldPlanSha256
  )
    throw new RuntimePublicError(
      "assessment_integrity_error",
      "storage",
      "The assessment evidence bindings do not reconcile.",
      409,
    );
  const validationBytes = await readFile(
    path.join(root, "metadata", "validation.json"),
  );
  if (
    sha256(validationBytes) !== commit.validationRecordSha256 ||
    sha256(validationBytes) !== summary.provenance.validationRecordSha256
  )
    throw new RuntimePublicError(
      "assessment_integrity_error",
      "storage",
      "The committed assessment validation binding does not match.",
      409,
    );
  if (
    summary.assessmentStatus !== "assessment_complete" ||
    summary.approvalStatus !== "approval_pending" ||
    summary.adoptionStatus !== "not_adopted" ||
    summary.recommendationStatus !== "evidence_only" ||
    summary.recommendationStrength !== "not_available"
  )
    throw new RuntimePublicError(
      "assessment_not_decision_ready",
      "validation",
      "The assessment is not eligible for a model-use decision.",
      409,
    );
  return {
    root,
    commit,
    commitSha256: sha256(commitFile.bytes),
    summary,
    summarySha256: summaryHash,
    comparison,
    rolling,
    recommendation,
  };
}

export async function recordDecision(
  config: RuntimeConfig,
  assessmentId: string,
  choice: DecisionChoice,
  reason: string,
  expectedSummary: string,
  correlationId: string,
) {
  const index = assessmentDecisionPaths(config.runtimeRoot, assessmentId);
  const lock = await acquire(index.lock);
  try {
    const existingIndex = await jsonBytes(index.active).catch(() => null);
    if (existingIndex) {
      const existing = await readVerifiedDecision(
        config,
        String(existingIndex.value.decisionId),
      );
      if (
        existingIndex.value.assessmentId !== assessmentId ||
        existingIndex.value.decisionCommitSha256 !==
          existing.decisionCommitSha256
      )
        throw new RuntimePublicError(
          "decision_index_integrity_error",
          "storage",
          "The active model-use decision index failed integrity verification.",
          409,
        );
      if (
        existing.decision.decision === choice &&
        existing.decision.reason === reason
      )
        return existing;
      if (existing.decision.decision !== "defer")
        throw new RuntimePublicError(
          "decision_conflict",
          "validation",
          "A final model-use decision already exists for this assessment.",
          409,
        );
    }
    const evidence = await readVerifiedAssessment(
      config,
      assessmentId,
      expectedSummary,
    );
    const policy = await loadDecisionPolicy(
      config.repositoryRoot,
      evidence.summary.deploymentId,
    );
    if (
      evidence.commit.assessmentPolicySha256 !==
        policy.allowedAssessmentPolicySha256 ||
      evidence.commit.candidateRegistrySha256 !==
        policy.candidateRegistrySha256 ||
      evidence.summary.provenance.assessmentPolicySha256 !==
        policy.allowedAssessmentPolicySha256
    )
      throw new RuntimePublicError(
        "decision_policy_mismatch",
        "validation",
        "The assessment is outside the active decision policy.",
        409,
      );
    const registrySha256 = sha256(
      await readFile(
        path.join(config.repositoryRoot, "config", "candidate_models.json"),
      ),
    );
    if (registrySha256 !== policy.candidateRegistrySha256)
      throw new RuntimePublicError(
        "candidate_registry_changed",
        "validation",
        "The governed candidate registry identity has changed.",
        409,
      );
    const age = Date.now() - Date.parse(evidence.summary.committedAt);
    if (
      !Number.isFinite(age) ||
      age < 0 ||
      age >
        Math.min(
          config.decisionValiditySeconds,
          policy.assessmentValiditySeconds,
        ) *
          1000
    )
      throw new RuntimePublicError(
        "assessment_expired",
        "validation",
        "The assessment is outside the governed decision validity period.",
        409,
      );
    const winner = evidence.summary.technicalWinnerModelId as string | null;
    const candidates = evidence.summary.candidates as Array<
      Record<string, any>
    >;
    const winnerCandidate =
      candidates.find((value) => value.modelId === winner) ?? null;
    const current =
      candidates.find((value) => value.modelId === policy.currentModelId) ??
      null;
    let selected: Record<string, any> | null = null;
    if (choice === "approve_technical_winner") selected = winnerCandidate;
    if (choice === "keep_current_model") selected = current;
    if (
      selected &&
      (!DEPLOYABLE.has(selected.modelId) ||
        selected.deployabilityClass !== "deployable_learned_model" ||
        selected.completionStatus !== "complete" ||
        selected.selectionEligible !== true ||
        selected.successfulFolds !== 68 ||
        selected.failedFolds !== 0)
    )
      throw new RuntimePublicError(
        "selected_model_not_deployable",
        "validation",
        "The selected assessment model is not governed for runtime forecasting.",
        409,
      );
    if (choice === "approve_technical_winner" && !selected)
      throw new RuntimePublicError(
        "technical_winner_unavailable",
        "validation",
        "The assessment has no deployable technical winner.",
        409,
      );
    if (choice === "keep_current_model") {
      const profile = JSON.parse(
        await readFile(
          path.join(
            config.repositoryRoot,
            "config",
            "deployments",
            evidence.summary.deploymentId,
            "profile.json",
          ),
          "utf8",
        ),
      );
      if (
        !selected ||
        selected.parametersSha256 !== policy.currentModelParameterSha256 ||
        profile.model?.model_id !== policy.currentModelId ||
        profile.model?.model_parameters_sha256 !==
          policy.currentModelParameterSha256
      )
        throw new RuntimePublicError(
          "current_model_identity_mismatch",
          "validation",
          "The current Random Forest identity is not valid for this assessment.",
          409,
        );
    }
    const decisionId = randomUUID(),
      authorizationId = selected ? randomUUID() : null,
      createdAt = now();
    const supersedes = existingIndex
      ? String(existingIndex.value.decisionId)
      : null;
    const status =
      choice === "approve_technical_winner"
        ? "approved_technical_winner"
        : choice === "keep_current_model"
          ? "current_model_retained"
          : choice === "defer"
            ? "deferred"
            : "assessment_rejected";
    const decision = {
      schemaVersion: "1.0",
      decisionId,
      assessmentId,
      assessmentCommitSha256: evidence.commitSha256,
      assessmentSummarySha256: evidence.summarySha256,
      comparisonSha256:
        evidence.summary.evidenceHashes.candidateComparisonSha256,
      recommendationSha256:
        evidence.summary.evidenceHashes.recommendationSha256,
      foldPlanSha256: evidence.summary.foldPlanSha256,
      datasetId: evidence.summary.datasetId,
      deploymentId: evidence.summary.deploymentId,
      validationRecordSha256:
        evidence.summary.provenance.validationRecordSha256,
      assessmentPolicyId: policy.allowedAssessmentPolicyId,
      assessmentPolicyVersion: policy.allowedAssessmentPolicyVersion,
      assessmentPolicySha256: policy.allowedAssessmentPolicySha256,
      decisionPolicyId: policy.policyId,
      decisionPolicyVersion: policy.policyVersion,
      decisionPolicySha256: policy.policySha256,
      candidateRegistrySha256: policy.candidateRegistrySha256,
      technicalWinnerModelId: winner,
      technicalWinnerParameterSha256: winnerCandidate?.parametersSha256 ?? null,
      decision: choice,
      selectedModelId: selected?.modelId ?? null,
      selectedModelParameterSha256: selected?.parametersSha256 ?? null,
      decisionScope: "one_run",
      operatorType: "trusted_internal_unverified",
      operatorIdentifier: config.internalOperatorId,
      institutionalApproval: false,
      reason,
      limitationsAcknowledged: true,
      decisionStatus: status,
      forecastAuthorized: Boolean(selected),
      authorizationId,
      createdAt,
      correlationId,
      supersedesDecisionId: supersedes,
      supersessionStatus: supersedes ? "supersedes_defer" : "active",
    };
    const dPaths = decisionPaths(config.runtimeRoot, decisionId);
    const temporary = `${dPaths.root}.tmp-${process.pid}-${Date.now()}`;
    await mkdir(temporary, { recursive: false, mode: 0o700 });
    const decisionBytes = Buffer.from(`${JSON.stringify(decision, null, 2)}\n`);
    await writeJsonAtomic(path.join(temporary, "decision.json"), decision);
    const decisionCommit = {
      schemaVersion: "1.0",
      decisionId,
      assessmentId,
      decisionSha256: sha256(decisionBytes),
      assessmentCommitSha256: evidence.commitSha256,
      decisionPolicySha256: policy.policySha256,
      status: "committed",
      committedAt: createdAt,
      latestPointerUpdated: false,
      deploymentProfileModified: false,
    };
    await writeJsonAtomic(path.join(temporary, "commit.json"), decisionCommit);
    await rename(temporary, dPaths.root);
    await immutableDirectory(dPaths.root);
    const decisionCommitBytes = await readFile(dPaths.commit);
    const decisionCommitSha256 = sha256(decisionCommitBytes);
    await mkdir(index.root, { recursive: true, mode: 0o700 });
    await writeJsonAtomic(index.active, {
      schemaVersion: "1.0",
      assessmentId,
      decisionId,
      decisionCommitSha256,
      authorizationId,
      updatedAt: createdAt,
    });
    if (authorizationId && selected) {
      try {
        const a = authorizationPaths(config.runtimeRoot, authorizationId);
        const temp = `${a.root}.tmp-${process.pid}-${Date.now()}`;
        await mkdir(temp, { recursive: false, mode: 0o700 });
        const expiresAt = new Date(
          Date.parse(createdAt) +
            Math.min(
              config.decisionValiditySeconds,
              policy.assessmentValiditySeconds,
            ) *
              1000,
        ).toISOString();
        const authorization = {
          schemaVersion: "1.0",
          authorizationId,
          decisionId,
          decisionCommitSha256,
          assessmentId,
          assessmentCommitSha256: evidence.commitSha256,
          datasetId: evidence.summary.datasetId,
          deploymentId: evidence.summary.deploymentId,
          selectedModelId: selected.modelId,
          selectedModelParameterSha256: selected.parametersSha256,
          workflowMode: "approved_assessment_forecast",
          scope: "one_run",
          initialStatus: "available",
          createdAt,
          expiresAt,
          policyId: policy.policyId,
          policyVersion: policy.policyVersion,
          policySha256: policy.policySha256,
        };
        await writeJsonAtomic(
          path.join(temp, "authorization.json"),
          authorization,
        );
        const authorizationBytes = await readFile(
          path.join(temp, "authorization.json"),
        );
        await writeJsonAtomic(path.join(temp, "commit.json"), {
          schemaVersion: "1.0",
          authorizationId,
          decisionId,
          authorizationSha256: sha256(authorizationBytes),
          decisionCommitSha256,
          status: "committed",
          committedAt: createdAt,
        });
        await rename(temp, a.root);
        await immutableDirectory(a.root);
      } catch {
        throw new RuntimePublicError(
          "authorization_creation_incomplete",
          "storage",
          "The decision was committed, but its one-run authorization could not be completed. Controlled recovery is required.",
          500,
        );
      }
    }
    return readVerifiedDecision(config, decisionId);
  } finally {
    await lock.close();
    await rm(index.lock, { force: true });
  }
}

export async function readVerifiedDecision(
  config: RuntimeConfig,
  decisionId: string,
) {
  const paths = decisionPaths(config.runtimeRoot, decisionId);
  const [decisionFile, commitFile] = await Promise.all([
    jsonBytes(paths.decision),
    jsonBytes(paths.commit),
  ]).catch(() => {
    throw new RuntimePublicError(
      "decision_not_found",
      "validation",
      "The model-use decision was not found.",
      404,
    );
  });
  const decision = decisionFile.value,
    commit = commitFile.value;
  if (
    commit.status !== "committed" ||
    commit.decisionId !== decisionId ||
    commit.decisionSha256 !== sha256(decisionFile.bytes) ||
    commit.assessmentCommitSha256 !== decision.assessmentCommitSha256 ||
    commit.latestPointerUpdated !== false
  )
    throw new RuntimePublicError(
      "decision_integrity_error",
      "storage",
      "The model-use decision failed integrity verification.",
      409,
    );
  let authorization: null | Record<string, any> = null,
    committedRunId: string | null = null,
    authorizationStatus:
      | "not_authorized"
      | "authorization_incomplete"
      | "available"
      | "reserved"
      | "consumed" =
      "not_authorized";
  if (decision.authorizationId) {
    const p = authorizationPaths(config.runtimeRoot, decision.authorizationId);
    const pair = await Promise.all([
      jsonBytes(p.authorization),
      jsonBytes(p.commit),
    ]).catch(() => null);
    if (!pair) {
      authorizationStatus = "authorization_incomplete";
      return {
        decision,
        commit,
        decisionCommitSha256: sha256(commitFile.bytes),
        authorization,
        authorizationStatus,
        committedRunId,
      };
    }
    const [a, c] = pair;
    if (
      c.value.authorizationSha256 !== sha256(a.bytes) ||
      a.value.decisionCommitSha256 !== sha256(commitFile.bytes)
    )
      throw new RuntimePublicError(
        "authorization_integrity_error",
        "storage",
        "The forecast authorization failed integrity verification.",
        409,
      );
    authorization = a.value;
    const consumption = await jsonBytes(p.consumption).catch(() => null);
    if (consumption) {
      if (
        consumption.value.authorizationId !== decision.authorizationId ||
        consumption.value.decisionId !== decisionId ||
        consumption.value.eventType !== "consumed" ||
        typeof consumption.value.runId !== "string"
      )
        throw new RuntimePublicError(
          "authorization_integrity_error",
          "storage",
          "The forecast authorization consumption record failed integrity verification.",
          409,
        );
      authorizationStatus = "consumed";
      committedRunId = consumption.value.runId;
    } else {
      authorizationStatus = await lstat(p.reservation)
        .then(() => "reserved" as const)
        .catch(() => "available" as const);
    }
    if (authorizationStatus === "reserved") {
      const runs = runtimeCollectionPaths(config.runtimeRoot).runs;
      for (const entry of await readdir(runs, { withFileTypes: true }).catch(
        () => [],
      )) {
        if (!entry.isDirectory()) continue;
        const run = await jsonBytes(
          path.join(runs, entry.name, "metadata", "run.json"),
        ).catch(() => null);
        const commitRun = await jsonBytes(
          path.join(runs, entry.name, "metadata", "commit.json"),
        ).catch(() => null);
        if (
          run?.value.authorizationId === decision.authorizationId &&
          commitRun?.value.status === "committed"
        ) {
          authorizationStatus = "consumed";
          committedRunId = entry.name;
          break;
        }
      }
    }
    if (committedRunId) {
      const committedRun = await jsonBytes(
        path.join(
          runtimeCollectionPaths(config.runtimeRoot).runs,
          committedRunId,
          "metadata",
          "commit.json",
        ),
      ).catch(() => null);
      if (
        !committedRun ||
        committedRun.value.status !== "committed" ||
        committedRun.value.runId !== committedRunId ||
        committedRun.value.decisionId !== decisionId ||
        committedRun.value.authorizationId !== decision.authorizationId ||
        committedRun.value.selectedModelId !== decision.selectedModelId
      )
        throw new RuntimePublicError(
          "approved_forecast_integrity_error",
          "storage",
          "The committed selected-model forecast failed decision binding verification.",
          409,
        );
    }
  }
  return {
    decision,
    commit,
    decisionCommitSha256: sha256(commitFile.bytes),
    authorization,
    authorizationStatus,
    committedRunId,
  };
}

export async function readVerifiedAssessmentDecisionState(
  config: RuntimeConfig,
  assessmentId: string,
) {
  const index = assessmentDecisionPaths(config.runtimeRoot, assessmentId);
  const active = await jsonBytes(index.active).catch((error) => {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw new RuntimePublicError(
      "decision_index_integrity_error",
      "storage",
      "The assessment decision index could not be verified.",
      409,
    );
  });
  if (!active) return null;
  const value = active.value;
  if (
    value.schemaVersion !== "1.0" ||
    value.assessmentId !== assessmentId ||
    typeof value.decisionId !== "string" ||
    typeof value.decisionCommitSha256 !== "string"
  )
    throw new RuntimePublicError(
      "decision_index_integrity_error",
      "storage",
      "The assessment decision index failed identity verification.",
      409,
    );
  const verified = await readVerifiedDecision(config, value.decisionId);
  if (
    verified.decision.assessmentId !== assessmentId ||
    verified.decisionCommitSha256 !== value.decisionCommitSha256 ||
    verified.decision.authorizationId !== value.authorizationId
  )
    throw new RuntimePublicError(
      "decision_index_integrity_error",
      "storage",
      "The assessment decision index does not match immutable decision evidence.",
      409,
    );
  return {
    decisionId: verified.decision.decisionId as string,
    outcome: verified.decision.decision as DecisionChoice,
    decisionStatus: verified.decision.decisionStatus as string,
    selectedModelId: (verified.decision.selectedModelId as string | null) ?? null,
    forecastAuthorized: verified.decision.forecastAuthorized === true,
    authorizationId: (verified.decision.authorizationId as string | null) ?? null,
    authorizationStatus: verified.authorizationStatus,
    committedRunId: verified.committedRunId,
    decisionCommitSha256: verified.decisionCommitSha256,
    createdAt: verified.decision.createdAt as string,
  };
}
