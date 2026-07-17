import "server-only";
import {createHash} from "node:crypto";
import {lstat,readFile} from "node:fs/promises";
import {RuntimePublicError} from "./errors";
import {modelDegradationLatestPaths,modelDegradationPaths,monitoringPaths} from "./paths";
import {readVerifiedMonitoringSummary} from "./outcome-store";
import {ACCEPTED_MONITORING_POLICY_SHA,loadModelDegradationPolicy,MODEL_DEGRADATION_POLICY_SHA} from "./model-degradation-policy";
import type {ModelDegradationEvidence,ModelDegradationSummary} from "./contracts";

const sha256=(value:Buffer|string)=>createHash("sha256").update(value).digest("hex");
function canonical(value:unknown):string{if(Array.isArray(value))return`[${value.map(canonical).join(",")}]`;if(value&&typeof value==="object")return`{${Object.entries(value as Record<string,unknown>).sort(([a],[b])=>a.localeCompare(b)).map(([k,v])=>`${JSON.stringify(k)}:${canonical(v)}`).join(",")}}`;return JSON.stringify(value)}
async function json(path:string){const bytes=await readFile(path);const value=JSON.parse(bytes.toString("utf8")) as Record<string,any>;if(!value||Array.isArray(value)||typeof value!=="object")throw new Error("object required");return{bytes,value}}
function integrity():never{throw new RuntimePublicError("model_degradation_integrity_error","storage","Model-degradation evidence failed integrity verification.",409)}

export async function readVerifiedModelDegradationEvidence(repositoryRoot:string,runtimeRoot:string,deploymentId:string){if(deploymentId!=="dhaka_south")throw new RuntimePublicError("model_degradation_deployment_not_found","validation","Model-degradation evidence is unavailable for this deployment.",404);await loadModelDegradationPolicy(repositoryRoot);const latestPath=modelDegradationLatestPaths(runtimeRoot,deploymentId).latest;
  try{const pointer=await json(latestPath),evidenceId=String(pointer.value.evidenceId??""),paths=modelDegradationPaths(runtimeRoot,evidenceId),stat=await lstat(paths.committed);if(!stat.isDirectory()||stat.isSymbolicLink())return integrity();const[commit,evidence,summary]=await Promise.all([json(paths.commit),json(paths.evidence),json(paths.summary)]);const p=pointer.value,c=commit.value,e=evidence.value as unknown as ModelDegradationEvidence,s=summary.value as unknown as ModelDegradationSummary;
    if(p.schemaVersion!=="1.0"||p.policyId!=="RUNTIME.MODEL_DEGRADATION.EVIDENCE"||p.policyVersion!=="p2-v1"||p.policySha256!==MODEL_DEGRADATION_POLICY_SHA||p.monitoringPolicySha256!==ACCEPTED_MONITORING_POLICY_SHA||p.evidenceStatus!=="evidence_only"||p.materialWorseningStatus!=="not_governed"||p.lifecycleActionStatus!=="prohibited_not_generated")return integrity();
    if(c.status!=="committed"||c.evidenceId!==evidenceId||c.policySha256!==MODEL_DEGRADATION_POLICY_SHA||c.monitoringPolicySha256!==ACCEPTED_MONITORING_POLICY_SHA||c.monitoringLatestModified!==false||c.forecastLatestModified!==false||c.profileModified!==false||c.deploymentModelModified!==false||c.authorizationModified!==false||c.lifecycleActionProduced!==false)return integrity();
    if(p.commitSha256!==sha256(commit.bytes)||p.evidenceSha256!==sha256(evidence.bytes)||p.summarySha256!==sha256(summary.bytes)||c.artifactHashes?.["degradation_evidence.json"]!==sha256(evidence.bytes)||c.artifactHashes?.["degradation_summary.json"]!==sha256(summary.bytes))return integrity();
    if(e.evidenceId!==evidenceId||s.evidenceId!==evidenceId||e.evidenceStatus!=="evidence_only"||e.materialWorseningStatus!=="not_governed"||e.lifecycleActionStatus!=="prohibited_not_generated"||s.evidenceStatus!=="evidence_only"||s.materialWorseningStatus!=="not_governed"||s.lifecycleActionStatus!=="prohibited_not_generated")return integrity();
    const cohortSet=sha256(canonical(e.cohorts.map(value=>({cohortId:value.cohortId,outcomeSetSha256:(value as any).outcomeSetSha256}))));if(cohortSet!==e.includedCohortSetSha256||cohortSet!==s.includedCohortSetSha256||cohortSet!==c.includedCohortSetSha256)return integrity();
    for(const cohort of e.cohorts){if(cohort.monitoringWindow.status!=="window_size_not_governed"||cohort.monitoringWindow.windowOutcomeCount!==null||cohort.monitoringWindow.metricsCalculated!==false)return integrity();}
    const monitoring=await readVerifiedMonitoringSummary(runtimeRoot,deploymentId),monitoringBytes=await readFile(monitoringPaths(runtimeRoot,deploymentId).latest);if(sha256(monitoringBytes)!==c.monitoringLatestSha256||sha256(monitoringBytes)!==p.monitoringLatestInputSha256||monitoring.summary.outcomeSetSha256!==c.includedOutcomeSetSha256||monitoring.summary.outcomeSetSha256!==s.includedOutcomeSetSha256)return integrity();
    return{pointer:p,commit:c,evidence:e,summary:s};
  }catch(error){if(error instanceof RuntimePublicError)throw error;if((error as NodeJS.ErrnoException).code==="ENOENT")throw new RuntimePublicError("model_degradation_evidence_not_found","validation","No governed model-degradation evidence has been generated.",404);return integrity();}}
