import "server-only";
import {createHash} from "node:crypto";
import {readFile} from "node:fs/promises";
import path from "node:path";
import {RuntimePublicError} from "./errors";

export const GOVERNED_MONITORING_POLICY_SHA="3ebf8c09d8ffa45ad6c46462580796969d80b782da8c255fac027395b1c80172" as const;
export const GOVERNED_MONITORING_POLICY_ID="RUNTIME.MODEL_DEGRADATION.EVIDENCE" as const;
export const GOVERNED_MONITORING_POLICY_VERSION="b9.d-v1" as const;

type Policy={schema_version:"1.0";policy_id:typeof GOVERNED_MONITORING_POLICY_ID;policy_version:typeof GOVERNED_MONITORING_POLICY_VERSION;policy_status:"active";policy_sha256:typeof GOVERNED_MONITORING_POLICY_SHA;deployment_id:"dhaka_south";confidence:{classification:"forecast_evidence_confidence";weights:Record<string,number>;calibration_component_weights:Record<string,number>;bands:{high_minimum:number;moderate_minimum:number};[key:string]:unknown};[key:string]:unknown};

function canonical(value:unknown):string{
  if(Array.isArray(value))return`[${value.map(canonical).join(",")}]`;
  if(value&&typeof value==="object")return`{${Object.entries(value as Record<string,unknown>).sort(([a],[b])=>a<b?-1:a>b?1:0).map(([key,item])=>`${JSON.stringify(key)}:${canonical(item)}`).join(",")}}`;
  return JSON.stringify(value);
}
function invalid():never{throw new RuntimePublicError("governed_monitoring_policy_invalid","configuration","The governed B9.D monitoring policy is unavailable or invalid.",503)}

export async function loadGovernedMonitoringPolicy(repositoryRoot:string):Promise<Policy>{
  try{
    const policy=JSON.parse(await readFile(path.join(repositoryRoot,"config","deployments","dhaka_south","model_monitoring_policy.json"),"utf8")) as Policy;
    const content={...policy} as Record<string,unknown>;delete content.policy_sha256;
    const digest=createHash("sha256").update(canonical(content)).digest("hex");
    const weights=policy.confidence?.weights??{};const weightTotal=Object.values(weights).reduce((sum,value)=>sum+Number(value),0);const calibrationTotal=Object.values(policy.confidence?.calibration_component_weights??{}).reduce((sum,value)=>sum+Number(value),0);
    if(policy.schema_version!=="1.0"||policy.policy_id!==GOVERNED_MONITORING_POLICY_ID||policy.policy_version!==GOVERNED_MONITORING_POLICY_VERSION||policy.policy_status!=="active"||policy.policy_sha256!==GOVERNED_MONITORING_POLICY_SHA||digest!==GOVERNED_MONITORING_POLICY_SHA||policy.deployment_id!=="dhaka_south"||policy.confidence?.classification!=="forecast_evidence_confidence"||Math.abs(weightTotal-1)>1e-12||Math.abs(calibrationTotal-1)>1e-12)return invalid();
    return policy;
  }catch(error){if(error instanceof RuntimePublicError)throw error;return invalid()}
}
