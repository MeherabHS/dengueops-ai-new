import {randomUUID} from "node:crypto";
import {mkdir,open,readFile} from "node:fs/promises";
import path from "node:path";
import {requireSuperUser,requireSuperUserMutation} from "@/lib/auth/authorization";
import {loadRuntimeConfig} from "@/lib/runtime/config";
import type {OperationalPreparednessJobRecord,StartOperationalPreparednessResponse} from "@/lib/runtime/contracts";
import {errorResponse,RuntimePublicError} from "@/lib/runtime/errors";
import {jobRecordPath,operationalPreparednessPaths,runtimeCollectionPaths} from "@/lib/runtime/paths";
import {resolveCurrentPreparednessAuthority} from "@/lib/runtime/preparedness-authority";
import {readCurrentOperationalPreparedness} from "@/lib/runtime/operational-preparedness-reader";
import {createPendingJob,initializeRuntimeRoot} from "@/lib/runtime/store";

export const runtime="nodejs";

async function existingJob(runtimeRoot:string,jobId:string):Promise<OperationalPreparednessJobRecord|null>{const collections=runtimeCollectionPaths(runtimeRoot);for(const directory of [collections.pendingJobs,collections.runningJobs,collections.completedJobs,collections.failedJobs])try{return JSON.parse(await readFile(jobRecordPath(directory,jobId),"utf8")) as OperationalPreparednessJobRecord}catch{}return null}

export async function GET(request:Request):Promise<Response>{try{await requireSuperUser(request);const value=await readCurrentOperationalPreparedness();return Response.json({ok:true,...value},{headers:{"Cache-Control":"no-store"}})}catch(error){const failure=errorResponse(error,randomUUID());return Response.json(failure.body,{status:failure.status,headers:{"Cache-Control":"no-store"}})}}

export async function POST(request:Request):Promise<Response>{const correlationId=randomUUID();try{
  await requireSuperUserMutation(request);const body=await request.json().catch(()=>null);if(!body||typeof body!=="object"||Array.isArray(body)||Object.keys(body).length!==0)throw new RuntimePublicError("invalid_preparedness_request","validation","Preparedness recalculation accepts no client-selected authority.",400);
  const config=loadRuntimeConfig();await initializeRuntimeRoot(config.runtimeRoot);const authority=await resolveCurrentPreparednessAuthority();
  try{const current=await readCurrentOperationalPreparedness();if(current.summary.authoritySnapshotSha256===authority.authoritySnapshotSha256){const response:StartOperationalPreparednessResponse={ok:true,jobId:null,preparednessId:String(current.pointer.preparednessId),status:"completed",statusUrl:null,recovered:true,authoritySnapshotSha256:authority.authoritySnapshotSha256};return Response.json(response,{headers:{"Cache-Control":"no-store"}})}}catch(error){if(error instanceof RuntimePublicError&&!['operational_preparedness_unavailable','operational_preparedness_stale'].includes(error.code))throw error}
  const authorityPaths=operationalPreparednessPaths(config.runtimeRoot,"dhaka_south");await mkdir(authorityPaths.requests,{recursive:true,mode:0o700});const markerPath=path.join(authorityPaths.requests,`${authority.authoritySnapshotSha256}.json`);
  try{const marker=JSON.parse(await readFile(markerPath,"utf8")) as {jobId:string;preparednessId:string;authoritySnapshotSha256:string};if(marker.authoritySnapshotSha256===authority.authoritySnapshotSha256){const job=await existingJob(config.runtimeRoot,marker.jobId);const response:StartOperationalPreparednessResponse={ok:true,jobId:marker.jobId,preparednessId:marker.preparednessId,status:job?.status??"queued",statusUrl:`/api/runtime/jobs/${marker.jobId}`,recovered:true,authoritySnapshotSha256:authority.authoritySnapshotSha256};return Response.json(response,{headers:{"Cache-Control":"no-store"}})}}catch{}
  const jobId=randomUUID(),preparednessId=randomUUID(),now=new Date().toISOString();const marker={schemaVersion:"1.0",jobId,preparednessId,authoritySnapshotSha256:authority.authoritySnapshotSha256,createdAt:now};const handle=await open(markerPath,"wx",0o600);try{await handle.writeFile(`${JSON.stringify(marker,null,2)}\n`,"utf8");await handle.sync()}finally{await handle.close()}
  const job:OperationalPreparednessJobRecord={schemaVersion:"1.0",jobKind:"operational_preparedness",jobId,preparednessId,deploymentId:"dhaka_south",workflowMode:"operational_preparedness",authoritySnapshotSha256:authority.authoritySnapshotSha256,status:"queued",progress:"waiting_for_preparedness_worker",createdAt:now,claimedAt:null,startedAt:null,updatedAt:now,completedAt:null,heartbeatAt:null,workerId:null,processId:null,timeoutSeconds:300,retryCount:0,error:null,committedPreparednessId:null};
  await createPendingJob(jobRecordPath(runtimeCollectionPaths(config.runtimeRoot).pendingJobs,jobId),job);const response:StartOperationalPreparednessResponse={ok:true,jobId,preparednessId,status:"queued",statusUrl:`/api/runtime/jobs/${jobId}`,recovered:false,authoritySnapshotSha256:authority.authoritySnapshotSha256};return Response.json(response,{status:202,headers:{"Cache-Control":"no-store"}});
}catch(error){const failure=errorResponse(error,correlationId);return Response.json(failure.body,{status:failure.status,headers:{"Cache-Control":"no-store"}})}}
