import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { RuntimePublicError } from "./errors";

const POLICY_ID="RUNTIME.FORECAST_OUTCOME.MONITORING" as const;
const P1_SHA="0121c2fad28b7b8e9080df52698593d1cab677febf4fa668e11f6f19541fb249" as const;
const P2_SHA="c73461e211e334733309232806fa2d41c2e5fdce7aa5e096d065e13e7525eaab" as const;
export type ForecastSourceFamily="quick_forecast_p1"|"approved_forecast_p1"|"approved_forecast_p2";
type Common={policy_id:typeof POLICY_ID;policy_status:"active";policy_sha256:string;deployment_id:"dhaka_south";geography:{level:"city";id:"BGD-DHAKA-SOUTH";name:"Dhaka South"};timezone:"Asia/Dhaka";observation_scope:{source_type:"synthetic_benchmark";source_id:"dhaka_south_synthetic_benchmark";operator_type:"trusted_internal_unverified"};formula_registry:{version:string;sha256:string;referenced_formula_ids:string[]}};
export type Phase1ForecastOutcomePolicy=Common&{schema_version:"1.0";policy_version:"p1.4g-v1";forecast_scope:Record<string,unknown>};
export type Phase2ForecastOutcomePolicy=Common&{schema_version:"2.0";policy_version:"p2-v1";source_families:Record<ForecastSourceFamily,Record<string,unknown>>;candidate_registry_sha256:string;feature_order_sha256:string;target_column:"target_cases_next_2w";forecast_horizon_weeks:2};
export type ForecastOutcomePolicy=Phase1ForecastOutcomePolicy|Phase2ForecastOutcomePolicy;
export type ForecastOutcomePolicyIdentity={schemaVersion:"1.0";policyVersion:"p1.4g-v1";policySha256:typeof P1_SHA}|{schemaVersion:"2.0";policyVersion:"p2-v1";policySha256:typeof P2_SHA};

function canonical(value:unknown):string{if(Array.isArray(value))return`[${value.map(canonical).join(",")}]`;if(value&&typeof value==="object")return`{${Object.entries(value as Record<string,unknown>).sort(([a],[b])=>a.localeCompare(b)).map(([k,v])=>`${JSON.stringify(k)}:${canonical(v)}`).join(",")}}`;return JSON.stringify(value);}
function invalid():never{throw new RuntimePublicError("forecast_outcome_policy_invalid","configuration","The governed forecast-outcome policy is unavailable or invalid.",503);}

export async function loadForecastOutcomePolicy(repositoryRoot:string,identity:ForecastOutcomePolicyIdentity={schemaVersion:"2.0",policyVersion:"p2-v1",policySha256:P2_SHA}):Promise<ForecastOutcomePolicy>{
  const phase1=identity.schemaVersion==="1.0"&&identity.policyVersion==="p1.4g-v1"&&identity.policySha256===P1_SHA;
  const phase2=identity.schemaVersion==="2.0"&&identity.policyVersion==="p2-v1"&&identity.policySha256===P2_SHA;
  if(!phase1&&!phase2)return invalid();
  const filename=phase1?"forecast_outcome_policy_p1.4g-v1.json":"forecast_outcome_policy.json";
  try{
    const policy=JSON.parse(await readFile(path.join(repositoryRoot,"config","deployments","dhaka_south",filename),"utf8")) as ForecastOutcomePolicy;
    const content={...policy} as Record<string,unknown>;delete content.policy_sha256;const digest=createHash("sha256").update(canonical(content)).digest("hex");
    const expectedSha=phase1?P1_SHA:P2_SHA,expectedVersion=phase1?"p1.4g-v1":"p2-v1",expectedSchema=phase1?"1.0":"2.0";
    if(policy.policy_id!==POLICY_ID||policy.policy_version!==expectedVersion||policy.schema_version!==expectedSchema||policy.policy_sha256!==expectedSha||digest!==expectedSha||policy.policy_status!=="active"||policy.deployment_id!=="dhaka_south")return invalid();
    if(phase2){const value=policy as Phase2ForecastOutcomePolicy;if(Object.keys(value.source_families??{}).sort().join("|")!=="approved_forecast_p1|approved_forecast_p2|quick_forecast_p1")return invalid();}
    return policy;
  }catch(error){if(error instanceof RuntimePublicError)throw error;return invalid();}
}
