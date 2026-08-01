import "server-only";

import {createHash} from "node:crypto";
import {readFile} from "node:fs/promises";
import {loadRuntimeConfig} from "./config";
import {RuntimePublicError} from "./errors";
import {operationalPreparednessPaths} from "./paths";
import {resolveCurrentPreparednessAuthority} from "./preparedness-authority";
import {validateStrictJsonSchema} from "./strict-json-schema";

type Json=Record<string,unknown>;
const sha=(value:Buffer)=>createHash("sha256").update(value).digest("hex");
const object=(value:unknown):Json=>{if(!value||typeof value!=="object"||Array.isArray(value))throw new Error("object");return value as Json};

export interface VerifiedOperationalPreparedness{pointer:Json;pointerSha256:string;summary:Json;facilities:{schemaVersion:"1.0";preparednessId:string;deploymentId:"dhaka_south";authoritySnapshotSha256:string;rows:Array<Record<string,unknown>>};commit:Json}

export async function readCurrentOperationalPreparedness():Promise<VerifiedOperationalPreparedness>{
  const config=loadRuntimeConfig(false);const authority=await resolveCurrentPreparednessAuthority();const base=operationalPreparednessPaths(config.runtimeRoot,"dhaka_south");
  let pointerBytes:Buffer;
  try{pointerBytes=await readFile(base.latest)}catch(error){if((error as NodeJS.ErrnoException).code==="ENOENT")throw new RuntimePublicError("operational_preparedness_unavailable","storage","Preparedness has not yet been calculated for the current authorities.",404);throw error}
  try{
    const pointer=object(JSON.parse(pointerBytes.toString("utf8")));if(pointer.authoritySnapshotSha256!==authority.authoritySnapshotSha256)throw new RuntimePublicError("operational_preparedness_stale","storage","Preparedness must be recalculated for the current forecast, formula, policy, and inventory.",409);
    const paths=operationalPreparednessPaths(config.runtimeRoot,"dhaka_south",String(pointer.preparednessId));if(!("summary" in paths))throw new Error("paths");
    const [summaryBytes,facilityBytes,commitBytes,summarySchemaBytes,facilitySchemaBytes,commitSchemaBytes,pointerSchemaBytes]=await Promise.all([readFile(paths.summary),readFile(paths.facilities),readFile(paths.commit),readFile(`${config.repositoryRoot}/config/runtime_operational_preparedness.schema.json`),readFile(`${config.repositoryRoot}/config/runtime_operational_facility_preparedness.schema.json`),readFile(`${config.repositoryRoot}/config/runtime_operational_preparedness_commit.schema.json`),readFile(`${config.repositoryRoot}/config/runtime_operational_preparedness_latest.schema.json`)]);
    const summary=object(JSON.parse(summaryBytes.toString("utf8")));const facilities=object(JSON.parse(facilityBytes.toString("utf8")));const commit=object(JSON.parse(commitBytes.toString("utf8")));
    validateStrictJsonSchema(JSON.parse(pointerSchemaBytes.toString("utf8")),pointer);validateStrictJsonSchema(JSON.parse(summarySchemaBytes.toString("utf8")),summary);validateStrictJsonSchema(JSON.parse(facilitySchemaBytes.toString("utf8")),facilities);validateStrictJsonSchema(JSON.parse(commitSchemaBytes.toString("utf8")),commit);
    const hashes=object(commit.artifactHashes);
    if(pointer.preparednessArtifactSha256!==sha(summaryBytes)||pointer.facilityPreparednessArtifactSha256!==sha(facilityBytes)||pointer.commitSha256!==sha(commitBytes)||hashes["preparedness.json"]!==sha(summaryBytes)||hashes["facility_preparedness.json"]!==sha(facilityBytes)||summary.authoritySnapshotSha256!==authority.authoritySnapshotSha256||facilities.authoritySnapshotSha256!==authority.authoritySnapshotSha256||commit.authoritySnapshotSha256!==authority.authoritySnapshotSha256||summary.preparednessId!==pointer.preparednessId||facilities.preparednessId!==pointer.preparednessId||commit.preparednessId!==pointer.preparednessId)throw new Error("binding");
    return{pointer,pointerSha256:sha(pointerBytes),summary,facilities:facilities as VerifiedOperationalPreparedness["facilities"],commit};
  }catch(error){if(error instanceof RuntimePublicError)throw error;throw new RuntimePublicError("operational_preparedness_integrity_failure","storage","Current operational preparedness failed integrity verification.",503,true)}
}
