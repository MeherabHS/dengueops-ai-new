import path from "node:path";
import { RuntimePublicError } from "./errors";

export function assertContained(root: string, candidate: string): string {
  const resolvedRoot = path.resolve(root);
  const resolved = path.resolve(candidate);
  const relative = path.relative(resolvedRoot, resolved);
  if (relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative))) return resolved;
  throw new RuntimePublicError("runtime_path_escape", "storage", "A runtime path escaped its workspace.", 500);
}

export interface WorkspacePaths {
  root: string;
  metadata: string;
  workspaceMetadata: string;
  validation: string;
  originalInputs: string;
  canonicalInputs: string;
  dengueOriginal: string;
  climateOriginal: string;
  dengueCanonical: string;
  climateCanonical: string;
  logs: string;
  events: string;
  stdout: string;
  stderr: string;
}

export function workspacePaths(runtimeRoot: string, workspaceId: string): WorkspacePaths {
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(workspaceId)) {
    throw new RuntimePublicError("invalid_workspace_id", "storage", "The workspace identifier is invalid.", 500);
  }
  const workspaces = assertContained(runtimeRoot, path.join(/* turbopackIgnore: true */ runtimeRoot, "workspaces"));
  const root = assertContained(workspaces, path.join(/* turbopackIgnore: true */ workspaces, workspaceId));
  const metadata = assertContained(root, path.join(/* turbopackIgnore: true */ root, "metadata"));
  const originalInputs = assertContained(root, path.join(/* turbopackIgnore: true */ root, "inputs", "original"));
  const canonicalInputs = assertContained(root, path.join(/* turbopackIgnore: true */ root, "inputs", "canonical"));
  const logs = assertContained(root, path.join(/* turbopackIgnore: true */ root, "logs"));
  return {
    root,
    metadata,
    workspaceMetadata: assertContained(root, path.join(/* turbopackIgnore: true */ metadata, "workspace.json")),
    validation: assertContained(root, path.join(/* turbopackIgnore: true */ metadata, "validation.json")),
    originalInputs,
    canonicalInputs,
    dengueOriginal: assertContained(root, path.join(/* turbopackIgnore: true */ originalInputs, "dengue.csv")),
    climateOriginal: assertContained(root, path.join(/* turbopackIgnore: true */ originalInputs, "climate.csv")),
    dengueCanonical: assertContained(root, path.join(/* turbopackIgnore: true */ canonicalInputs, "dengue_cases.csv")),
    climateCanonical: assertContained(root, path.join(/* turbopackIgnore: true */ canonicalInputs, "climate_data.csv")),
    logs,
    events: assertContained(root, path.join(/* turbopackIgnore: true */ logs, "events.jsonl")),
    stdout: assertContained(root, path.join(/* turbopackIgnore: true */ logs, "validation.stdout.log")),
    stderr: assertContained(root, path.join(/* turbopackIgnore: true */ logs, "validation.stderr.log")),
  };
}

export function runtimeCollectionPaths(runtimeRoot: string) {
  const root = path.resolve(runtimeRoot);
  const jobs = assertContained(root, path.join(root, "jobs"));
  return {
    jobs,
    pendingJobs: assertContained(root, path.join(jobs, "pending")),
    runningJobs: assertContained(root, path.join(jobs, "running")),
    completedJobs: assertContained(root, path.join(jobs, "completed")),
    failedJobs: assertContained(root, path.join(jobs, "failed")),
    staging: assertContained(root, path.join(root, "staging")),
    runs: assertContained(root, path.join(root, "runs")),
    assessmentStaging: assertContained(root, path.join(root, "assessment-staging")),
    assessments: assertContained(root, path.join(root, "assessments")),
    decisions: assertContained(root, path.join(root, "decisions")),
    assessmentDecisions: assertContained(root, path.join(root, "assessment-decisions")),
    authorizations: assertContained(root, path.join(root, "authorizations")),
    authorizationState: assertContained(root, path.join(root, "authorization-state")),
    deployments: assertContained(root, path.join(root, "deployments")),
    locks: assertContained(root, path.join(root, "locks")),
    outcomeStaging: assertContained(root, path.join(root, "outcome-staging")),
    forecastOutcomes: assertContained(root, path.join(root, "forecast-outcomes")),
    degradationStaging: assertContained(root, path.join(root, "degradation-staging")),
    degradationEvidence: assertContained(root, path.join(root, "degradation-evidence")),
    lifecycleStaging: assertContained(root, path.join(root, "lifecycle-staging")),
    modelLifecycle: assertContained(root, path.join(root, "model-lifecycle")),
  };
}

export function modelLifecyclePaths(runtimeRoot:string,lifecycleDecisionId:string){const collections=runtimeCollectionPaths(runtimeRoot);const staging=uuidPath(collections.lifecycleStaging,lifecycleDecisionId,"lifecycle_decision");const committed=uuidPath(collections.modelLifecycle,lifecycleDecisionId,"lifecycle_decision");return{staging,committed,decision:assertContained(committed,path.join(committed,"artifacts","lifecycle_decision.json")),assignment:assertContained(committed,path.join(committed,"artifacts","model_assignment.json")),decisionCommit:assertContained(committed,path.join(committed,"metadata","lifecycle_decision_commit.json")),assignmentCommit:assertContained(committed,path.join(committed,"metadata","model_assignment_commit.json"))};}
export function modelAssignmentPaths(runtimeRoot:string,deploymentId:string){const deployment=deploymentRuntimePaths(runtimeRoot,deploymentId);const root=assertContained(deployment.root,path.join(deployment.root,"model-assignment"));return{root,latest:assertContained(root,path.join(root,"latest.json")),commitLock:assertContained(root,path.join(root,"locks","commit.lock"))};}

export function forecastOutcomePaths(runtimeRoot: string, outcomeId: string) {
  const collections = runtimeCollectionPaths(runtimeRoot);
  const staging = uuidPath(collections.outcomeStaging, outcomeId, "outcome");
  const committed = uuidPath(collections.forecastOutcomes, outcomeId, "outcome");
  return { staging, committed, observation: assertContained(committed, path.join(committed, "artifacts", "observation.json")), evaluation: assertContained(committed, path.join(committed, "artifacts", "outcome_evaluation.json")), summary: assertContained(committed, path.join(committed, "artifacts", "monitoring_summary.json")), commit: assertContained(committed, path.join(committed, "metadata", "commit.json")) };
}

export function monitoringPaths(runtimeRoot: string, deploymentId: string) {
  const deployment = deploymentRuntimePaths(runtimeRoot, deploymentId);
  const root = assertContained(deployment.root, path.join(deployment.root, "monitoring"));
  return { root, latest: assertContained(root, path.join(root, "latest.json")), commitLock: assertContained(root, path.join(root, "locks", "commit.lock")) };
}

export function modelDegradationPaths(runtimeRoot:string,evidenceId:string){const collections=runtimeCollectionPaths(runtimeRoot);const staging=uuidPath(collections.degradationStaging,evidenceId,"evidence");const committed=uuidPath(collections.degradationEvidence,evidenceId,"evidence");return{staging,committed,evidence:assertContained(committed,path.join(committed,"artifacts","degradation_evidence.json")),summary:assertContained(committed,path.join(committed,"artifacts","degradation_summary.json")),commit:assertContained(committed,path.join(committed,"metadata","commit.json"))};}
export function modelDegradationLatestPaths(runtimeRoot:string,deploymentId:string){const deployment=deploymentRuntimePaths(runtimeRoot,deploymentId);const root=assertContained(deployment.root,path.join(deployment.root,"degradation"));return{root,latest:assertContained(root,path.join(root,"latest.json")),commitLock:assertContained(root,path.join(root,"locks","commit.lock"))};}

function uuidPath(root: string, value: string, label: string): string {
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value)) {
    throw new RuntimePublicError(`invalid_${label}_id`, "storage", `The ${label} identifier is invalid.`, 400);
  }
  return assertContained(root, path.join(root, value));
}

export function decisionPaths(runtimeRoot: string, decisionId: string) {
  const collections = runtimeCollectionPaths(runtimeRoot); const root = uuidPath(collections.decisions, decisionId, "decision");
  return { root, decision: assertContained(root, path.join(root, "decision.json")), commit: assertContained(root, path.join(root, "commit.json")) };
}

export function assessmentDecisionPaths(runtimeRoot: string, assessmentId: string) {
  const collections = runtimeCollectionPaths(runtimeRoot); const root = uuidPath(collections.assessmentDecisions, assessmentId, "assessment");
  return { root, active: assertContained(root, path.join(root, "active.json")), lock: assertContained(collections.locks, path.join(collections.locks, "decisions", `${assessmentId}.lock`)) };
}

export function authorizationPaths(runtimeRoot: string, authorizationId: string) {
  const collections = runtimeCollectionPaths(runtimeRoot); const root = uuidPath(collections.authorizations, authorizationId, "authorization"); const state = uuidPath(collections.authorizationState, authorizationId, "authorization");
  return { root, authorization: assertContained(root, path.join(root, "authorization.json")), commit: assertContained(root, path.join(root, "commit.json")), state, reservation: assertContained(state, path.join(state, "reservation.json")), consumption: assertContained(state, path.join(state, "consumption.json")), lock: assertContained(collections.locks, path.join(collections.locks, "authorizations", `${authorizationId}.lock`)) };
}

export function assessmentPaths(runtimeRoot: string, assessmentId: string) {
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(assessmentId)) {
    throw new RuntimePublicError("invalid_assessment_id", "storage", "The assessment identifier is invalid.", 400);
  }
  const collections = runtimeCollectionPaths(runtimeRoot);
  return {
    staging: assertContained(collections.assessmentStaging, path.join(collections.assessmentStaging, assessmentId)),
    committed: assertContained(collections.assessments, path.join(collections.assessments, assessmentId)),
  };
}

export function jobRecordPath(directory: string, jobId: string): string {
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(jobId)) {
    throw new RuntimePublicError("invalid_job_id", "storage", "The job identifier is invalid.", 400);
  }
  return assertContained(directory, path.join(directory, `${jobId}.json`));
}

export function deploymentRuntimePaths(runtimeRoot: string, deploymentId: string) {
  if (!/^[a-z0-9][a-z0-9_-]{0,63}$/.test(deploymentId)) {
    throw new RuntimePublicError("invalid_deployment_id", "storage", "The deployment identifier is invalid.", 400);
  }
  const collections = runtimeCollectionPaths(runtimeRoot);
  const root = assertContained(collections.deployments, path.join(collections.deployments, deploymentId));
  return { root, latest: assertContained(root, path.join(root, "latest.json")), locks: assertContained(root, path.join(root, "locks")), commitLock: assertContained(root, path.join(root, "locks", "commit.lock")) };
}
