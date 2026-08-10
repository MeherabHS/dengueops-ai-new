import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

const cwd = path.resolve(new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
const readKey = "community-read-test-key-0001";
const submitKey = "vector-submit-test-key-0001";

function run(code, extra = {}) {
  return JSON.parse(execFileSync(process.execPath, ["--conditions=react-server", "--import=tsx", "--eval", code], {
    cwd, encoding: "utf8", env: { ...process.env, DENGUEOPS_RUNTIME_ROOT: path.join(cwd, "runtime"), DENGUEOPS_COMMUNITY_READ_API_KEY: readKey, DENGUEOPS_VECTOR_SUBMIT_API_KEY: submitKey, ...extra },
  }));
}

test("scoped bearer auth rejects missing, wrong, cross-scope, identical keys, and rate limits", () => {
  const result = run(`const m=await import('./lib/community/api-auth.ts');const a=m.default||m;
    const check=(key,scope,now=1)=>{try{a.authenticateCommunityApi(new Request('http://local',{headers:key?{authorization:'Bearer '+key,'x-real-ip':'1.2.3.4'}:{'x-real-ip':'1.2.3.4'}}),scope,now);return 'ok'}catch(e){return e.code}};
    const values=[check(null,'community:read'),check('wrong-credential-value','community:read'),check(process.env.DENGUEOPS_VECTOR_SUBMIT_API_KEY,'community:read'),check(process.env.DENGUEOPS_COMMUNITY_READ_API_KEY,'community:read')];
    let limited='';for(let i=0;i<61;i++)limited=check(process.env.DENGUEOPS_COMMUNITY_READ_API_KEY,'community:read',5000);
    console.log(JSON.stringify({values,limited}));`);
  assert.deepEqual(result.values, ["unauthorized", "unauthorized", "forbidden_scope", "ok"]);
  assert.equal(result.limited, "rate_limited");
  const identical = run(`const m=await import('./lib/community/api-auth.ts');const a=m.default||m;try{a.authenticateCommunityApi(new Request('http://local',{headers:{authorization:'Bearer '+process.env.DENGUEOPS_COMMUNITY_READ_API_KEY}}),'community:read');console.log(JSON.stringify('ok'))}catch(e){console.log(JSON.stringify(e.code))}`, { DENGUEOPS_VECTOR_SUBMIT_API_KEY: readKey });
  assert.equal(identical, "unauthorized");
});

test("Community v1 current is no-store, scoped, ordered, sanitized, and truthful", () => {
  const value = run(`const m=await import('./app/api/community/v1/current/route.ts');const r=m.default||m;const call=async key=>{const x=await r.GET(new Request('http://local/api/community/v1/current',{headers:key?{authorization:'Bearer '+key}:{}}));return{status:x.status,cache:x.headers.get('cache-control'),body:await x.json()}};console.log(JSON.stringify({missing:await call(),submit:await call(process.env.DENGUEOPS_VECTOR_SUBMIT_API_KEY),read:await call(process.env.DENGUEOPS_COMMUNITY_READ_API_KEY)}));`);
  assert.equal(value.missing.status, 401);
  assert.equal(value.submit.status, 403);
  assert.equal(value.read.status, 200);
  assert.equal(value.read.cache, "no-store");
  const body = value.read.body;
  assert.equal(body.schemaVersion, "1.0");
  assert.equal(body.forecast.status, "available");
  assert.equal(body.forecast.pointCases, 230);
  assert.deepEqual(body.forecast.trend, { direction: "up", changeCases: 41 });
  assert.equal(body.forecast.series.observed.at(-1).cases, 189);
  assert.deepEqual(body.forecast.series.forecast[0], { period: body.forecast.targetPeriod, cases: 230, lower: 162, upper: 298 });
  assert.deepEqual(body.forecast.confidence, { status: "available", score: 53, band: "low" });
  assert.equal(body.preparedness.status, "available");
  assert.equal(body.forecast.series.observed.every((p, i, a) => i === 0 || a[i - 1].period.localeCompare(p.period) <= 0), true);
  assert.equal(body.preparedness.facilities.every(row => row.liveAvailability === null), true);
  const serialized = JSON.stringify(body);
  for (const forbidden of ["modelId", "assessmentId", "assignmentId", "policySha", "formulaExpression", "workspaceId", "technicalWinner", "activeModel", "authoritySnapshotSha256", "latitude", "longitude", "locationAccuracyM", "clientSubmissionId", "analysisDisposition", "deletedAt", "deletedBy", "deletionReason", "originalEvidenceSha256"]) assert.equal(serialized.includes(forbidden), false);
});

test("Community trend is server-derived from latest observed and point forecast", () => {
  const trends = run(`const m=await import('./lib/community/public-read-model.ts');const api=m.default||m;console.log(JSON.stringify([
    api.deriveCommunityTrend(189,230),
    api.deriveCommunityTrend(230,189),
    api.deriveCommunityTrend(189,189),
    api.deriveCommunityTrend(null,230),
    api.deriveCommunityTrend(189,null),
  ]));`);
  assert.deepEqual(trends, [
    { direction: "up", changeCases: 41 },
    { direction: "down", changeCases: -41 },
    { direction: "stable", changeCases: 0 },
    { direction: "unknown", changeCases: null },
    { direction: "unknown", changeCases: null },
  ]);
});

test("vector storage accepts raster signatures, preserves integrity, and prevents paths", async t => {
  const uploadRoot = await mkdtemp(path.join(os.tmpdir(), "dengueops-vector-"));
  t.after(() => rm(uploadRoot, { recursive: true, force: true }));
  const result = run(`const s=await import('./lib/community/vector-storage.ts');const a=s.default||s;
    const samples=[['image/jpeg',Uint8Array.from([255,216,255,1])],['image/png',Uint8Array.from([137,80,78,71,13,10,26,10,1])],['image/webp',Uint8Array.from([82,73,70,70,4,0,0,0,87,69,66,80,1])]];const receipts=[];
    for(const [type,bytes] of samples)receipts.push(await a.saveImage(bytes,type,{capturedAt:null,latitude:null,longitude:null,locationAccuracyM:null,note:null}));
    const listed=await a.listSubmissions(10);const image=await a.readImage(receipts[0].submissionId);let fake='',traversal='',oversized='';try{await a.saveImage(Uint8Array.from([1,2,3]),'image/jpeg',{capturedAt:null,latitude:null,longitude:null,locationAccuracyM:null,note:null})}catch(e){fake=e.code}try{await a.readImage('../../etc/passwd')}catch(e){traversal=e.code}const large=new Uint8Array(1025);large.set([137,80,78,71,13,10,26,10]);try{await a.saveImage(large,'image/png',{capturedAt:null,latitude:null,longitude:null,locationAccuracyM:null,note:null})}catch(e){oversized=e.code}
    console.log(JSON.stringify({receipts,listed,sha:image.metadata.sha256,fake,traversal,oversized,storageKey:image.metadata.storageKey}));`, { DENGUEOPS_COMMUNITY_UPLOAD_ROOT: uploadRoot, DENGUEOPS_VECTOR_IMAGE_MAX_BYTES: "1024" });
  assert.equal(result.receipts.length, 3);
  assert.equal(result.listed.submissions.length, 3);
  assert.match(result.sha, /^[0-9a-f]{64}$/);
  assert.equal(result.fake, "invalid_image_type");
  assert.equal(result.traversal, "not_found");
  assert.equal(result.oversized, "image_too_large");
  assert.match(result.storageKey, /^submissions\/[0-9a-f-]+\/image\./);
  const metadata = JSON.parse(await readFile(path.join(uploadRoot, result.storageKey.replace(/image\.[^.]+$/, "metadata.json")), "utf8"));
  assert.equal("apiKey" in metadata, false);
  assert.equal(path.resolve(uploadRoot).startsWith(path.join(cwd, "public")), false);
});

test("vector submission route validates scope, multipart, metadata, receipt, and size", async t => {
  const uploadRoot = await mkdtemp(path.join(os.tmpdir(), "dengueops-vector-route-"));
  t.after(() => rm(uploadRoot, { recursive: true, force: true }));
  const value = run(`const m=await import('./app/api/community/v1/vector-submissions/route.ts');const r=m.default||m;
    const call=async(key,bytes,type='image/png',fields={})=>{const f=new FormData();f.set('image',new File([Uint8Array.from(bytes)],'../../escape.png',{type}));for(const[k,v]of Object.entries(fields))f.set(k,v);const x=await r.POST(new Request('http://local/api/community/v1/vector-submissions',{method:'POST',headers:key?{authorization:'Bearer '+key}:{},body:f}));return{status:x.status,body:await x.json()}};
    console.log(JSON.stringify({missing:await call(null,[137,80,78,71,13,10,26,10]),read:await call(process.env.DENGUEOPS_COMMUNITY_READ_API_KEY,[137,80,78,71,13,10,26,10]),valid:await call(process.env.DENGUEOPS_VECTOR_SUBMIT_API_KEY,[137,80,78,71,13,10,26,10], 'image/png',{latitude:'23.7',longitude:'90.4',note:'test'}),svg:await call(process.env.DENGUEOPS_VECTOR_SUBMIT_API_KEY,[60,115,118,103], 'image/svg+xml'),badLocation:await call(process.env.DENGUEOPS_VECTOR_SUBMIT_API_KEY,[137,80,78,71,13,10,26,10], 'image/png',{latitude:'200'})}));`, { DENGUEOPS_COMMUNITY_UPLOAD_ROOT: uploadRoot });
  assert.deepEqual([value.missing.status, value.read.status, value.valid.status, value.svg.status, value.badLocation.status], [401, 403, 201, 415, 400]);
  assert.deepEqual(Object.keys(value.valid.body).sort(), ["receivedAt", "schemaVersion", "status", "submissionId"]);
});

test("Super User vector surfaces, governance mutations, and protected image route are guarded", async () => {
  const sources = ["proxy.ts", "app/vector-surveillance/page.tsx", "app/vector-surveillance/saved-datasets-images/page.tsx", "app/api/vector-surveillance/submissions/route.ts", "app/api/vector-surveillance/submissions/[submissionId]/route.ts", "app/api/vector-surveillance/submissions/[submissionId]/image/route.ts"].map(file => execFileSync(process.execPath, ["-e", `process.stdout.write(require('fs').readFileSync(${JSON.stringify(path.join(cwd, "FILE"))}.replace('FILE',${JSON.stringify(file)}),'utf8'))`], { encoding: "utf8" })).join("\n");
  assert.match(sources, /vector-surveillance\/:path\*/);
  assert.match(sources, /requireSuperUser/);
  assert.match(sources, /No Community image submissions have been received yet/);
  assert.match(sources, /Datasets/);
  assert.match(sources, /Planned|future governed dataset-intake/);
  assert.match(sources, /X-Content-Type-Options/);
  assert.match(sources, /requireSuperUserMutation/);
  assert.match(sources, /delete_permanently/);
});

test("protected listing returns stored location and image retrieval requires a valid Super User session", async t => {
  const uploadRoot = await mkdtemp(path.join(os.tmpdir(), "dengueops-vector-protected-"));
  t.after(() => rm(uploadRoot, { recursive: true, force: true }));
  const result = run(`const storage=await import('./lib/community/vector-storage.ts');const s=storage.default||storage;const receipt=await s.saveImage(Uint8Array.from([255,216,255,1]),'image/jpeg',{capturedAt:'2026-08-10T02:03:00.000Z',latitude:23.8103,longitude:90.4125,locationAccuracyM:18,note:null});
    const listModule=await import('./app/api/vector-surveillance/submissions/route.ts');const list=listModule.default||listModule;const imageModule=await import('./app/api/vector-surveillance/submissions/[submissionId]/image/route.ts');const images=imageModule.default||imageModule;const sessions=await import('./lib/auth/session.ts');const auth=sessions.default||sessions;const token=await auth.createSessionToken('admin@rmcl');const cookie=auth.sessionCookie(token).split(';')[0];
    const unauth=await list.GET(new Request('http://local/api/vector-surveillance/submissions'));const listed=await list.GET(new Request('http://local/api/vector-surveillance/submissions',{headers:{cookie}}));const fetched=await images.GET(new Request('http://local/image',{headers:{cookie}}),{params:Promise.resolve({submissionId:receipt.submissionId})});const traversal=await images.GET(new Request('http://local/image',{headers:{cookie}}),{params:Promise.resolve({submissionId:'../../etc/passwd'})});
    console.log(JSON.stringify({unauth:unauth.status,listed:listed.status,listBody:await listed.json(),fetched:fetched.status,type:fetched.headers.get('content-type'),nosniff:fetched.headers.get('x-content-type-options'),traversal:traversal.status}));`, { DENGUEOPS_COMMUNITY_UPLOAD_ROOT: uploadRoot, DENGUEOPS_SESSION_SECRET: "focused-test-session-secret-at-least-32-bytes" });
  assert.equal(result.unauth, 401);
  assert.equal(result.listed, 200);
  assert.equal(result.listBody.submissions[0].submissionId.length, 36);
  assert.deepEqual({latitude:result.listBody.submissions[0].latitude,longitude:result.listBody.submissions[0].longitude,accuracy:result.listBody.submissions[0].locationAccuracyM,capturedAt:result.listBody.submissions[0].capturedAt},{latitude:23.8103,longitude:90.4125,accuracy:18,capturedAt:'2026-08-10T02:03:00.000Z'});
  assert.equal(result.fetched, 200);
  assert.equal(result.type, "image/jpeg");
  assert.equal(result.nosniff, "nosniff");
  assert.equal(result.traversal, 404);
});
