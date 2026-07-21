import "server-only";
import {createHash} from "node:crypto";
import {readFile} from "node:fs/promises";
import path from "node:path";
import {RuntimePublicError} from "./errors";
import {validateStrictJsonSchema} from "./strict-json-schema";



export const MODEL_LIFECYCLE_POLICY_SHA="570a931bc2e98ca5cada78c5fe891e699e43e7c9f513b8df2257c06f1261b7bb" as const;
export const LIFECYCLE_RF_PARAMETER_SHA="ac37d2d2947de2f6004d39ecdfa3290c5d65901b796f1eb1fd248ad658e1b1e0" as const;
export const LIFECYCLE_FEATURE_ORDER_SHA="aeccbe517da452e1132f08c02599418523fb003280b11ff9cda66cfb3aa55a85" as const;
export const LIFECYCLE_CANDIDATE_REGISTRY_SHA="2e627f8a368a7e92cebd4ad62139b1050c7614559affd620e9a41738fd6a25d4" as const;
export const LIFECYCLE_QUICK_POLICY_SHA="5e6bcb68e5f29a50f8d377892d7786cc1932b3435e8a0b709a363d6c2e42bb9a" as const;
export const LIFECYCLE_QUICK_POLICY_RAW_SHA="02e31f11addfb5e59e1b3d276148bface284383dcd404e2a6370e27cd8e7dd45" as const;
export const LIFECYCLE_PROFILE_SHA="53fe1fb09aea994c34a5b3d6839b60092c777030445b8ec46c32520675a7233a" as const;
function canonical(v:unknown):string{if(Array.isArray(v))return`[${v.map(canonical).join(",")}]`;if(v&&typeof v==="object")return`{${Object.entries(v as Record<string,unknown>).sort(([a],[b])=>a.localeCompare(b)).map(([k,x])=>`${JSON.stringify(k)}:${canonical(x)}`).join(",")}}`;return JSON.stringify(v)}
function sha(data: Buffer | string): string { return createHash("sha256").update(data).digest("hex"); }

export async function loadModelLifecyclePolicyByIdentity(params: {
  repositoryRoot: string;
  deploymentId?: string;
  policyId: string;
  policyVersion: string;
  expectedCanonicalSha256: string;
  expectedRawSha256?: string;
}) {
  const deploymentId = params.deploymentId || "dhaka_south";
  if (params.policyId !== "RUNTIME.MODEL_LIFECYCLE.DECISION") {
    throw new RuntimePublicError("model_lifecycle_policy_invalid", "configuration", `Unsupported policy_id '${params.policyId}'`, 503);
  }

  let filePath: string;
  if (params.policyVersion === "p2-v1") {
    filePath = path.join(params.repositoryRoot, "config", "deployments", deploymentId, "model_lifecycle_policy_p2-v1.json");
  } else if (params.policyVersion === "p2-v2") {
    filePath = path.join(params.repositoryRoot, "config", "deployments", deploymentId, "model_lifecycle_policy.json");
  } else {
    throw new RuntimePublicError("model_lifecycle_policy_invalid", "configuration", `Unknown policy version '${params.policyVersion}'`, 503);
  }

  try {
    const rawBuffer = await readFile(filePath);
    if (params.expectedRawSha256) {
      const computedRaw = sha(rawBuffer);
      if (computedRaw !== params.expectedRawSha256) {
        throw new Error(`Raw policy SHA-256 mismatch: expected ${params.expectedRawSha256}, got ${computedRaw}`);
      }
    }

    const value = JSON.parse(rawBuffer.toString("utf8")) as Record<string, any>;
    const declId = value.policy_id || value.policyId;
    const declVer = value.policy_version || value.policyVersion;
    const declHash = value.policy_sha256 || value.policySha256;

    if (declId !== params.policyId || declVer !== params.policyVersion) {
      throw new Error("Declared policy identity mismatch.");
    }

    const content = { ...value };
    delete content.policy_sha256;
    delete content.policySha256;
    const computedCanonical = createHash("sha256").update(canonical(content)).digest("hex");

    if (declHash !== computedCanonical) {
      throw new Error(`Embedded canonical policy hash mismatch: declared ${declHash}, recomputed ${computedCanonical}`);
    }

    if (computedCanonical !== params.expectedCanonicalSha256) {
      throw new Error(`Expected canonical policy hash mismatch: expected ${params.expectedCanonicalSha256}, got ${computedCanonical}`);
    }

    if (params.policyVersion === "p2-v2") {
      const schema = JSON.parse(await readFile(path.join(params.repositoryRoot, "config", "runtime_model_lifecycle_policy.schema.json"), "utf8"));
      validateStrictJsonSchema(schema, value);
    }

    return value;
  } catch (error) {
    if (error instanceof RuntimePublicError) throw error;
    throw new RuntimePublicError("model_lifecycle_policy_invalid", "configuration", "The governed model lifecycle policy is unavailable or invalid.", 503);
  }
}

export async function loadModelLifecyclePolicy(params: {
  repositoryRoot: string;
  deploymentId?: string;
  version: "p2-v1" | "p2-v2";
}) {
  const deploymentId = params.deploymentId || "dhaka_south";
  let expectedCanonicalHash: string;
  if (params.version === "p2-v1") {
    expectedCanonicalHash = MODEL_LIFECYCLE_POLICY_SHA;
  } else {
    const raw = JSON.parse(await readFile(path.join(params.repositoryRoot, "config", "deployments", deploymentId, "model_lifecycle_policy.json"), "utf8"));
    const content = { ...raw };
    delete content.policy_sha256;
    delete content.policySha256;
    expectedCanonicalHash = createHash("sha256").update(canonical(content)).digest("hex");
  }

  return loadModelLifecyclePolicyByIdentity({
    repositoryRoot: params.repositoryRoot,
    deploymentId,
    policyId: "RUNTIME.MODEL_LIFECYCLE.DECISION",
    policyVersion: params.version,
    expectedCanonicalSha256: expectedCanonicalHash
  });
}

export async function loadCurrentModelLifecyclePolicy(repositoryRoot: string, deploymentId: string = "dhaka_south") {
  return loadModelLifecyclePolicy({
    repositoryRoot,
    deploymentId,
    version: "p2-v2"
  });
}
