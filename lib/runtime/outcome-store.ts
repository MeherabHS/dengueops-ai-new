import { createHash } from "node:crypto";
import { lstat, readFile } from "node:fs/promises";
import path from "node:path";
import { RuntimePublicError } from "./errors";
import { forecastOutcomePaths, monitoringPaths } from "./paths";
const P1="0121c2fad28b7b8e9080df52698593d1cab677febf4fa668e11f6f19541fb249",P2="c73461e211e334733309232806fa2d41c2e5fdce7aa5e096d065e13e7525eaab";
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const sha256=(value:Buffer|string)=>createHash("sha256").update(value).digest("hex");
function canonical(value:unknown):string{if(Array.isArray(value))return`[${value.map(canonical).join(",")}]`;if(value&&typeof value==="object")return`{${Object.entries(value as Record<string,unknown>).sort(([a],[b])=>a.localeCompare(b)).map(([k,v])=>`${JSON.stringify(k)}:${canonical(v)}`).join(",")}}`;return JSON.stringify(value);}
async function json(file:string){const bytes=await readFile(file);const value=JSON.parse(bytes.toString("utf8")) as Record<string,any>;if(!value||Array.isArray(value)||typeof value!=="object")throw new Error("object required");return{bytes,value};}
function integrity():never{throw new RuntimePublicError("forecast_outcome_integrity_error","storage","Forecast outcome evidence failed integrity verification.",409);}
function policy(version:unknown,digest:unknown,schema:unknown){return(schema==="1.0"&&version==="p1.4g-v1"&&digest===P1)||(schema==="2.0"&&version==="p2-v1"&&digest===P2);}

export async function readVerifiedForecastOutcome(runtimeRoot:string,outcomeId:string){
  const p=forecastOutcomePaths(runtimeRoot,outcomeId);const stat=await lstat(p.committed).catch(()=>null);if(!stat?.isDirectory()||stat.isSymbolicLink())throw new RuntimePublicError("forecast_outcome_not_found","validation","The committed forecast outcome was not found.",404);
  try{
    const[commit,observation,evaluation,summary]=await Promise.all([json(p.commit),json(p.observation),json(p.evaluation),json(p.summary)]);const c=commit.value,e=evaluation.value,o=observation.value,s=summary.value,version=c.schemaVersion;
    if(!policy(c.policyVersion,c.policySha256,version)||c.status!=="committed"||c.outcomeId!==outcomeId||c.latestForecastPointerModified!==false||e.schemaVersion!==version||o.schemaVersion!==version||s.schemaVersion!==version||s.policyVersion!==c.policyVersion||s.policySha256!==c.policySha256)return integrity();
    const runId=String(c.forecastRunId??"");if(!UUID.test(runId))return integrity();const sourceRoot=path.join(runtimeRoot,"runs",runId),sourceCommit=await readFile(path.join(sourceRoot,"metadata","commit.json"));const sourceCommitValue=JSON.parse(sourceCommit.toString("utf8")) as Record<string,any>,sourceSha=sha256(sourceCommit);const outcomeSourceSha=String(e.forecastCommitSha256??e.sourceForecastCommitSha256??"");
    const hashes=c.artifactHashes as Record<string,string>;if(c.forecastCommitSha256!==sourceSha||outcomeSourceSha!==sourceSha||hashes["observation.json"]!==sha256(observation.bytes)||hashes["outcome_evaluation.json"]!==sha256(evaluation.bytes)||hashes["monitoring_summary.json"]!==sha256(summary.bytes)||e.observationArtifactSha256!==sha256(observation.bytes)||e.outcomeId!==outcomeId)return integrity();
    if(version==="1.0"&&(e.workflowMode!=="quick_forecast"||e.modelId!=="random_forest"))return integrity();
    if(version==="2.0"){
      if(!["quick_forecast_p1","approved_forecast_p1","approved_forecast_p2"].includes(e.sourceFamily)||e.sourceForecastRunId!==runId||o.sourceFamily!==e.sourceFamily||e.monitoringPolicy?.policyVersion!=="p2-v1"||e.monitoringPolicy?.policySha256!==P2||c.sourceFamily!==e.sourceFamily||c.profileModified!==false||c.authorizationModified!==false)return integrity();
      const approved=e.sourceFamily!=="quick_forecast_p1",expectedWorkflow=approved?"approved_assessment_forecast":"quick_forecast",expectedSchema=e.sourceFamily==="approved_forecast_p2"?"2.0":"1.0";if(sourceCommitValue.workflowMode!==expectedWorkflow||sourceCommitValue.schemaVersion!==expectedSchema)return integrity();
      const sourceHashes=sourceCommitValue.artifactHashes as Record<string,string>,evidence=e.sourceEvidence as Record<string,string>;const required=approved?["forecast_output.json","forecast_uncertainty.json","model_card.json"]:["forecast_output.json","forecast_uncertainty.json","forecast_calibration.json","model_card.json"];
      for(const name of required){const bytes=await readFile(path.join(sourceRoot,"artifacts",name));if(sourceHashes[name]!==sha256(bytes))return integrity();}
      if(evidence.forecastOutputSha256!==sourceHashes["forecast_output.json"]||evidence.forecastUncertaintySha256!==sourceHashes["forecast_uncertainty.json"]||evidence.modelCardSha256!==sourceHashes["model_card.json"]||(!approved&&evidence.forecastCalibrationSha256!==sourceHashes["forecast_calibration.json"]))return integrity();
    }
    const source={observationSourceType:o.observationSourceType,observationSourceId:o.observationSourceId,observationRecordId:o.observationRecordId,observationRecordedAt:o.observationRecordedAt};
    return{outcome:e,observation:source,summary:s,integrity:{outcomeCommitSha256:sha256(commit.bytes),outcomeEvaluationSha256:sha256(evaluation.bytes),observationSha256:sha256(observation.bytes)}};
  }catch(error){if(error instanceof RuntimePublicError)throw error;return integrity();}
}

export async function readVerifiedMonitoringSummary(runtimeRoot:string,deploymentId:string){
  if(deploymentId!=="dhaka_south")throw new RuntimePublicError("monitoring_deployment_not_found","validation","The monitoring deployment is unavailable.",404);const latestPath=monitoringPaths(runtimeRoot,deploymentId).latest;
  try{
    const pointer=await json(latestPath);const outcomeId=String(pointer.value.outcomeId??"");const verified=await readVerifiedForecastOutcome(runtimeRoot,outcomeId);const p=forecastOutcomePaths(runtimeRoot,outcomeId);const[commitBytes,summaryBytes]=await Promise.all([readFile(p.commit),readFile(p.summary)]);const v=pointer.value,s=verified.summary as Record<string,any>;
    if(v.deploymentId!==deploymentId||v.outcomeCommitPath!==`forecast-outcomes/${outcomeId}/metadata/commit.json`||v.monitoringSummaryPath!==`forecast-outcomes/${outcomeId}/artifacts/monitoring_summary.json`||v.outcomeCommitSha256!==sha256(commitBytes)||v.monitoringSummarySha256!==sha256(summaryBytes)||v.policyId!=="RUNTIME.FORECAST_OUTCOME.MONITORING"||!policy(v.policyVersion,v.policySha256,v.schemaVersion)||v.policyVersion!==s.policyVersion||v.policySha256!==s.policySha256)return integrity();
    const included=s.includedOutcomes as Array<{outcomeId:string;outcomeEvidenceSha256:string}>;if(!Array.isArray(included)||included.length!==s.evaluatedForecastCount)return integrity();
    const setRecords:Array<{outcomeId:string;outcomeEvidenceSha256:string;target:string;runId:string}>=[];
    for(const item of included){if(!UUID.test(item.outcomeId))return integrity();const bytes=await readFile(forecastOutcomePaths(runtimeRoot,item.outcomeId).evaluation);if(sha256(bytes)!==item.outcomeEvidenceSha256)return integrity();const value=JSON.parse(bytes.toString("utf8")) as Record<string,unknown>;setRecords.push({outcomeId:item.outcomeId,outcomeEvidenceSha256:item.outcomeEvidenceSha256,target:String(value.forecastTargetPeriod),runId:String(value.forecastRunId??value.sourceForecastRunId)});}
    const setHash=sha256(canonical(setRecords.sort((a,b)=>a.target.localeCompare(b.target)||a.runId.localeCompare(b.runId)||a.outcomeId.localeCompare(b.outcomeId)).map(({outcomeId,outcomeEvidenceSha256})=>({outcomeId,outcomeEvidenceSha256}))));if(setHash!==s.outcomeSetSha256)return integrity();
    return{pointer:v,summary:s,latestOutcome:verified.outcome};
  }catch(error){if(error instanceof RuntimePublicError)throw error;throw new RuntimePublicError("monitoring_summary_not_found","validation","No committed monitoring summary is available.",404);}
}
