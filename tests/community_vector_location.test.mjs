import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

const cwd = path.resolve(new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
const submitKey = "vector-location-submit-test-key";
const readKey = "vector-location-read-test-key";

function run(code, extra = {}) {
  return JSON.parse(execFileSync(process.execPath, ["--conditions=react-server", "--import=tsx", "--eval", code], {
    cwd,
    encoding: "utf8",
    env: { ...process.env, DENGUEOPS_VECTOR_SUBMIT_API_KEY: submitKey, DENGUEOPS_COMMUNITY_READ_API_KEY: readKey, ...extra },
  }));
}

test("location metadata enforces complete finite coordinate evidence", () => {
  const result = run(`const m=await import('./lib/community/vector-storage.ts');const s=m.default||m;
    const parse=(fields)=>{const f=new FormData();for(const[k,v]of Object.entries(fields))f.set(k,v);try{return{ok:true,value:s.parseVectorMetadata(f)}}catch(e){return{ok:false,code:e.code}}};
    console.log(JSON.stringify({
      valid:parse({latitude:'23.8103',longitude:'90.4125',locationAccuracyM:'18',capturedAt:'2026-08-10T02:03:00.000Z'}),
      highLat:parse({latitude:'90.0001',longitude:'90'}),lowLat:parse({latitude:'-90.0001',longitude:'90'}),
      highLon:parse({latitude:'23',longitude:'180.0001'}),lowLon:parse({latitude:'23',longitude:'-180.0001'}),
      malformed:parse({latitude:'23north',longitude:'90'}),infinite:parse({latitude:'Infinity',longitude:'90'}),
      partial:parse({latitude:'23'}),badTimestamp:parse({capturedAt:'2026-02-30T02:03:00Z'}),missing:parse({capturedAt:'2026-08-10T02:03:00Z'})
    }));`);
  assert.deepEqual(result.valid.value, {
    clientSubmissionId: null,
    capturedAt: "2026-08-10T02:03:00.000Z",
    latitude: 23.8103,
    longitude: 90.4125,
    locationAccuracyM: 18,
    note: null,
  });
  for (const key of ["highLat", "lowLat", "highLon", "lowLon", "malformed", "infinite", "partial", "badTimestamp"]) {
    assert.deepEqual(result[key], { ok: false, code: "invalid_metadata" }, key);
  }
  assert.equal(result.missing.ok, true);
  assert.equal(result.missing.value.latitude, null);
  assert.equal(result.missing.value.longitude, null);
  assert.equal(result.missing.value.locationAccuracyM, null);
});

test("GPS evidence survives persistence and has a heatmap-ready projection", async t => {
  const uploadRoot = await mkdtemp(path.join(os.tmpdir(), "dengueops-vector-location-"));
  t.after(() => rm(uploadRoot, { recursive: true, force: true }));
  const result = run(`const m=await import('./lib/community/vector-storage.ts');const s=m.default||m;
    const f=new FormData();for(const[k,v]of Object.entries({latitude:'23.8103',longitude:'90.4125',locationAccuracyM:'18.25',capturedAt:'2026-08-10T02:03:00Z'}))f.set(k,v);
    const receipt=await s.saveImage(Uint8Array.from([137,80,78,71,13,10,26,10]),'image/png',s.parseVectorMetadata(f));
    const stored=await s.readSubmission(receipt.submissionId);const analytical=s.toVectorAnalyticalSubmission(stored);
    console.log(JSON.stringify({stored,analytical}));`, { DENGUEOPS_COMMUNITY_UPLOAD_ROOT: uploadRoot });
  assert.equal(result.stored.latitude, 23.8103);
  assert.equal(result.stored.longitude, 90.4125);
  assert.equal(result.stored.locationAccuracyM, 18.25);
  assert.equal(result.stored.capturedAt, "2026-08-10T02:03:00.000Z");
  assert.deepEqual(result.analytical, {
    submissionId: result.stored.submissionId,
    clientSubmissionId: null,
    latitude: 23.8103,
    longitude: 90.4125,
    accuracyMeters: 18.25,
    capturedAt: "2026-08-10T02:03:00.000Z",
    receivedAt: result.stored.receivedAt,
    classificationStatus: "unreviewed",
    processingState: "received",
    logicalObservationStatus: "legacy_unverified",
  });
});

test("protected UI renders coordinates and unavailable evidence truthfully", async t => {
  const uploadRoot = await mkdtemp(path.join(os.tmpdir(), "dengueops-vector-ui-"));
  t.after(() => rm(uploadRoot, { recursive: true, force: true }));
  const result = run(`const storageModule=await import('./lib/community/vector-storage.ts');const s=storageModule.default||storageModule;
    const present=new FormData();for(const[k,v]of Object.entries({latitude:'23.8103',longitude:'90.4125',locationAccuracyM:'18'}))present.set(k,v);
    await s.saveImage(Uint8Array.from([137,80,78,71,13,10,26,10]),'image/png',s.parseVectorMetadata(present));
    await s.saveImage(Uint8Array.from([255,216,255,1]),'image/jpeg',s.parseVectorMetadata(new FormData()));
    const pageModule=await import('./app/vector-surveillance/saved-datasets-images/page.tsx');const page=pageModule.default?.default||pageModule.default;
    const text=[];const visit=value=>{if(typeof value==='string'||typeof value==='number')text.push(String(value));else if(Array.isArray(value))value.forEach(visit);else if(value&&typeof value==='object'&&value.props)visit(value.props.children)};visit(await page());
    console.log(JSON.stringify({coordinates:text.includes('23.8103, 90.4125'),accuracy:text.includes('±18 m'),unavailable:text.includes('Not available'),reported:text.includes('Reported')}));`, { DENGUEOPS_COMMUNITY_UPLOAD_ROOT: uploadRoot });
  assert.deepEqual(result, { coordinates: true, accuracy: true, unavailable: true, reported: false });
});

test("stable clientSubmissionId makes concurrent retries idempotent and rejects conflicts", async t => {
  const uploadRoot = await mkdtemp(path.join(os.tmpdir(), "dengueops-vector-idempotency-"));
  t.after(() => rm(uploadRoot, { recursive: true, force: true }));
  const result = run(`const routeModule=await import('./app/api/community/v1/vector-submissions/route.ts');const route=routeModule.default||routeModule;
    const call=async(id,bytes=[137,80,78,71,13,10,26,10])=>{const f=new FormData();f.set('image',new File([Uint8Array.from(bytes)],'evidence.png',{type:'image/png'}));f.set('clientSubmissionId',id);f.set('latitude','23.8103');f.set('longitude','90.4125');const r=await route.POST(new Request('http://local/api/community/v1/vector-submissions',{method:'POST',headers:{authorization:'Bearer '+process.env.DENGUEOPS_VECTOR_SUBMIT_API_KEY},body:f}));return{status:r.status,body:await r.json()}};
    const firstId='11111111-1111-4111-8111-111111111111',secondId='22222222-2222-4222-8222-222222222222';
    const retries=await Promise.all([call(firstId),call(firstId)]);const separate=await call(secondId);const conflict=await call(firstId,[137,80,78,71,13,10,26,10,1]);
    const storageModule=await import('./lib/community/vector-storage.ts');const storage=storageModule.default||storageModule;const listed=await storage.listSubmissions(10);
    console.log(JSON.stringify({retries,separate,conflict,count:listed.submissions.length,clientIds:listed.submissions.map(x=>x.clientSubmissionId).sort()}));`, { DENGUEOPS_COMMUNITY_UPLOAD_ROOT: uploadRoot });
  assert.equal(result.retries[0].status, 201);
  assert.equal(result.retries[1].status, 201);
  assert.equal(result.retries[0].body.submissionId, result.retries[1].body.submissionId);
  assert.equal(result.retries[0].body.receivedAt, result.retries[1].body.receivedAt);
  assert.equal(result.separate.status, 201);
  assert.equal(result.conflict.status, 409);
  assert.equal(result.conflict.body.error.code, "idempotency_conflict");
  assert.equal(result.count, 2);
  assert.deepEqual(result.clientIds, ["11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"]);
});
