import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

const cwd = path.resolve(new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
const readKey = "vector-governance-read-key";
const submitKey = "vector-governance-submit-key";
const sessionSecret = "vector-governance-session-secret-at-least-32-bytes";

function run(code, uploadRoot) {
  return JSON.parse(execFileSync(process.execPath, ["--conditions=react-server", "--import=tsx", "--eval", code], {
    cwd,
    encoding: "utf8",
    env: {
      ...process.env,
      DENGUEOPS_COMMUNITY_UPLOAD_ROOT: uploadRoot,
      DENGUEOPS_COMMUNITY_READ_API_KEY: readKey,
      DENGUEOPS_VECTOR_SUBMIT_API_KEY: submitKey,
      DENGUEOPS_SESSION_SECRET: sessionSecret,
    },
  }));
}

test("only a same-origin Super User can exclude evidence", async t => {
  const uploadRoot = await mkdtemp(path.join(os.tmpdir(), "dengueops-vector-exclude-"));
  t.after(() => rm(uploadRoot, { recursive: true, force: true }));
  const result = run(`const storageModule=await import('./lib/community/vector-storage.ts');const storage=storageModule.default||storageModule;
    const input=new FormData();for(const[k,v]of Object.entries({clientSubmissionId:'33333333-3333-4333-8333-333333333333',latitude:'23.8',longitude:'90.4'}))input.set(k,v);
    const receipt=await storage.saveImage(Uint8Array.from([137,80,78,71,13,10,26,10]),'image/png',storage.parseVectorMetadata(input));
    const routeModule=await import('./app/api/vector-surveillance/submissions/[submissionId]/route.ts');const route=routeModule.default||routeModule;
    const sessions=await import('./lib/auth/session.ts');const auth=sessions.default||sessions;const token=await auth.createSessionToken('admin@example.test');const cookie=auth.sessionCookie(token).split(';')[0];
    const call=async(method,id,body,headers={})=>{const response=await route[method](new Request('http://local/api/vector-surveillance/submissions/'+id,{method,headers:{'content-type':'application/json',...headers},body:JSON.stringify(body)}),{params:Promise.resolve({submissionId:id})});return{status:response.status,body:await response.json()}};
    const deletion={reason:'duplicate',confirmation:'delete_permanently'};
    const unauth=await call('DELETE',receipt.submissionId,deletion);const readKey=await call('DELETE',receipt.submissionId,deletion,{authorization:'Bearer '+process.env.DENGUEOPS_COMMUNITY_READ_API_KEY});const submitKey=await call('DELETE',receipt.submissionId,deletion,{authorization:'Bearer '+process.env.DENGUEOPS_VECTOR_SUBMIT_API_KEY});
    const excluded=await call('PATCH',receipt.submissionId,{reason:'other',note:'Confirmed analyst review.'},{cookie,origin:'http://local',host:'local'});
    const stored=await storage.readSubmission(receipt.submissionId);const image=await storage.readImage(receipt.submissionId);const analytical=storage.toVectorAnalyticalSubmission(stored);const listed=await storage.listSubmissions(10);
    const traversal=await call('DELETE','../../etc/passwd',deletion,{cookie,origin:'http://local',host:'local'});
    console.log(JSON.stringify({unauth,readKey,submitKey,excluded,disposition:stored.analysisDisposition,imageBytes:image.bytes.length,analytical,listCount:listed.submissions.length,traversal}));`, uploadRoot);
  assert.equal(result.unauth.status, 401);
  assert.equal(result.readKey.status, 401);
  assert.equal(result.submitKey.status, 401);
  assert.equal(result.excluded.status, 200);
  assert.deepEqual(result.disposition, {
    status: "excluded",
    reason: "other",
    note: "Confirmed analyst review.",
    changedAt: result.disposition.changedAt,
    changedBy: "admin@example.test",
  });
  assert.match(result.disposition.changedAt, /^\d{4}-\d{2}-\d{2}T/);
  assert.equal(result.imageBytes, 8);
  assert.equal(result.analytical, null);
  assert.equal(result.listCount, 1);
  assert.equal(result.traversal.status, 404);
});

test("permanent deletion removes active evidence, publishes a minimal tombstone, and prevents resurrection", async t => {
  const uploadRoot = await mkdtemp(path.join(os.tmpdir(), "dengueops-vector-delete-"));
  t.after(() => rm(uploadRoot, { recursive: true, force: true }));
  const result = run(`const storageModule=await import('./lib/community/vector-storage.ts');const storage=storageModule.default||storageModule;
    const save=async(id,note)=>{const f=new FormData();for(const[k,v]of Object.entries({clientSubmissionId:id,latitude:'23.8',longitude:'90.4',locationAccuracyM:'12',note}))f.set(k,v);return storage.saveImage(Uint8Array.from([137,80,78,71,13,10,26,10]),'image/png',storage.parseVectorMetadata(f))};
    const deletedReceipt=await save('44444444-4444-4444-8444-444444444444','private original note');const separateReceipt=await save('55555555-5555-4555-8555-555555555555','separate');
    const routeModule=await import('./app/api/vector-surveillance/submissions/[submissionId]/route.ts');const route=routeModule.default||routeModule;const imageModule=await import('./app/api/vector-surveillance/submissions/[submissionId]/image/route.ts');const imageRoute=imageModule.default||imageModule;
    const sessions=await import('./lib/auth/session.ts');const auth=sessions.default||sessions;const token=await auth.createSessionToken('privacy-admin@example.test');const cookie=auth.sessionCookie(token).split(';')[0];const headers={'content-type':'application/json',cookie,origin:'http://local',host:'local'};
    const response=await route.DELETE(new Request('http://local/api/vector-surveillance/submissions/'+deletedReceipt.submissionId,{method:'DELETE',headers,body:JSON.stringify({reason:'user_request',confirmation:'delete_permanently'})}),{params:Promise.resolve({submissionId:deletedReceipt.submissionId})});
    const deletion={status:response.status,body:await response.json()};const tombstone=await storage.readDeletionTombstone(deletedReceipt.submissionId);const listed=await storage.listSubmissions(10);const separate=await storage.readSubmission(separateReceipt.submissionId);
    const code=async(fn)=>{try{await fn();return'ok'}catch(error){return error.code}};const metadataState=await code(()=>storage.readSubmission(deletedReceipt.submissionId));const imageState=await code(()=>storage.readImage(deletedReceipt.submissionId));
    const imageResponse=await imageRoute.GET(new Request('http://local/image',{headers:{cookie}}),{params:Promise.resolve({submissionId:deletedReceipt.submissionId})});
    const postModule=await import('./app/api/community/v1/vector-submissions/route.ts');const post=postModule.default||postModule;const retryForm=new FormData();retryForm.set('image',new File([Uint8Array.from([137,80,78,71,13,10,26,10])],'retry.png',{type:'image/png'}));retryForm.set('clientSubmissionId',deletedReceipt.submissionId);retryForm.set('latitude','23.8');retryForm.set('longitude','90.4');retryForm.set('locationAccuracyM','12');retryForm.set('note','private original note');const retry=await post.POST(new Request('http://local/api/community/v1/vector-submissions',{method:'POST',headers:{authorization:'Bearer '+process.env.DENGUEOPS_VECTOR_SUBMIT_API_KEY},body:retryForm}));
    const fs=await import('node:fs/promises');const activeDirectory=path=>fs.access(path).then(()=>true,()=>false);const nodePath=await import('node:path');const activeExists=await activeDirectory(nodePath.join(process.env.DENGUEOPS_COMMUNITY_UPLOAD_ROOT,'submissions',deletedReceipt.submissionId));
    console.log(JSON.stringify({deletion,tombstone,tombstoneKeys:Object.keys(tombstone).sort(),tombstoneText:JSON.stringify(tombstone),listIds:listed.submissions.map(x=>x.submissionId),separateId:separate.submissionId,metadataState,imageState,imageRouteStatus:imageResponse.status,retry:{status:retry.status,body:await retry.json()},activeExists}));`, uploadRoot);
  assert.equal(result.deletion.status, 200);
  assert.equal(result.deletion.body.status, "deleted");
  assert.deepEqual(result.tombstoneKeys, ["clientSubmissionId", "deletedAt", "deletedBy", "deletionReason", "originalEvidenceSha256", "schemaVersion", "submissionId"]);
  for (const forbidden of ["latitude", "longitude", "locationAccuracyM", "note", "storageKey", "image", "byteSize"]) assert.equal(result.tombstoneText.includes(forbidden), false);
  assert.equal(result.tombstone.deletedBy, "privacy-admin@example.test");
  assert.equal(result.tombstone.deletionReason, "user_request");
  assert.equal(result.listIds.includes(result.tombstone.submissionId), false);
  assert.equal(result.listIds.includes(result.separateId), true);
  assert.equal(result.metadataState, "not_found");
  assert.equal(result.imageState, "not_found");
  assert.equal(result.imageRouteStatus, 404);
  assert.equal(result.retry.status, 410);
  assert.equal(result.retry.body.error.code, "submission_deleted");
  assert.equal(result.activeExists, false);
});

test("simultaneous and repeated deletion is deterministic", async t => {
  const uploadRoot = await mkdtemp(path.join(os.tmpdir(), "dengueops-vector-delete-race-"));
  t.after(() => rm(uploadRoot, { recursive: true, force: true }));
  const result = run(`const storageModule=await import('./lib/community/vector-storage.ts');const storage=storageModule.default||storageModule;const f=new FormData();f.set('clientSubmissionId','66666666-6666-4666-8666-666666666666');const receipt=await storage.saveImage(Uint8Array.from([255,216,255,1]),'image/jpeg',storage.parseVectorMetadata(f));
    const concurrent=await Promise.all([storage.deleteSubmission(receipt.submissionId,'test_submission','admin-a'),storage.deleteSubmission(receipt.submissionId,'test_submission','admin-b')]);const repeated=await storage.deleteSubmission(receipt.submissionId,'test_submission','admin-c');const tombstone=await storage.readDeletionTombstone(receipt.submissionId);
    const racedForm=new FormData();racedForm.set('clientSubmissionId','77777777-7777-4777-8777-777777777777');const racedMetadata=storage.parseVectorMetadata(racedForm);await storage.saveImage(Uint8Array.from([255,216,255,2]),'image/jpeg',racedMetadata);const race=await Promise.allSettled([storage.deleteSubmission('77777777-7777-4777-8777-777777777777','duplicate','admin-race'),storage.saveImage(Uint8Array.from([255,216,255,2]),'image/jpeg',racedMetadata)]);let retryCode='';try{await storage.saveImage(Uint8Array.from([255,216,255,2]),'image/jpeg',racedMetadata)}catch(error){retryCode=error.code}const listed=await storage.listSubmissions(10);
    console.log(JSON.stringify({statuses:concurrent.map(x=>x.status).sort(),repeated:repeated.status,count:listed.submissions.length,tombstone,race:race.map(x=>x.status==='fulfilled'?'fulfilled':'rejected:'+x.reason.code),retryCode}));`, uploadRoot);
  assert.deepEqual(result.statuses, ["already_deleted", "deleted"]);
  assert.equal(result.repeated, "already_deleted");
  assert.equal(result.count, 0);
  assert.equal(result.tombstone.submissionId, "66666666-6666-4666-8666-666666666666");
  assert.equal(result.race[0], "fulfilled");
  assert.ok(["fulfilled", "rejected:submission_deleted"].includes(result.race[1]), JSON.stringify(result.race));
  assert.equal(result.retryCode, "submission_deleted");
});
