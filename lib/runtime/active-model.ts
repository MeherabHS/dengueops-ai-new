import "server-only";

import { createHash } from "node:crypto";
import { lstat, readFile, readdir } from "node:fs/promises";
import path from "node:path";
import { RuntimePublicError } from "./errors";

import {
  LIFECYCLE_CANDIDATE_REGISTRY_SHA,
  LIFECYCLE_FEATURE_ORDER_SHA,
  LIFECYCLE_PROFILE_SHA,
  LIFECYCLE_QUICK_POLICY_SHA,
  LIFECYCLE_QUICK_POLICY_RAW_SHA,
  LIFECYCLE_RF_PARAMETER_SHA,
  MODEL_LIFECYCLE_POLICY_SHA,
  loadModelLifecyclePolicy,
} from "./model-lifecycle-policy";
import { validateStrictJsonSchema } from "./strict-json-schema";


import type { ActiveModelAuthority, CurrentActiveModelAuthority } from "./contracts";

export type { ActiveModelAuthority } from "./contracts";

type JsonObject = Record<string, any>;
type JsonFile = { bytes: Buffer; value: JsonObject };
type Bundle = {
  root: string;
  decision: JsonFile;
  decisionCommit: JsonFile;
  assignment: JsonFile | null;
  assignmentCommit: JsonFile | null;
};

const sha = (value: Buffer | string) => createHash("sha256").update(value).digest("hex");

function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, child]) => `${JSON.stringify(key)}:${canonical(child)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

async function rejectSymlinkPath(root: string, candidate: string): Promise<void> {
  const resolvedRoot = path.resolve(root);
  const resolvedCandidate = path.resolve(candidate);
  const relative = path.relative(resolvedRoot, resolvedCandidate);
  if (relative.startsWith("..") || path.isAbsolute(relative)) throw new Error("path_escape");
  let current = resolvedRoot;
  for (const part of relative.split(path.sep).filter(Boolean)) {
    current = path.join(current, part);
    try {
      if ((await lstat(current)).isSymbolicLink()) throw new Error("symlink_path");
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    }
  }
}

async function safeJson(file: string, root?: string): Promise<JsonFile> {
  if (root) await rejectSymlinkPath(root, file);
  const stat = await lstat(file);
  if (stat.isSymbolicLink() || !stat.isFile()) throw new Error("unsafe_json");
  const bytes = await readFile(file);
  const value: unknown = JSON.parse(bytes.toString("utf8"));
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("json_not_object");
  return { bytes, value: value as JsonObject };
}

async function validateArtifact(repositoryRoot: string, name: string, value: unknown): Promise<void> {
  const schema = JSON.parse(await readFile(path.join(repositoryRoot, "config", name), "utf8"));
  validateStrictJsonSchema(schema, value);
}

function integrity(): never {
  throw new RuntimePublicError(
    "active_model_integrity_error",
    "storage",
    "The active model authority failed integrity verification.",
    409,
  );
}

async function verifyBundle(repositoryRoot: string, runtimeRoot: string, root: string): Promise<Bundle> {
  await rejectSymlinkPath(runtimeRoot, root);
  const rootStat = await lstat(root);
  if (rootStat.isSymbolicLink() || !rootStat.isDirectory()) throw new Error("unsafe_bundle");
  const [decision, decisionCommit] = await Promise.all([
    safeJson(path.join(root, "artifacts", "lifecycle_decision.json"), runtimeRoot),
    safeJson(path.join(root, "metadata", "lifecycle_decision_commit.json"), runtimeRoot),
  ]);
  await Promise.all([
    validateArtifact(repositoryRoot, "runtime_model_lifecycle_decision.schema.json", decision.value),
    validateArtifact(repositoryRoot, "runtime_model_lifecycle_decision_commit.schema.json", decisionCommit.value),
  ]);
  const lifecycleId = decision.value.lifecycleDecisionId;
  if (
    path.basename(root) !== lifecycleId ||
    decisionCommit.value.lifecycleDecisionId !== lifecycleId ||
    decisionCommit.value.jobId !== decision.value.jobId ||
    decisionCommit.value.action !== decision.value.action ||
    decisionCommit.value.lifecycleDecisionSha256 !== sha(decision.bytes)
  ) throw new Error("decision_identity_mismatch");
  for (const value of [decision.value, decisionCommit.value]) {
    if (
      value.policyId !== "RUNTIME.MODEL_LIFECYCLE.DECISION" ||
      value.policyVersion !== "p2-v1" ||
      value.policySha256 !== MODEL_LIFECYCLE_POLICY_SHA
    ) throw new Error("lifecycle_policy_mismatch");
  }

  const assignmentPath = path.join(root, "artifacts", "model_assignment.json");
  const assignmentCommitPath = path.join(root, "metadata", "model_assignment_commit.json");
  let assignment: JsonFile | null = null;
  let assignmentCommit: JsonFile | null = null;
  try {
    [assignment, assignmentCommit] = await Promise.all([
      safeJson(assignmentPath, runtimeRoot),
      safeJson(assignmentCommitPath, runtimeRoot),
    ]);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    try { await lstat(assignmentPath); throw new Error("partial_assignment"); } catch (left) { if ((left as NodeJS.ErrnoException).code !== "ENOENT") throw left; }
    try { await lstat(assignmentCommitPath); throw new Error("partial_assignment_commit"); } catch (right) { if ((right as NodeJS.ErrnoException).code !== "ENOENT") throw right; }
    if (decision.value.resultingAssignmentId !== null) throw new Error("missing_assignment");
    return { root, decision, decisionCommit, assignment: null, assignmentCommit: null };
  }
  await Promise.all([
    validateArtifact(repositoryRoot, "runtime_model_assignment.schema.json", assignment.value),
    validateArtifact(repositoryRoot, "runtime_model_assignment_commit.schema.json", assignmentCommit.value),
  ]);
  const actionMap: Record<string, string> = {
    bootstrap: "bootstrap_historical_profile",
    promote: "promote_selected_model",
    rollback: "rollback_previous_assignment",
  };
  const assignmentId = assignment.value.assignmentId;
  if (
    decision.value.action !== actionMap[assignment.value.assignmentAction] ||
    decision.value.resultingAssignmentId !== assignmentId ||
    assignmentCommit.value.assignmentId !== assignmentId ||
    assignmentCommit.value.assignmentAction !== assignment.value.assignmentAction ||
    assignment.value.lifecycleDecisionId !== lifecycleId ||
    assignmentCommit.value.lifecycleDecisionId !== lifecycleId ||
    assignment.value.lifecycleDecisionCommitSha256 !== sha(decisionCommit.bytes) ||
    assignmentCommit.value.lifecycleDecisionCommitSha256 !== sha(decisionCommit.bytes) ||
    assignmentCommit.value.assignmentSha256 !== sha(assignment.bytes)
  ) throw new Error("assignment_identity_mismatch");
  if (
    assignmentCommit.value.priorPointerSha256 !== decisionCommit.value.inputAssignmentPointerSha256 ||
    decision.value.expectedAssignmentPointerSha256 !== decisionCommit.value.inputAssignmentPointerSha256 ||
    decision.value.expectedAssignmentPointerState !== decisionCommit.value.inputAssignmentPointerState ||
    assignment.value.priorAssignmentId !== assignmentCommit.value.priorAssignmentId ||
    assignment.value.priorAssignmentCommitSha256 !== assignmentCommit.value.priorAssignmentCommitSha256 ||
    decision.value.priorAssignmentId !== assignment.value.priorAssignmentId ||
    decision.value.priorAssignmentCommitSha256 !== assignment.value.priorAssignmentCommitSha256
  ) throw new Error("assignment_prior_mismatch");
  const governedIdentity = [
    "random_forest", "RandomForestRegressor", LIFECYCLE_RF_PARAMETER_SHA,
    LIFECYCLE_FEATURE_ORDER_SHA, LIFECYCLE_CANDIDATE_REGISTRY_SHA,
    "RUNTIME.QUICK_FORECAST.COMPATIBILITY", "p1.4f-v1", LIFECYCLE_QUICK_POLICY_SHA,
  ];
  for (const value of [assignment.value, assignmentCommit.value]) {
    const actual = [value.assignedModelId, value.modelFamily, value.parameterSha256, value.featureOrderSha256,
      value.candidateRegistrySha256, value.quickForecastPolicyId, value.quickForecastPolicyVersion, value.quickForecastPolicySha256];
    if (JSON.stringify(actual) !== JSON.stringify(governedIdentity)) throw new Error("selected_model_not_active_quick_forecast_compatible");
  }
  if (
    assignment.value.deploymentId !== "dhaka_south" ||
    assignment.value.target !== "target_cases_next_2w" ||
    assignment.value.forecastHorizonWeeks !== 2 ||
    JSON.stringify(assignment.value.geography) !== JSON.stringify({ level: "city", id: "BGD-DHAKA-SOUTH", name: "Dhaka South" })
  ) throw new Error("assignment_deployment_mismatch");
  return { root, decision, decisionCommit, assignment, assignmentCommit };
}

async function readHistory(repositoryRoot: string, runtimeRoot: string): Promise<{
  assignments: Map<string, Bundle>;
  decisions: Map<string, Bundle>;
}> {
  const assignments = new Map<string, Bundle>();
  const decisions = new Map<string, Bundle>();
  const historyRoot = path.join(runtimeRoot, "model-lifecycle");
  let names: string[];
  try { names = await readdir(historyRoot); }
  catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return { assignments, decisions };
    throw error;
  }
  await rejectSymlinkPath(runtimeRoot, historyRoot);
  for (const name of names) {
    const bundle = await verifyBundle(repositoryRoot, runtimeRoot, path.join(historyRoot, name));
    const decisionId = String(bundle.decision.value.lifecycleDecisionId);
    if (decisions.has(decisionId)) throw new Error("duplicate_decision_id");
    decisions.set(decisionId, bundle);
    if (bundle.assignment) {
      const assignmentId = String(bundle.assignment.value.assignmentId);
      if (assignments.has(assignmentId)) throw new Error("duplicate_assignment_id");
      assignments.set(assignmentId, bundle);
    }
  }
  return { assignments, decisions };
}

export async function resolveActiveModelP2V2(params: {
  repositoryRoot: string;
  runtimeRoot: string;
  deploymentId?: string;
}): Promise<CurrentActiveModelAuthority> {
  const deploymentId = params.deploymentId || "dhaka_south";
  try {
    const policy = await loadModelLifecyclePolicy({
      repositoryRoot: params.repositoryRoot,
      deploymentId,
      version: "p2-v2"
    });
    const pointerPath = path.join(params.runtimeRoot, "deployments", deploymentId, "model-assignment", "latest.json");
    let pointerFile: JsonFile;
    try {
      pointerFile = await safeJson(pointerPath, params.runtimeRoot);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") {
        throw new RuntimePublicError("active_model_not_assigned", "storage", "No active model assigned on p2-v2 deployment.", 404);
      }
      throw error;
    }
    const pointer = pointerFile.value;
    await validateArtifact(params.repositoryRoot, "runtime_model_assignment_latest.schema.json", pointer);
    if (
      pointer.schemaVersion !== "2.0" ||
      pointer.deploymentId !== deploymentId ||
      pointer.policyId !== policy.policyId ||
      pointer.policyVersion !== policy.policyVersion ||
      pointer.policySha256 !== policy.policySha256 ||
      pointer.assignmentAction !== "assign_selected_model" ||
      pointer.activeModelAuthority !== "committed_assignment" ||
      pointer.automaticAction !== false
    ) throw new Error("pointer_identity_mismatch");
    if (String(pointer.assignmentPath ?? "").includes("model-lifecycle")) throw new Error("cross_version_pointer");
    if ((pointer.priorAssignmentId === null) !== (pointer.priorAssignmentCommitSha256 === null)) {
      throw new Error("half_null_prior_assignment");
    }

    const assignmentId = String(pointer.assignmentId || "");
    if (!assignmentId || assignmentId.includes("/") || assignmentId.includes("\\") || assignmentId.includes("..")) {
      throw new Error("invalid_assignment_id");
    }
    const assignmentDir = path.join(params.runtimeRoot, "model-assignments", assignmentId);
    await rejectSymlinkPath(params.runtimeRoot, assignmentDir);
    const [recordFile, commitFile] = await Promise.all([
      safeJson(path.join(assignmentDir, "artifacts", "assignment_record.json"), params.runtimeRoot),
      safeJson(path.join(assignmentDir, "metadata", "commit.json"), params.runtimeRoot),
    ]);
    const record = recordFile.value;
    const commit = commitFile.value;
    const assignmentCommitSha256 = sha(commitFile.bytes);
    if (
      commit.schemaVersion !== "2.0" ||
      commit.assignmentId !== assignmentId ||
      commit.assignmentRecordSha256 !== sha(recordFile.bytes) ||
      pointer.assignmentCommitSha256 !== assignmentCommitSha256
    ) throw new Error("assignment_commit_mismatch");
    if (
      record.schemaVersion !== "2.0" ||
      record.deploymentId !== deploymentId ||
      record.assignmentId !== assignmentId ||
      record.assignmentAction !== pointer.assignmentAction ||
      record.priorAssignmentId !== pointer.priorAssignmentId ||
      record.priorAssignmentCommitSha256 !== pointer.priorAssignmentCommitSha256
    ) throw new Error("assignment_record_identity_mismatch");
    const pointerRecordPairs: Array<[string, string]> = [
      ["assignedModelId", "modelId"],
      ["modelFamily", "modelFamily"],
      ["parameterSha256", "parameterSha256"],
      ["candidateRegistrySha256", "candidateRegistrySha256"],
      ["featureOrderSha256", "featureOrderSha256"],
    ];
    if (pointerRecordPairs.some(([left, right]) => pointer[left] !== record[right])) {
      throw new Error("pointer_record_mismatch");
    }

    const registryFile = await safeJson(path.join(params.repositoryRoot, "config", "candidate_models.json"));
    await validateArtifact(params.repositoryRoot, "candidate_models.schema.json", registryFile.value);
    const registry = registryFile.value;
    const registrySha = sha(registryFile.bytes);
    if (
      registrySha !== policy.candidateRegistrySha256 ||
      registrySha !== pointer.candidateRegistrySha256 ||
      registrySha !== record.candidateRegistrySha256 ||
      registry.feature_order_sha256 !== policy.featureOrderSha256 ||
      registry.feature_order_sha256 !== pointer.featureOrderSha256 ||
      registry.feature_order_sha256 !== record.featureOrderSha256
    ) throw new Error("candidate_registry_identity_mismatch");
    const candidate = (registry.candidates as JsonObject[]).find(item => item.model_id === record.modelId);
    if (
      !candidate ||
      candidate.candidate_class !== "learned_model" ||
      candidate.selection_role !== "learned_selectable" ||
      candidate.selectable !== true ||
      candidate.model_family !== record.modelFamily ||
      candidate.parameters_sha256 !== record.parameterSha256 ||
      candidate.preprocessing_identity !== record.preprocessingIdentity ||
      candidate.feature_order_sha256 !== record.featureOrderSha256
    ) throw new Error("candidate_assignment_mismatch");

    const seen = new Set([assignmentId]);
    let current = record;
    while (current.priorAssignmentId) {
      const priorId = String(current.priorAssignmentId);
      const priorSha = String(current.priorAssignmentCommitSha256 ?? "");
      if (!priorSha || seen.has(priorId) || priorId.includes("/") || priorId.includes("\\") || priorId.includes("..")) {
        throw new Error("invalid_assignment_chain");
      }
      seen.add(priorId);
      const priorDir = path.join(params.runtimeRoot, "model-assignments", priorId);
      const [priorRecord, priorCommit] = await Promise.all([
        safeJson(path.join(priorDir, "artifacts", "assignment_record.json"), params.runtimeRoot),
        safeJson(path.join(priorDir, "metadata", "commit.json"), params.runtimeRoot),
      ]);
      if (
        sha(priorCommit.bytes) !== priorSha ||
        priorCommit.value.schemaVersion !== "2.0" ||
        priorCommit.value.assignmentId !== priorId ||
        priorCommit.value.assignmentRecordSha256 !== sha(priorRecord.bytes) ||
        priorRecord.value.schemaVersion !== "2.0" ||
        priorRecord.value.assignmentId !== priorId ||
        priorRecord.value.deploymentId !== deploymentId
      ) throw new Error("invalid_prior_assignment");
      current = priorRecord.value;
    }

    return {
      deploymentId,
      authoritySource: "committed_assignment",
      modelId: record.modelId,
      modelFamily: record.modelFamily,
      parameterSha256: record.parameterSha256,
      preprocessingIdentity: record.preprocessingIdentity,
      candidateRegistrySha256: record.candidateRegistrySha256,
      featureOrderSha256: record.featureOrderSha256,
      assignmentId,
      assignmentCommitSha256,
      assignmentAction: record.assignmentAction,
      lifecyclePolicyId: policy.policyId as "RUNTIME.MODEL_LIFECYCLE.DECISION",
      lifecyclePolicyVersion: policy.policyVersion as "p2-v2" | "p2-v3",
      lifecyclePolicySha256: String(policy.policySha256),
      authoritySnapshotSha256: sha(pointerFile.bytes),
    };
  } catch (error) {
    if (error instanceof RuntimePublicError && error.code === "active_model_not_assigned") throw error;
    return integrity();
  }
}

export async function resolveHistoricalActiveModelP2V1(params: {
  repositoryRoot: string;
  runtimeRoot: string;
  deploymentId?: string;
}): Promise<ActiveModelAuthority> {
  const deploymentId = params.deploymentId || "dhaka_south";
  if (deploymentId !== "dhaka_south") return integrity();
  await loadModelLifecyclePolicy({
    repositoryRoot: params.repositoryRoot,
    deploymentId,
    version: "p2-v1"
  });
  try {
    const [profile, quick, registry, history] = await Promise.all([
      readFile(path.join(params.repositoryRoot, "config", "deployments", "dhaka_south", "profile.json")),
      safeJson(path.join(params.repositoryRoot, "config", "deployments", "dhaka_south", "quick_forecast_policy_p1.4f-v1.json")),
      readFile(path.join(params.repositoryRoot, "config", "candidate_models_p1.2a-v1.json")),
      readHistory(params.repositoryRoot, params.runtimeRoot),
    ]);
    const quickContent = { ...quick.value };
    delete quickContent.policy_sha256;
    if (
      sha(profile) !== LIFECYCLE_PROFILE_SHA ||
      sha(registry) !== LIFECYCLE_CANDIDATE_REGISTRY_SHA ||
      sha(quick.bytes) !== LIFECYCLE_QUICK_POLICY_RAW_SHA ||
      quick.value.policy_sha256 !== LIFECYCLE_QUICK_POLICY_SHA ||
      sha(canonical(quickContent)) !== LIFECYCLE_QUICK_POLICY_SHA ||
      quick.value.feature_contract?.feature_order_sha256 !== LIFECYCLE_FEATURE_ORDER_SHA
    ) return integrity();

    const latest = path.join(params.runtimeRoot, "deployments", deploymentId, "model-assignment", "latest.json");
    let pointer: JsonFile;
    try { pointer = await safeJson(latest, params.runtimeRoot); }
    catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
      if (history.assignments.size) return integrity();
      const snapshot = sha(Buffer.concat([
        Buffer.from("historical_profile_fallback_pending_explicit_bootstrap\0"),
        profile,
        Buffer.from(MODEL_LIFECYCLE_POLICY_SHA),
      ]));
      return {
        authoritySource: "historical_profile_fallback_pending_explicit_bootstrap",
        authoritySnapshotSha256: snapshot,
        assignmentPointerSha256: null,
        assignmentId: null,
        assignmentCommitSha256: null,
        modelId: "random_forest",
        modelFamily: "RandomForestRegressor",
        parameterSha256: LIFECYCLE_RF_PARAMETER_SHA,
        featureOrderSha256: LIFECYCLE_FEATURE_ORDER_SHA,
        candidateRegistrySha256: LIFECYCLE_CANDIDATE_REGISTRY_SHA,
        quickPolicyId: "RUNTIME.QUICK_FORECAST.COMPATIBILITY",
        quickPolicyVersion: "p1.4f-v1",
        quickPolicySha256: LIFECYCLE_QUICK_POLICY_SHA,
        lifecyclePolicyId: "RUNTIME.MODEL_LIFECYCLE.DECISION",
        lifecyclePolicyVersion: "p2-v1",
        lifecyclePolicySha256: MODEL_LIFECYCLE_POLICY_SHA,
        profileSha256: LIFECYCLE_PROFILE_SHA,
        bootstrapRequired: true,
        quickForecastCompatible: true,
      };
    }
    await validateArtifact(params.repositoryRoot, "runtime_model_assignment_latest.schema.json", pointer.value);
    const current = pointer.value;
    if (current.schemaVersion === "2.0") return integrity();
    const expectedAssignmentPath = `model-lifecycle/${current.lifecycleDecisionId}/artifacts/model_assignment.json`;
    const expectedDecisionPath = `model-lifecycle/${current.lifecycleDecisionId}/artifacts/lifecycle_decision.json`;
    if (
      current.policySha256 !== MODEL_LIFECYCLE_POLICY_SHA ||
      current.assignmentPath !== expectedAssignmentPath ||
      current.lifecycleDecisionPath !== expectedDecisionPath
    ) return integrity();
    await Promise.all([
      rejectSymlinkPath(params.runtimeRoot, path.join(params.runtimeRoot, current.assignmentPath)),
      rejectSymlinkPath(params.runtimeRoot, path.join(params.runtimeRoot, current.lifecycleDecisionPath)),
    ]);
    const bundle = history.decisions.get(String(current.lifecycleDecisionId));
    if (!bundle || bundle !== history.assignments.get(String(current.assignmentId)) || !bundle.assignment || !bundle.assignmentCommit) return integrity();
    if (
      sha(bundle.assignment.bytes) !== current.assignmentSha256 ||
      sha(bundle.decision.bytes) !== current.lifecycleDecisionSha256 ||
      sha(bundle.assignmentCommit.bytes) !== current.assignmentCommitSha256 ||
      sha(bundle.decisionCommit.bytes) !== current.lifecycleDecisionCommitSha256 ||
      bundle.assignment.value.lifecycleDecisionCommitSha256 !== current.lifecycleDecisionCommitSha256 ||
      bundle.assignmentCommit.value.assignmentSha256 !== current.assignmentSha256 ||
      bundle.decisionCommit.value.lifecycleDecisionSha256 !== current.lifecycleDecisionSha256
    ) return integrity();
    const pointerIdentity = [current.assignedModelId, current.modelFamily, current.parameterSha256, current.featureOrderSha256,
      current.candidateRegistrySha256, current.assignmentAction, current.priorAssignmentId, current.priorAssignmentCommitSha256];
    const assignmentIdentity = [bundle.assignment.value.assignedModelId, bundle.assignment.value.modelFamily,
      bundle.assignment.value.parameterSha256, bundle.assignment.value.featureOrderSha256,
      bundle.assignment.value.candidateRegistrySha256, bundle.assignment.value.assignmentAction,
      bundle.assignment.value.priorAssignmentId, bundle.assignment.value.priorAssignmentCommitSha256];
    if (JSON.stringify(pointerIdentity) !== JSON.stringify(assignmentIdentity)) return integrity();

    const seen = new Set<string>([String(current.assignmentId)]);
    let chain = bundle;
    while (chain.assignment?.value.priorAssignmentId != null) {
      const priorId = String(chain.assignment.value.priorAssignmentId);
      if (seen.has(priorId)) return integrity();
      seen.add(priorId);
      const prior = history.assignments.get(priorId);
      if (!prior?.assignment || !prior.assignmentCommit) return integrity();
      if (
        sha(prior.assignmentCommit.bytes) !== chain.assignment.value.priorAssignmentCommitSha256 ||
        prior.assignmentCommit.value.assignmentSha256 !== sha(prior.assignment.bytes) ||
        prior.decisionCommit.value.lifecycleDecisionSha256 !== sha(prior.decision.bytes) ||
        prior.assignment.value.lifecycleDecisionCommitSha256 !== sha(prior.decisionCommit.bytes)
      ) return integrity();
      chain = prior;
    }
    if (seen.size !== history.assignments.size) return integrity();
    return {
      authoritySource: "committed_assignment",
      authoritySnapshotSha256: sha(pointer.bytes),
      assignmentPointerSha256: sha(pointer.bytes),
      assignmentId: current.assignmentId,
      assignmentCommitSha256: current.assignmentCommitSha256,
      assignmentAction: current.assignmentAction,
      effectiveAt: current.publishedAt,
      priorAssignmentId: current.priorAssignmentId,
      modelId: "random_forest",
      modelFamily: "RandomForestRegressor",
      parameterSha256: LIFECYCLE_RF_PARAMETER_SHA,
      featureOrderSha256: LIFECYCLE_FEATURE_ORDER_SHA,
      candidateRegistrySha256: LIFECYCLE_CANDIDATE_REGISTRY_SHA,
      quickPolicyId: "RUNTIME.QUICK_FORECAST.COMPATIBILITY",
      quickPolicyVersion: "p1.4f-v1",
      quickPolicySha256: LIFECYCLE_QUICK_POLICY_SHA,
      lifecyclePolicyId: "RUNTIME.MODEL_LIFECYCLE.DECISION",
      lifecyclePolicyVersion: "p2-v1",
      lifecyclePolicySha256: MODEL_LIFECYCLE_POLICY_SHA,
      profileSha256: null,
      bootstrapRequired: false,
      quickForecastCompatible: true,
    };
  } catch (error) {
    if (error instanceof RuntimePublicError) throw error;
    return integrity();
  }
}

export async function resolveActiveModel(
  repositoryRoot: string,
  runtimeRoot: string,
  deploymentId = "dhaka_south",
): Promise<CurrentActiveModelAuthority> {
  return resolveActiveModelP2V2({
    repositoryRoot,
    runtimeRoot,
    deploymentId
  });
}
