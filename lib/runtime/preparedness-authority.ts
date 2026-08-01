import "server-only";

import {createHash} from "node:crypto";
import {readFile} from "node:fs/promises";
import path from "node:path";
import {loadRuntimeConfig} from "./config";
import {RuntimePublicError} from "./errors";
import {readVerifiedCurrentForecast} from "./dashboard-reader";
import {readVerifiedCurrentHospitalInventory} from "./hospital-inventory-reader";

type Json=Record<string,unknown>;
const sha=(value:Buffer|string)=>createHash("sha256").update(value).digest("hex");
const canonical=(value:unknown):string=>Array.isArray(value)?`[${value.map(canonical).join(",")}]`:value&&typeof value==="object"?`{${Object.entries(value as Json).sort(([a],[b])=>a<b?-1:a>b?1:0).map(([key,child])=>`${JSON.stringify(key)}:${canonical(child)}`).join(",")}}`:JSON.stringify(value);
const object=(value:unknown):Json=>{if(!value||typeof value!=="object"||Array.isArray(value))throw new Error("object");return value as Json};
const without=(value:Json,key:string):Json=>Object.fromEntries(Object.entries(value).filter(([candidate])=>candidate!==key));

export interface CurrentPreparednessAuthority{snapshot:Json;authoritySnapshotSha256:string;formula:Json;formulaPolicy:Json;planningPolicy:Json;forecast:Awaited<ReturnType<typeof readVerifiedCurrentForecast>>;inventory:Awaited<ReturnType<typeof readVerifiedCurrentHospitalInventory>>}

export async function resolveCurrentPreparednessAuthority():Promise<CurrentPreparednessAuthority>{
  const config=loadRuntimeConfig(false);const deploymentId="dhaka_south";
  const registryPath=process.env.DENGUEOPS_OPERATIONAL_FORMULA_REGISTRY_PATH||path.join(config.repositoryRoot,"config","inventory_gap_formulas.json");
  const formulaPolicyPath=process.env.DENGUEOPS_OPERATIONAL_FORMULA_POLICY_PATH||path.join(config.repositoryRoot,"config","deployments",deploymentId,"formula_activation_policy.json");
  const planningPath=process.env.DENGUEOPS_OPERATIONAL_PLANNING_POLICY_PATH||path.join(config.repositoryRoot,"config","deployments",deploymentId,"operational_preparedness_policy.json");
  try{
    const [registryBytes,formulaPolicyBytes,planningBytes,forecast,inventory]=await Promise.all([readFile(registryPath),readFile(formulaPolicyPath),readFile(planningPath),readVerifiedCurrentForecast(config.runtimeRoot,deploymentId),readVerifiedCurrentHospitalInventory(config.runtimeRoot,deploymentId)]);
    const registry=object(JSON.parse(registryBytes.toString("utf8")));const formulaPolicy=object(JSON.parse(formulaPolicyBytes.toString("utf8")));const planningPolicy=object(JSON.parse(planningBytes.toString("utf8")));
    if(registry.registrySha256!==sha(canonical(without(registry,"registrySha256")))||formulaPolicy.policySha256!==sha(canonical(without(formulaPolicy,"policySha256")))||planningPolicy.policySha256!==sha(canonical(without(planningPolicy,"policySha256"))))throw new Error("governance hash");
    const bindings=object(formulaPolicy.formulaBindings);const binding=object(bindings["inventory.gap"]);const formulas=registry.formulas;if(!Array.isArray(formulas))throw new Error("formula registry");
    const formula=object(formulas.find(candidate=>object(candidate).formulaId===binding.activeFormulaId));const gate=object(formulaPolicy.authorityGate);
    if(formula.formulaSha256!==sha(canonical(without(formula,"formulaSha256")))||formula.formulaSha256!==binding.activeFormulaSha256||formula.formulaSlot!=="inventory.gap"||formula.status!=="approved"||formulaPolicy.inventoryGapActivationStatus!=="configured"||gate.status!=="approved"||gate.approvedInventoryId!==inventory.inventory.inventoryId||planningPolicy.operationalUseAllowed!==true||planningPolicy.forecastRequirement!=="exact_current_committed")throw new Error("governance binding");
    const snapshot:Json={deploymentId,forecastRunId:forecast.pointer.runId,forecastCommitSha256:forecast.pointer.commitRecordSha256,forecastPointerSha256:forecast.pointerSha256,formulaId:formula.formulaId,formulaVersion:formula.formulaVersion,formulaSha256:formula.formulaSha256,formulaRegistrySha256:registry.registrySha256,formulaRegistryRawSha256:sha(registryBytes),formulaActivationPolicyId:formulaPolicy.policyId,formulaActivationPolicyVersion:formulaPolicy.policyVersion,formulaActivationPolicySha256:formulaPolicy.policySha256,formulaActivationPolicyRawSha256:sha(formulaPolicyBytes),planningPolicyId:planningPolicy.policyId,planningPolicyVersion:planningPolicy.policyVersion,planningPolicySha256:planningPolicy.policySha256,inventoryId:inventory.inventory.inventoryId,inventoryArtifactSha256:inventory.inventoryRawSha256,inventoryCommitSha256:inventory.commitSha256,inventoryPointerSha256:inventory.pointerSha256};
    return{snapshot,authoritySnapshotSha256:sha(canonical(snapshot)),formula,formulaPolicy,planningPolicy,forecast,inventory};
  }catch(error){if(error instanceof RuntimePublicError)throw error;throw new RuntimePublicError("preparedness_authority_unavailable","configuration","The current operational preparedness authorities failed verification.",503,true)}
}
