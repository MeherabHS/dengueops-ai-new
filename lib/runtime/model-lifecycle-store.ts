import "server-only";
import {createHash} from "node:crypto";
import {readdir,readFile} from "node:fs/promises";
import path from "node:path";
import {resolveActiveModel} from "./active-model";
import {validateStrictJsonSchema} from "./strict-json-schema";
import type {LifecycleAction,LifecycleAcknowledgements,LifecycleDecision,LifecycleDecisionCommit,PromotionLifecycleEvidence,VerifiedContextEvidence} from "./contracts";

const sha=(value:Buffer)=>createHash("sha256").update(value).digest("hex");
async function schema(repositoryRoot:string,name:string){return JSON.parse(await readFile(path.join(repositoryRoot,"config",name),"utf8")) as unknown}
async function verifiedDecision(repositoryRoot:string,bundle:string):Promise<{decision:LifecycleDecision;commit:LifecycleDecisionCommit}>{const decisionBytes=await readFile(path.join(bundle,"artifacts/lifecycle_decision.json")),commitBytes=await readFile(path.join(bundle,"metadata/lifecycle_decision_commit.json")),decision=JSON.parse(decisionBytes.toString("utf8")),commit=JSON.parse(commitBytes.toString("utf8"));validateStrictJsonSchema(await schema(repositoryRoot,"runtime_model_lifecycle_decision.schema.json"),decision);validateStrictJsonSchema(await schema(repositoryRoot,"runtime_model_lifecycle_decision_commit.schema.json"),commit);if(commit.lifecycleDecisionSha256!==sha(decisionBytes)||commit.lifecycleDecisionId!==decision.lifecycleDecisionId||commit.action!==decision.action)throw new Error("lifecycle_decision_commit_mismatch");return{decision:decision as unknown as LifecycleDecision,commit:commit as unknown as LifecycleDecisionCommit}}

export async function readModelLifecycleSummary(repositoryRoot:string,runtimeRoot:string,deploymentId="dhaka_south"){
 const authority=await resolveActiveModel(repositoryRoot,runtimeRoot,deploymentId),historyRoot=path.join(runtimeRoot,"model-lifecycle"),history:Array<{lifecycleDecisionId:string;action:LifecycleAction;createdAt:string;modelIdentityChanged:boolean;assignmentProduced:boolean}>=[];
 try{for(const name of await readdir(historyRoot)){const{decision}=await verifiedDecision(repositoryRoot,path.join(historyRoot,name));history.push({lifecycleDecisionId:decision.lifecycleDecisionId,action:decision.action,createdAt:decision.createdAt,modelIdentityChanged:decision.modelIdentityChanged,assignmentProduced:decision.resultingAssignmentId!==null})}}catch(error){if((error as NodeJS.ErrnoException).code!=="ENOENT")throw error}
 history.sort((a,b)=>b.createdAt.localeCompare(a.createdAt));return{authority,history:history.slice(0,20),rollbackAvailable:authority.authoritySource==="committed_assignment"&&authority.priorAssignmentId!=null,humanGoverned:true,automaticActionAllowed:false,materialWorseningStatus:"not_governed" as const,statisticalSufficiencyStatus:"not_governed" as const,modelQualificationStatus:"not_governed" as const};
}

type IdempotencyBase=LifecycleAcknowledgements&{expectedAssignmentPointerState:"absent"|"present";expectedAssignmentPointerSha256:string|null;operatorIdentifier:string;reason:string};
export type LifecycleIdempotencyInput=IdempotencyBase&(
 {action:"bootstrap_historical_profile";expectedProfileSha256:string}|
 ({action:"promote_selected_model"}&PromotionLifecycleEvidence)|
 ({action:"retain_current_model"|"reject"}&VerifiedContextEvidence)|
 {action:"reject";evidenceContextStatus:"verified_assessment_and_decision";expectedAssessmentCommitSha256:string;expectedDecisionCommitSha256:string}|
 {action:"rollback_previous_assignment"}|
 {action:"defer";evidenceContextStatus:"explicit_no_evidence"}|
 ({action:"defer"}&VerifiedContextEvidence)
);

function sameEvidence(decision:LifecycleDecision,input:LifecycleIdempotencyInput):boolean{
 if(decision.action!==input.action)return false;
 if(input.action==="bootstrap_historical_profile")return decision.action==="bootstrap_historical_profile"&&decision.profileSha256===input.expectedProfileSha256;
 if(input.action==="promote_selected_model")return decision.action==="promote_selected_model"&&decision.assessmentCommitSha256===input.expectedAssessmentCommitSha256&&decision.decisionCommitSha256===input.expectedDecisionCommitSha256&&decision.authorizationCommitSha256===input.expectedAuthorizationCommitSha256&&decision.approvedForecastCommitSha256===input.expectedApprovedForecastCommitSha256&&decision.outcomeCommitSha256===input.expectedOutcomeCommitSha256&&decision.monitoringLatestSha256===input.expectedMonitoringLatestSha256&&decision.monitoringSummarySha256===input.expectedMonitoringSummarySha256&&decision.monitoringIncludedOutcomeSetSha256===input.expectedMonitoringIncludedOutcomeSetSha256&&decision.degradationLatestSha256===input.expectedDegradationLatestSha256&&decision.degradationEvidenceCommitSha256===input.expectedDegradationEvidenceCommitSha256&&decision.degradationEvidenceSha256===input.expectedDegradationEvidenceSha256;
 if(input.action==="rollback_previous_assignment")return decision.action==="rollback_previous_assignment";
 if(input.action==="reject"&&input.evidenceContextStatus==="verified_assessment_and_decision")return decision.action==="reject"&&decision.evidenceContextStatus==="verified_assessment_and_decision"&&decision.assessmentCommitSha256===input.expectedAssessmentCommitSha256&&decision.decisionCommitSha256===input.expectedDecisionCommitSha256;
 if(input.evidenceContextStatus==="explicit_no_evidence")return decision.action==="defer"&&decision.evidenceContextStatus==="explicit_no_evidence";
 return decision.action===input.action&&"monitoringLatestSha256" in decision&&decision.monitoringLatestSha256===input.expectedMonitoringLatestSha256&&decision.monitoringSummarySha256===input.expectedMonitoringSummarySha256&&decision.monitoringIncludedOutcomeSetSha256===input.expectedMonitoringIncludedOutcomeSetSha256&&decision.degradationLatestSha256===input.expectedDegradationLatestSha256&&decision.degradationEvidenceCommitSha256===input.expectedDegradationEvidenceCommitSha256&&decision.degradationEvidenceSha256===input.expectedDegradationEvidenceSha256;
}

function canonical(value:unknown):string{if(Array.isArray(value))return`[${value.map(canonical).join(",")}]`;if(value&&typeof value==="object")return`{${Object.entries(value).sort(([a],[b])=>a.localeCompare(b)).map(([key,child])=>`${JSON.stringify(key)}:${canonical(child)}`).join(",")}}`;return JSON.stringify(value)}
export function deterministicLifecycleDecisionId(input:LifecycleIdempotencyInput):string{const digest=createHash("sha256").update(canonical({policySha256:"570a931bc2e98ca5cada78c5fe891e699e43e7c9f513b8df2257c06f1261b7bb",...input})).digest();digest[6]=(digest[6]&0x0f)|0x50;digest[8]=(digest[8]&0x3f)|0x80;const hex=digest.subarray(0,16).toString("hex");return`${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`}

export async function findLifecycleIdempotency(repositoryRoot:string,runtimeRoot:string,input:LifecycleIdempotencyInput){const root=path.join(runtimeRoot,"model-lifecycle");try{for(const name of await readdir(root)){const{decision}=await verifiedDecision(repositoryRoot,path.join(root,name));const sameBase=decision.expectedAssignmentPointerState===input.expectedAssignmentPointerState&&decision.expectedAssignmentPointerSha256===input.expectedAssignmentPointerSha256&&decision.operatorIdentifier===input.operatorIdentifier&&sameEvidence(decision,input);if(sameBase){const sameAcknowledgements=decision.manualActionAcknowledged===input.manualActionAcknowledged&&decision.statisticalSufficiencyNotGovernedAcknowledged===input.statisticalSufficiencyNotGovernedAcknowledged&&decision.materialWorseningNotClassifiedAcknowledged===input.materialWorseningNotClassifiedAcknowledged&&decision.evidenceDoesNotProveSuperiorityAcknowledged===input.evidenceDoesNotProveSuperiorityAcknowledged&&decision.quickCompatibleRandomForestOnlyAcknowledged===input.quickCompatibleRandomForestOnlyAcknowledged;return{existingId:decision.lifecycleDecisionId,conflict:decision.reason!==input.reason||!sameAcknowledgements}}}}catch(error){if((error as NodeJS.ErrnoException).code!=="ENOENT")throw error}return null}
