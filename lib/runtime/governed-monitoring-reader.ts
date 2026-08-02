import "server-only";
import {createHash} from "node:crypto";
import {readFile} from "node:fs/promises";
import path from "node:path";
import type {MonitoringViewModel} from "@/lib/dashboard-view-model";
import {governedModelLabel} from "@/lib/status-labels";
import {RuntimePublicError} from "./errors";
import {assertContained} from "./paths";
import {GOVERNED_MONITORING_POLICY_ID,GOVERNED_MONITORING_POLICY_SHA,GOVERNED_MONITORING_POLICY_VERSION,loadGovernedMonitoringPolicy} from "./governed-monitoring-policy";
import type {VerifiedCurrentForecast} from "./dashboard-reader";

type JsonObject=Record<string,unknown>;
const SHA=/^[a-f0-9]{64}$/;const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const sha=(value:Buffer)=>createHash("sha256").update(value).digest("hex");
function object(value:unknown):JsonObject{if(!value||typeof value!=="object"||Array.isArray(value))throw new Error("object");return value as JsonObject}
function text(value:unknown):string{if(typeof value!=="string")throw new Error("string");return value}
function modelLabel(value:unknown):string|null{if(value===null||value===undefined)return null;const label=governedModelLabel(text(value));if(!label)throw new Error("model");return label}
function unavailable(reason:string):MonitoringViewModel{return{availabilityStatus:"unavailable",reason,confidence:{status:"unavailable",score:null,band:null,reasonCodes:["monitoring_unavailable"]},featureDrift:{status:"unavailable",maximumPsi:null,materialFeatureCount:0},performanceDrift:{status:"unavailable",matureOutcomeCount:0},rankingInstability:{status:"unavailable",winnerChanged:false,currentTechnicalWinner:null,latestTechnicalWinner:null},recommendation:{state:"not_recommended",reasonCodes:[],actionHref:"/forecast?intent=reassess"},technicalEvidence:null}}

export async function readCurrentGovernedMonitoring(runtimeRoot:string,repositoryRoot:string,verified:VerifiedCurrentForecast):Promise<MonitoringViewModel>{
  const pointerPath=path.join(runtimeRoot,"deployments","dhaka_south","degradation","latest_b9-d-v1.json");
  let pointerBytes:Buffer;
  try{pointerBytes=await readFile(pointerPath)}catch(error){if((error as NodeJS.ErrnoException).code==="ENOENT")return unavailable("Monitoring has not yet been generated for this forecast.");throw error}
  try{
    await loadGovernedMonitoringPolicy(repositoryRoot);
    const pointer=object(JSON.parse(pointerBytes.toString("utf8")));
    if(pointer.schemaVersion!=="1.0"||pointer.deploymentId!=="dhaka_south"||pointer.policyId!==GOVERNED_MONITORING_POLICY_ID||pointer.policyVersion!==GOVERNED_MONITORING_POLICY_VERSION||pointer.policySha256!==GOVERNED_MONITORING_POLICY_SHA||!UUID.test(text(pointer.monitoringId))||!SHA.test(text(pointer.evidenceSha256))||!SHA.test(text(pointer.commitSha256)))throw new Error("pointer");
    if(pointer.forecastRunId!==verified.pointer.runId||pointer.datasetId!==verified.pointer.datasetId||pointer.forecastLatestSha256!==verified.pointerSha256)throw new RuntimePublicError("governed_monitoring_stale","storage","Monitoring evidence is stale for the current forecast.",409);
    const assignmentPointerPath=path.join(runtimeRoot,"deployments","dhaka_south","model-assignment","latest.json");
    const assignmentPointerBytes=await readFile(assignmentPointerPath);
    if(pointer.assignmentPointerSha256!==sha(assignmentPointerBytes))throw new RuntimePublicError("governed_monitoring_stale","storage","Monitoring evidence is stale for the current assignment.",409);
    const evidencePath=assertContained(runtimeRoot,path.join(runtimeRoot,text(pointer.evidencePath)));
    const commitPath=assertContained(runtimeRoot,path.join(runtimeRoot,text(pointer.commitPath)));
    const [evidenceBytes,commitBytes]=await Promise.all([readFile(evidencePath),readFile(commitPath)]);
    if(sha(evidenceBytes)!==pointer.evidenceSha256||sha(commitBytes)!==pointer.commitSha256)throw new Error("artifact hash");
    const evidence=object(JSON.parse(evidenceBytes.toString("utf8")));const commit=object(JSON.parse(commitBytes.toString("utf8")));
    const authority=object(evidence.authority);const policy=object(evidence.policy);
    if(evidence.schemaVersion!=="1.0"||evidence.monitoringId!==pointer.monitoringId||policy.policyId!==GOVERNED_MONITORING_POLICY_ID||policy.policyVersion!==GOVERNED_MONITORING_POLICY_VERSION||policy.policySha256!==GOVERNED_MONITORING_POLICY_SHA||authority.authoritySnapshotSha256!==pointer.authoritySnapshotSha256||authority.assignmentId!==pointer.assignmentId||authority.assignmentPointerSha256!==pointer.assignmentPointerSha256||authority.forecastRunId!==pointer.forecastRunId||authority.forecastLatestSha256!==pointer.forecastLatestSha256||authority.forecastCommitSha256!==verified.commitSha256||authority.datasetId!==pointer.datasetId)throw new Error("authority");
    if(commit.schemaVersion!=="1.0"||commit.monitoringId!==pointer.monitoringId||commit.policySha256!==GOVERNED_MONITORING_POLICY_SHA||commit.authoritySnapshotSha256!==pointer.authoritySnapshotSha256||commit.evidenceSha256!==pointer.evidenceSha256||commit.status!=="committed"||commit.assignmentModified!==false||commit.forecastModified!==false||commit.preparednessModified!==false)throw new Error("commit");
    const feature=object(evidence.featureDrift);const performance=object(evidence.performanceDrift);const ranking=object(evidence.rankingInstability);const recommendation=object(evidence.recommendation);const confidence=object(evidence.confidence);const invariants=object(evidence.invariants);
    if(invariants.confidenceScoreChangesModelSelection!==false||invariants.confidenceAffectsForecastPoint!==false||invariants.confidenceAffectsPredictionInterval!==false||invariants.confidenceAffectsPreparedness!==false||invariants.reassessmentAutoStarted!==false||invariants.modelAutoReassigned!==false)throw new Error("invariants");
    const confidenceStatus=confidence.status;if(confidenceStatus!=="available"&&confidenceStatus!=="unavailable")throw new Error("confidence");
    const score=confidenceStatus==="available"?Number(confidence.score):null;const band=confidenceStatus==="available"?text(confidence.band) as "high"|"moderate"|"low":null;
    if(confidenceStatus==="available"&&(score===null||!Number.isInteger(score)||score<0||score>100||!["high","moderate","low"].includes(String(band))))throw new Error("confidence score");
    return{availabilityStatus:"available",reason:null,
      confidence:{status:confidenceStatus,score,band,reasonCodes:Array.isArray(confidence.reasonCodes)?confidence.reasonCodes.map(String):[]},
      featureDrift:{status:text(feature.status) as MonitoringViewModel["featureDrift"]["status"],maximumPsi:typeof feature.maximumValue==="number"?feature.maximumValue:null,materialFeatureCount:Number(feature.materialFeatureCount??0)},
      performanceDrift:{status:text(performance.status) as MonitoringViewModel["performanceDrift"]["status"],matureOutcomeCount:Number(performance.matureOutcomeCount??0)},
      rankingInstability:{status:text(ranking.status) as MonitoringViewModel["rankingInstability"]["status"],winnerChanged:ranking.winnerChanged===true,currentTechnicalWinner:modelLabel(ranking.sourceTechnicalWinnerId),latestTechnicalWinner:modelLabel(ranking.latestTechnicalWinnerId)},
      recommendation:{state:text(recommendation.state) as MonitoringViewModel["recommendation"]["state"],reasonCodes:Array.isArray(recommendation.reasonCodes)?recommendation.reasonCodes.map(String):[],actionHref:"/forecast?intent=reassess"},
      technicalEvidence:{monitoringId:text(evidence.monitoringId),policyId:GOVERNED_MONITORING_POLICY_ID,policyVersion:GOVERNED_MONITORING_POLICY_VERSION,policySha256:GOVERNED_MONITORING_POLICY_SHA,authoritySnapshotSha256:text(authority.authoritySnapshotSha256),components:object(confidence.components??{}),weights:object(confidence.appliedWeights??{})}
    };
  }catch(error){if(error instanceof RuntimePublicError)throw error;throw new RuntimePublicError("governed_monitoring_integrity_error","storage","Current monitoring evidence failed integrity verification.",409)}
}
