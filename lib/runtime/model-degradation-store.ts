import "server-only";
import {createHash} from "node:crypto";
import {lstat,readFile} from "node:fs/promises";
import path from "node:path";
import {RuntimePublicError} from "./errors";
import {currentModelDegradationLatestPaths,modelDegradationPaths} from "./paths";
import {readVerifiedForecastOutcome} from "./outcome-store";
import {ACCEPTED_MONITORING_POLICY_SHA,loadModelDegradationPolicy,MODEL_DEGRADATION_POLICY_SHA} from "./model-degradation-policy";
import {validateStrictJsonSchema} from "./strict-json-schema";
import type {ModelDegradationEvidence,ModelDegradationSummary} from "./contracts";

const HISTORICAL_POLICY_SHA="bb13b8ec1991c0587656bf4f202334dddb115135d3ac055fee21b5f5e44f3321";
const HISTORICAL_MONITORING_SHA="c73461e211e334733309232806fa2d41c2e5fdce7aa5e096d065e13e7525eaab";
const PREVIOUS_POLICY_SHA="69db63b59f6e0dbbd5d45e98868ce0cafae1a9407d23595c89ec52491b713c98";
const PREVIOUS_MONITORING_SHA="5c3e1f7f14ab6a0a2fbc28639411a0269224b6f71746a315b9c6e159a6eacca6";
type JsonObject=Record<string,unknown>;
const sha256=(value:Buffer|string)=>createHash("sha256").update(value).digest("hex");
function canonical(value:unknown):string{if(Array.isArray(value))return`[${value.map(canonical).join(",")}]`;if(value&&typeof value==="object")return`{${Object.entries(value as Record<string,unknown>).sort(([a],[b])=>a<b?-1:a>b?1:0).map(([k,v])=>`${JSON.stringify(k)}:${canonical(v)}`).join(",")}}`;return JSON.stringify(value)}
async function json(file:string){const bytes=await readFile(file);const value=JSON.parse(bytes.toString("utf8")) as JsonObject;if(!value||Array.isArray(value)||typeof value!=="object")throw new Error("object required");return{bytes,value}}
async function schema(repositoryRoot:string,name:string){return JSON.parse(await readFile(path.join(repositoryRoot,"config",name),"utf8")) as unknown}
function integrity():never{throw new RuntimePublicError("model_degradation_integrity_error","storage","Model-degradation evidence failed integrity verification.",409)}
function contained(runtimeRoot:string,relative:string):string{if(!relative||relative.includes("\\")||path.isAbsolute(relative)||relative.split("/").includes(".."))return integrity();const root=path.resolve(runtimeRoot),candidate=path.resolve(root,relative);if(candidate!==root&&!candidate.startsWith(root+path.sep))return integrity();return candidate}

async function verifyIncludedOutcomes(runtimeRoot:string,commit:JsonObject,summary:JsonObject){
  const included=summary.includedOutcomes as Array<{outcomeId:string;outcomeEvidenceSha256:string}>,committed=commit.includedOutcomes as Array<{outcomeId:string;outcomeCommitSha256:string;outcomeEvidenceSha256:string}>;
  if(!Array.isArray(included)||!Array.isArray(committed)||included.length!==summary.evaluatedForecastCount||included.length!==committed.length)return integrity();
  const commitById=new Map(committed.map(value=>[value.outcomeId,value])),setRecords:Array<{outcomeId:string;outcomeEvidenceSha256:string;target:string;runId:string}>=[];
  for(const item of included){
    const bound=commitById.get(item.outcomeId);if(!bound||bound.outcomeEvidenceSha256!==item.outcomeEvidenceSha256)return integrity();
    let verified;
    try{verified=await readVerifiedForecastOutcome(runtimeRoot,item.outcomeId)}catch{return integrity()}
    const outcome=verified.outcome as JsonObject;
    if(verified.integrity.outcomeCommitSha256!==bound.outcomeCommitSha256||verified.integrity.outcomeEvaluationSha256!==item.outcomeEvidenceSha256)return integrity();
    if(outcome.sourceFamily==="quick_forecast_p2"){
      const runId=String(outcome.sourceForecastRunId),run=JSON.parse((await readFile(path.join(runtimeRoot,"runs",runId,"metadata","run.json"))).toString("utf8")) as JsonObject,provenance=(outcome.sourceEvidence as JsonObject|undefined)?.assignmentProvenance;
      const expected={assignmentId:run.assignmentId,assignmentCommitSha256:run.assignmentCommitSha256,assignmentAction:run.assignmentAction,authoritySnapshotSha256:run.authoritySnapshotSha256,lifecyclePolicy:{policyId:run.lifecyclePolicyId,policyVersion:run.lifecyclePolicyVersion,policySha256:run.lifecyclePolicySha256}};
      if(canonical(provenance)!==canonical(expected))return integrity();
    }
    setRecords.push({outcomeId:item.outcomeId,outcomeEvidenceSha256:item.outcomeEvidenceSha256,target:String(outcome.forecastTargetPeriod),runId:String(outcome.forecastRunId??outcome.sourceForecastRunId)});
  }
  const setHash=sha256(canonical(setRecords.sort((a,b)=>a.target.localeCompare(b.target)||a.runId.localeCompare(b.runId)||a.outcomeId.localeCompare(b.outcomeId)).map(({outcomeId,outcomeEvidenceSha256})=>({outcomeId,outcomeEvidenceSha256}))));
  if(setHash!==summary.outcomeSetSha256||setHash!==commit.includedOutcomeSetSha256)return integrity();
}

async function verifyBundle(repositoryRoot:string,runtimeRoot:string,evidenceId:string){
  const paths=modelDegradationPaths(runtimeRoot,evidenceId),stat=await lstat(paths.committed).catch(()=>null);if(!stat?.isDirectory()||stat.isSymbolicLink())throw new RuntimePublicError("model_degradation_evidence_not_found","validation","The committed model-degradation evidence was not found.",404);
  const[commit,evidence,summary]=await Promise.all([json(paths.commit),json(paths.evidence),json(paths.summary)]);
  validateStrictJsonSchema(await schema(repositoryRoot,"runtime_model_degradation_commit.schema.json"),commit.value);
  validateStrictJsonSchema(await schema(repositoryRoot,"runtime_model_degradation_evidence.schema.json"),evidence.value);
  validateStrictJsonSchema(await schema(repositoryRoot,"runtime_model_degradation_summary.schema.json"),summary.value);
  const c=commit.value,e=evidence.value as unknown as ModelDegradationEvidence,s=summary.value as unknown as ModelDegradationSummary,version=c.schemaVersion,artifactHashes=c.artifactHashes as Record<string,string>;
  if(c.evidenceId!==evidenceId||e.evidenceId!==evidenceId||s.evidenceId!==evidenceId||c.status!=="committed"||c.monitoringLatestModified!==false||c.forecastLatestModified!==false||c.profileModified!==false||c.deploymentModelModified!==false||c.authorizationModified!==false||c.lifecycleActionProduced!==false)return integrity();
  const evidenceSha=sha256(evidence.bytes),summarySha=sha256(summary.bytes);if(artifactHashes["degradation_evidence.json"]!==evidenceSha||artifactHashes["degradation_summary.json"]!==summarySha)return integrity();
  if(e.evidenceStatus!=="evidence_only"||e.materialWorseningStatus!=="not_governed"||(version==="2.0"&&e.lifecycleActionProduced!==false)||e.lifecycleActionStatus!=="prohibited_not_generated"||s.evidenceStatus!=="evidence_only"||s.materialWorseningStatus!=="not_governed"||s.lifecycleActionStatus!=="prohibited_not_generated")return integrity();
  const cohortSet=sha256(canonical(e.cohorts.map(value=>({cohortId:value.cohortId,outcomeSetSha256:value.outcomeSetSha256}))));if(cohortSet!==e.includedCohortSetSha256||cohortSet!==s.includedCohortSetSha256||cohortSet!==c.includedCohortSetSha256)return integrity();
  let monitoringSummary:JsonObject;
  if(version==="2.0"){
    const current=c.policyVersion==="p2-v3"&&c.policySha256===MODEL_DEGRADATION_POLICY_SHA&&c.monitoringPolicyVersion==="p2-v3"&&c.monitoringPolicySha256===ACCEPTED_MONITORING_POLICY_SHA;
    const previous=c.policyVersion==="p2-v2"&&c.policySha256===PREVIOUS_POLICY_SHA&&c.monitoringPolicyVersion==="p2-v2"&&c.monitoringPolicySha256===PREVIOUS_MONITORING_SHA;
    if((!current&&!previous)||e.schemaVersion!=="2.0"||s.schemaVersion!=="2.0")return integrity();
    const expectedPolicyVersion=current?"p2-v3":"p2-v2",expectedMonitoringSha=current?ACCEPTED_MONITORING_POLICY_SHA:PREVIOUS_MONITORING_SHA;
    const snapshot=await json(paths.monitoringLatestSnapshot);validateStrictJsonSchema(await schema(repositoryRoot,"runtime_monitoring_latest.schema.json"),snapshot.value);
    if(snapshot.value.schemaVersion!=="2.1"||snapshot.value.policyVersion!==expectedPolicyVersion||snapshot.value.policySha256!==expectedMonitoringSha||sha256(snapshot.bytes)!==c.monitoringLatestSnapshotSha256||sha256(snapshot.bytes)!==artifactHashes["monitoring_latest_snapshot.json"]||e.monitoringInput.latestSnapshotSha256!==sha256(snapshot.bytes))return integrity();
    if(c.monitoringLatestSnapshotPath!==`degradation-evidence/${evidenceId}/artifacts/monitoring_latest_snapshot.json`)return integrity();
    const summaryPath=contained(runtimeRoot,String(snapshot.value.monitoringSummaryPath)),monitoring=await json(summaryPath);validateStrictJsonSchema(await schema(repositoryRoot,"runtime_monitoring_summary.schema.json"),monitoring.value);
    if(snapshot.value.monitoringSummarySha256!==sha256(monitoring.bytes)||c.monitoringSummarySha256!==sha256(monitoring.bytes)||e.monitoringInput.summarySha256!==sha256(monitoring.bytes)||monitoring.value.schemaVersion!=="2.1"||monitoring.value.policyVersion!==expectedPolicyVersion||monitoring.value.policySha256!==expectedMonitoringSha)return integrity();
    monitoringSummary=monitoring.value;
    for(const cohort of e.cohorts){
      if(cohort.monitoringWindow.status!=="window_size_not_governed"||cohort.monitoringWindow.windowOutcomeCount!==null||cohort.monitoringWindow.metricsCalculated!==false||cohort.monitoringWindow.statisticalSufficiencyStatus!=="not_governed")return integrity();
      const pointOnly=cohort.identity.forecastPresentationMode==="point_only"&&cohort.identity.calibrationStatus==="unavailable",interval=cohort.identity.forecastPresentationMode==="point_and_interval"&&cohort.identity.calibrationStatus==="governed_available";
      if(pointOnly&&(cohort.actualPopulation.rangeEligibleCount!==0||cohort.actualPopulation.empiricalCoverage!==null||!cohort.warnings.includes("range_metric_unavailable")))return integrity();
      if(interval&&(cohort.actualPopulation.rangeEligibleCount<1||cohort.actualPopulation.empiricalCoverage===null))return integrity();
    }
  }else if(version==="1.0"){
    if(c.policyVersion!=="p2-v1"||c.policySha256!==HISTORICAL_POLICY_SHA||c.monitoringPolicyVersion!=="p2-v1"||c.monitoringPolicySha256!==HISTORICAL_MONITORING_SHA)return integrity();
    const monitoring=await json(contained(runtimeRoot,String(c.monitoringSummaryPath)));if(sha256(monitoring.bytes)!==c.monitoringSummarySha256)return integrity();monitoringSummary=monitoring.value;
  }else return integrity();
  if(monitoringSummary.outcomeSetSha256!==c.includedOutcomeSetSha256||monitoringSummary.outcomeSetSha256!==s.includedOutcomeSetSha256||monitoringSummary.outcomeSetSha256!==e.monitoringInput.includedOutcomeSetSha256)return integrity();
  await verifyIncludedOutcomes(runtimeRoot,c,monitoringSummary);
  return{commit:c,evidence:e,summary:s,integrity:{commitSha256:sha256(commit.bytes),evidenceSha256:evidenceSha,summarySha256:summarySha,monitoringLatestSnapshotSha256:version==="2.0"?c.monitoringLatestSnapshotSha256:null}};
}

export async function readVerifiedModelDegradationEvidenceById(repositoryRoot:string,runtimeRoot:string,deploymentId:string,evidenceId:string){
  if(deploymentId!=="dhaka_south")throw new RuntimePublicError("model_degradation_deployment_not_found","validation","Model-degradation evidence is unavailable for this deployment.",404);
  try{return await verifyBundle(repositoryRoot,runtimeRoot,evidenceId)}catch(error){if(error instanceof RuntimePublicError)throw error;return integrity()}
}

export async function readVerifiedCurrentModelDegradationEvidence(repositoryRoot:string,runtimeRoot:string,deploymentId:string){
  if(deploymentId!=="dhaka_south")throw new RuntimePublicError("model_degradation_deployment_not_found","validation","Model-degradation evidence is unavailable for this deployment.",404);await loadModelDegradationPolicy(repositoryRoot);
  const latestPath=currentModelDegradationLatestPaths(runtimeRoot,deploymentId).latest;
  try{
    const pointer=await json(latestPath);validateStrictJsonSchema(await schema(repositoryRoot,"runtime_model_degradation_latest.schema.json"),pointer.value);const p=pointer.value,evidenceId=String(p.evidenceId??"");
    if(p.schemaVersion!=="2.0"||p.policyVersion!=="p2-v3"||p.policySha256!==MODEL_DEGRADATION_POLICY_SHA)return integrity();
    const verified=await verifyBundle(repositoryRoot,runtimeRoot,evidenceId),c=verified.commit;
    if(p.commitPath!==`degradation-evidence/${evidenceId}/metadata/commit.json`||p.evidencePath!==`degradation-evidence/${evidenceId}/artifacts/degradation_evidence.json`||p.summaryPath!==`degradation-evidence/${evidenceId}/artifacts/degradation_summary.json`||p.monitoringLatestSnapshotPath!==`degradation-evidence/${evidenceId}/artifacts/monitoring_latest_snapshot.json`)return integrity();
    if(p.commitSha256!==verified.integrity.commitSha256||p.evidenceSha256!==verified.integrity.evidenceSha256||p.summarySha256!==verified.integrity.summarySha256||p.monitoringLatestSnapshotSha256!==verified.integrity.monitoringLatestSnapshotSha256||p.monitoringSummarySha256!==c.monitoringSummarySha256||p.includedOutcomeSetSha256!==c.includedOutcomeSetSha256)return integrity();
    return{pointer:p,...verified};
  }catch(error){if(error instanceof RuntimePublicError)throw error;if((error as NodeJS.ErrnoException).code==="ENOENT")throw new RuntimePublicError("model_degradation_evidence_not_found","validation","No governed model-degradation evidence has been generated.",404);return integrity()}
}

export const readVerifiedModelDegradationEvidence=readVerifiedCurrentModelDegradationEvidence;
