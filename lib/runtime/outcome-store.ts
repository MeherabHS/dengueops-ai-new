import { createHash } from "node:crypto";
import { lstat, readFile } from "node:fs/promises";
import { RuntimePublicError } from "./errors";
import { forecastOutcomePaths, monitoringPaths } from "./paths";
const sha256=(value:Buffer)=>createHash("sha256").update(value).digest("hex");
async function json(file:string){const bytes=await readFile(file);const value=JSON.parse(bytes.toString("utf8")) as Record<string,unknown>;if(!value||Array.isArray(value)||typeof value!=="object")throw new Error("object required");return {bytes,value};}
function integrity():never{throw new RuntimePublicError("forecast_outcome_integrity_error","storage","Forecast outcome evidence failed integrity verification.",409);}
export async function readVerifiedForecastOutcome(runtimeRoot:string,outcomeId:string){
  const p=forecastOutcomePaths(runtimeRoot,outcomeId);const stat=await lstat(p.committed).catch(()=>null);if(!stat?.isDirectory()||stat.isSymbolicLink())throw new RuntimePublicError("forecast_outcome_not_found","validation","The committed forecast outcome was not found.",404);
  try{const [commit,observation,evaluation,summary]=await Promise.all([json(p.commit),json(p.observation),json(p.evaluation),json(p.summary)]);const hashes=commit.value.artifactHashes as Record<string,string>;const forecastRunId=String(commit.value.forecastRunId??"");if(!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(forecastRunId))return integrity();const forecastCommit=await readFile(`${runtimeRoot}/runs/${forecastRunId}/metadata/commit.json`);
    if(commit.value.schemaVersion!=="1.0"||commit.value.status!=="committed"||commit.value.outcomeId!==outcomeId||commit.value.latestForecastPointerModified!==false||commit.value.forecastCommitSha256!==sha256(forecastCommit)||evaluation.value.forecastCommitSha256!==sha256(forecastCommit)||hashes["observation.json"]!==sha256(observation.bytes)||hashes["outcome_evaluation.json"]!==sha256(evaluation.bytes)||hashes["monitoring_summary.json"]!==sha256(summary.bytes)||evaluation.value.observationArtifactSha256!==sha256(observation.bytes)||evaluation.value.outcomeId!==outcomeId)return integrity();
    const source={observationSourceType:observation.value.observationSourceType,observationSourceId:observation.value.observationSourceId,observationRecordId:observation.value.observationRecordId,observationRecordedAt:observation.value.observationRecordedAt};
    return {outcome:evaluation.value,observation:source,summary:summary.value,integrity:{outcomeCommitSha256:sha256(commit.bytes),outcomeEvaluationSha256:sha256(evaluation.bytes),observationSha256:sha256(observation.bytes)}};
  }catch(error){if(error instanceof RuntimePublicError)throw error;return integrity();}
}
export async function readVerifiedMonitoringSummary(runtimeRoot:string,deploymentId:string){
  if(deploymentId!=="dhaka_south")throw new RuntimePublicError("monitoring_deployment_not_found","validation","The monitoring deployment is unavailable.",404);const latestPath=monitoringPaths(runtimeRoot,deploymentId).latest;
  try{const pointer=await json(latestPath);const outcomeId=String(pointer.value.outcomeId??"");const verified=await readVerifiedForecastOutcome(runtimeRoot,outcomeId);const p=forecastOutcomePaths(runtimeRoot,outcomeId);const commitBytes=await readFile(p.commit),summaryBytes=await readFile(p.summary);
    if(pointer.value.deploymentId!==deploymentId||pointer.value.outcomeCommitPath!==`forecast-outcomes/${outcomeId}/metadata/commit.json`||pointer.value.monitoringSummaryPath!==`forecast-outcomes/${outcomeId}/artifacts/monitoring_summary.json`||pointer.value.outcomeCommitSha256!==sha256(commitBytes)||pointer.value.monitoringSummarySha256!==sha256(summaryBytes)||pointer.value.policyId!=="RUNTIME.FORECAST_OUTCOME.MONITORING"||pointer.value.policyVersion!=="p1.4g-v1"||pointer.value.policySha256!==verified.summary.policySha256)return integrity();
    return {pointer:pointer.value,summary:verified.summary,latestOutcome:verified.outcome};
  }catch(error){if(error instanceof RuntimePublicError)throw error;throw new RuntimePublicError("monitoring_summary_not_found","validation","No committed monitoring summary is available.",404);}
}
