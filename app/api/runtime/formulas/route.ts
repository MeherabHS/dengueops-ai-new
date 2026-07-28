import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { loadDeploymentProductScope } from "@/lib/runtime/deployment-scope";
import { errorResponse, RuntimePublicError } from "@/lib/runtime/errors";
import type { FormulaGovernanceReadResponse } from "@/lib/runtime/contracts";
import { loadRuntimeConfig } from "@/lib/runtime/config";

export const runtime = "nodejs";

const sha = (value: Buffer | string) => createHash("sha256").update(value).digest("hex");
const canonical = (value: unknown): string => Array.isArray(value)
  ? `[${value.map(canonical).join(",")}]`
  : value && typeof value === "object"
    ? `{${Object.entries(value as Record<string, unknown>).sort(([left], [right]) => left.localeCompare(right)).map(([key, child]) => `${JSON.stringify(key)}:${canonical(child)}`).join(",")}}`
    : JSON.stringify(value);
const exactKeys = (value: Record<string, unknown>, expected: string[]) =>
  Object.keys(value).sort().join("|") === [...expected].sort().join("|");

export async function GET(): Promise<Response> {
  try {
    const config = loadRuntimeConfig(false);
    const scope = await loadDeploymentProductScope(config.repositoryRoot, config.defaultDeploymentId);
    const registryPath = path.join(config.repositoryRoot, "config", "inventory_gap_formulas.json");
    const policyPath = path.join(config.repositoryRoot, "config", "deployments", scope.internalDeploymentId, "formula_activation_policy.json");
    const [registryBytes, policyBytes] = await Promise.all([readFile(registryPath), readFile(policyPath)]);
    const registry = JSON.parse(registryBytes.toString("utf8")) as Record<string, unknown>;
    const policy = JSON.parse(policyBytes.toString("utf8")) as Record<string, unknown>;
    if (
      !exactKeys(registry, ["schemaVersion", "registryVersion", "registrySha256", "supportedFormulaSlots", "formulas"])
      || registry.schemaVersion !== "1.0"
      || JSON.stringify(registry.supportedFormulaSlots) !== '["inventory.gap"]'
      || !Array.isArray(registry.formulas)
      || typeof registry.registrySha256 !== "string"
      || registry.registrySha256 !== sha(canonical(Object.fromEntries(Object.entries(registry).filter(([key]) => key !== "registrySha256"))))
    ) {
      throw new RuntimePublicError("formula_registry_tampered", "storage", "The governed formula registry failed verification.", 409);
    }
    const formulaIds = new Set<string>();
    for (const candidate of registry.formulas) {
      if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) throw new RuntimePublicError("formula_registry_tampered", "storage", "A governed formula entry is invalid.", 409);
      const formula = candidate as Record<string, unknown>;
      const fields = ["formulaId", "formulaSlot", "formulaVersion", "expression", "description", "inputs", "outputUnit", "outputDomain", "roundingPolicy", "status", "scientificLimitations", "formulaSha256"];
      const inputs = formula.inputs as unknown[];
      if (!exactKeys(formula, fields) || formula.formulaSlot !== "inventory.gap" || typeof formula.formulaId !== "string" || formulaIds.has(formula.formulaId)
        || typeof formula.expression !== "string" || Buffer.byteLength(formula.expression, "utf8") > 512 || !Array.isArray(inputs)
        || inputs.some(input => !input || typeof input !== "object" || Array.isArray(input) || !exactKeys(input as Record<string, unknown>, ["name", "unit", "domain"]))
        || !["draft", "approved", "retired"].includes(String(formula.status))
        || typeof formula.formulaSha256 !== "string"
        || formula.formulaSha256 !== sha(canonical(Object.fromEntries(Object.entries(formula).filter(([key]) => key !== "formulaSha256"))))) {
        throw new RuntimePublicError("formula_registry_tampered", "storage", "A governed formula entry failed verification.", 409);
      }
      formulaIds.add(formula.formulaId);
    }
    const policyFields = ["schemaVersion", "policyId", "policyVersion", "policyStatus", "deploymentId", "supportedFormulaSlots", "formulaBindings", "inventoryGapActivationStatus", "authorityGate", "policySha256"];
    if (
      !exactKeys(policy, policyFields)
      || policy.schemaVersion !== "1.0"
      || policy.policyId !== "RUNTIME.FORMULA.ACTIVATION"
      || policy.policyVersion !== "b8.5-v1"
      || policy.policyStatus !== "active"
      || policy.deploymentId !== scope.internalDeploymentId
      || JSON.stringify(policy.supportedFormulaSlots) !== '["inventory.gap"]'
      || !policy.formulaBindings || typeof policy.formulaBindings !== "object" || Array.isArray(policy.formulaBindings)
      || !["not_configured", "configured"].includes(String(policy.inventoryGapActivationStatus))
      || typeof policy.policySha256 !== "string"
      || policy.policySha256 !== sha(canonical(Object.fromEntries(Object.entries(policy).filter(([key]) => key !== "policySha256"))))
    ) {
      throw new RuntimePublicError("formula_policy_tampered", "storage", "The formula activation policy failed verification.", 409);
    }
    const bindings = policy.formulaBindings as Record<string, unknown>;
    const gate = policy.authorityGate as Record<string, unknown>;
    const gateFields = ["status", "resourceType", "resourceUnit", "resourcePerCase", "coefficientSourceReferenceId", "coefficientHorizon", "allocationPolicyId", "allocationApprovalReferenceId", "roundingRule", "approvedInventoryId", "formulaActivationApprovalReferenceId"];
    const configured = Object.prototype.hasOwnProperty.call(bindings, "inventory.gap");
    if (!gate || !exactKeys(gate, gateFields) || !["not_approved", "approved"].includes(String(gate.status))
      || configured !== (policy.inventoryGapActivationStatus === "configured") || Object.keys(bindings).some(slot => slot !== "inventory.gap")
      || (!configured && gate.status !== "not_approved")) {
      throw new RuntimePublicError("formula_policy_tampered", "storage", "The formula activation binding is inconsistent.", 409);
    }
    if (configured) {
      const binding = bindings["inventory.gap"] as Record<string, unknown>;
      const formula = (registry.formulas as Array<Record<string, unknown>>).find(candidate => candidate.formulaId === binding?.activeFormulaId);
      if (!binding || !exactKeys(binding, ["activeFormulaId", "activeFormulaSha256"]) || !formula
        || formula.formulaSha256 !== binding.activeFormulaSha256 || formula.status !== "approved" || gate.status !== "approved"
        || gate.resourceUnit !== formula.outputUnit || gate.roundingRule !== formula.roundingPolicy
        || gateFields.some(field => field !== "status" && (gate[field] === null || gate[field] === ""))) {
        throw new RuntimePublicError("formula_policy_tampered", "storage", "The active formula authority failed verification.", 409);
      }
    }
    const response: FormulaGovernanceReadResponse = {
      ok: true,
      internalDeploymentId: scope.internalDeploymentId,
      deploymentDisplayName: scope.deploymentDisplayName,
      evidenceScope: scope.evidenceScope,
      operationalDhakaValidation: scope.operationalDhakaValidation,
      registryVersion: String(registry.registryVersion),
      registrySha256: String(registry.registrySha256),
      registryRawSha256: sha(registryBytes),
      policyId: "RUNTIME.FORMULA.ACTIVATION",
      policyVersion: String(policy.policyVersion),
      policySha256: String(policy.policySha256),
      policyRawSha256: sha(policyBytes),
      formulaSlots: [{ formulaSlot: "inventory.gap", activationStatus: configured ? "configured" : "not_configured" }],
    };
    return Response.json(response, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const failure = errorResponse(error);
    return Response.json(failure.body, { status: failure.status, headers: { "Cache-Control": "no-store" } });
  }
}
