import test from "node:test";
import assert from "node:assert/strict";
import {cp,mkdtemp,mkdir,readFile,readdir,rm,symlink,unlink,writeFile} from "node:fs/promises";
import {spawn,spawnSync} from "node:child_process";
import {tmpdir} from "node:os";
import path from "node:path";
import net from "node:net";
import {createRequire} from "node:module";

const python="C:\\Users\\CUBE\\AppData\\Local\\Programs\\Python\\Python313\\python.exe";
const root=process.cwd();
const sha="0".repeat(64);
async function freePort(){return await new Promise((resolve,reject)=>{const server=net.createServer();server.listen(0,"127.0.0.1",()=>{const address=server.address();server.close(()=>resolve(address.port))});server.on("error",reject)})}
async function start(runtime,cwd=root){const port=await freePort(),child=spawn(process.execPath,[path.join(root,"node_modules/next/dist/bin/next"),"dev","-H","127.0.0.1","-p",String(port)],{cwd,env:{...process.env,DENGUEOPS_RUNTIME_ROOT:runtime,DENGUEOPS_INTERNAL_MODEL_LIFECYCLE_ENABLED:"false"},stdio:["ignore","pipe","pipe"]});child.stdout.resume();child.stderr.resume();const url=`http://127.0.0.1:${port}/api/runtime/model-lifecycle`;for(let i=0;i<100;i++){try{await fetch(url);return{child,url}}catch{await new Promise(resolve=>setTimeout(resolve,100))}}child.kill();throw new Error("resolver test server did not start")}
async function stop(child){child.kill();await new Promise(resolve=>setTimeout(resolve,200))}
async function json(file){return JSON.parse(await readFile(file,"utf8"))}
async function put(file,value){await writeFile(file,JSON.stringify(value,null,2)+"\n")}
async function bundle(runtime,which=-1){const names=(await readdir(path.join(runtime,"model-lifecycle"))).sort();return path.join(runtime,"model-lifecycle",names.at(which))}

test("real TypeScript active-model resolver reconciles complete chains and fails closed",{timeout:240000},async()=>{
 const temporary=await mkdtemp(path.join(tmpdir(),"dengueops-ts-resolver-")),fixtureRoot=path.join(temporary,"fixtures"),working=path.join(temporary,"working");
 const built=spawnSync(python,["-m","tests.runtime_lifecycle_fixture_cli",fixtureRoot],{cwd:root,env:{...process.env,PYTHONDONTWRITEBYTECODE:"1"},encoding:"utf8",timeout:180000});assert.equal(built.status,0,built.stderr);
 await cp(path.join(fixtureRoot,"profile"),working,{recursive:true});const server=await start(working);
 try{
  async function restore(name){await rm(working,{recursive:true,force:true});await cp(path.join(fixtureRoot,name),working,{recursive:true})}
  async function expect(name,ok,mutate){await restore(name);if(mutate)await mutate(working);const response=await fetch(server.url);if(ok)assert.equal(response.status,200,`${name}:${mutate?.name??"valid"}`);else assert.notEqual(response.status,200,`${name}:${mutate?.name??"invalid"}`);if(ok)assert.equal((await response.json()).ok,true)}
  for(const name of ["profile","bootstrap","promotion","rollback"])await expect(name,true);
  const pointerFile=r=>path.join(r,"deployments/dhaka_south/model-assignment/latest.json");
  const latestBundle=async r=>bundle(r,-1);
  const corruptJson=(relative,key,value)=>async function corrupt(r){const file=path.join(await latestBundle(r),relative),data=await json(file);data[key]=value;await put(file,data)};
  const cases=[
   ["invalid latest-pointer schema",async r=>{const f=pointerFile(r),v=await json(f);v.unexpected=true;await put(f,v)}],
   ["invalid assignment schema",corruptJson("artifacts/model_assignment.json","unexpected",true)],
   ["invalid lifecycle decision schema",corruptJson("artifacts/lifecycle_decision.json","unexpected",true)],
   ["invalid assignment commit",corruptJson("metadata/model_assignment_commit.json","unexpected",true)],
   ["invalid lifecycle decision commit",corruptJson("metadata/lifecycle_decision_commit.json","unexpected",true)],
   ["extra governed fields",corruptJson("artifacts/lifecycle_decision.json","expectedAssessmentCommitSha256",sha)],
   ["assignment ID mismatch",async r=>{const f=pointerFile(r),v=await json(f);v.assignmentId="00000000-0000-4000-8000-000000000001";await put(f,v)}],
   ["decision ID mismatch",async r=>{const f=pointerFile(r),v=await json(f);v.lifecycleDecisionId="00000000-0000-4000-8000-000000000001";await put(f,v)}],
   ["commit artifact ID mismatch",corruptJson("metadata/model_assignment_commit.json","assignmentId","00000000-0000-4000-8000-000000000001")],
   ["duplicate current assignment ID",async r=>{const source=await latestBundle(r),target=path.join(r,"model-lifecycle","00000000-0000-4000-8000-000000000099");await cp(source,target,{recursive:true})}],
   ["duplicate prior assignment ID",async r=>{const names=(await readdir(path.join(r,"model-lifecycle"))).sort(),source=path.join(r,"model-lifecycle",names[0]),target=path.join(r,"model-lifecycle","00000000-0000-4000-8000-000000000098");await cp(source,target,{recursive:true})}],
   ["duplicate lifecycle decision ID",async r=>{const source=await latestBundle(r),target=path.join(r,"model-lifecycle","00000000-0000-4000-8000-000000000097");await cp(source,target,{recursive:true})}],
   ["prior-chain cycle",corruptJson("artifacts/model_assignment.json","priorAssignmentId","00000000-0000-4000-8000-000000000001")],
   ["broken prior link",corruptJson("artifacts/model_assignment.json","priorAssignmentCommitSha256",sha)],
   ["missing pointer with history",async r=>rm(pointerFile(r))],
   ["arbitrary orphan bundle",async r=>{const source=await latestBundle(r),target=path.join(r,"model-lifecycle","00000000-0000-4000-8000-000000000096");await cp(source,target,{recursive:true})}],
   ["incomplete assignment bundle",async r=>rm(path.join(await latestBundle(r),"metadata/model_assignment_commit.json"))],
   ["path traversal",async r=>{const f=pointerFile(r),v=await json(f);v.assignmentPath="../outside/model_assignment.json";await put(f,v)}],
   ["candidate registry mismatch",corruptJson("artifacts/model_assignment.json","candidateRegistrySha256",sha)],
   ["feature order mismatch",corruptJson("artifacts/model_assignment.json","featureOrderSha256",sha)],
   ["lifecycle policy mismatch",corruptJson("artifacts/lifecycle_decision.json","policySha256",sha)],
   ["model parameter mismatch",corruptJson("artifacts/model_assignment.json","parameterSha256",sha)],
   ["symbolic-link or reparse-point path",async r=>{const source=await latestBundle(r),target=path.join(r,"model-lifecycle","00000000-0000-4000-8000-000000000094");await symlink(source,target,process.platform==="win32"?"junction":"dir")}],
   ["Windows junction",async r=>{const source=await latestBundle(r),target=path.join(r,"model-lifecycle","00000000-0000-4000-8000-000000000095");await symlink(source,target,process.platform==="win32"?"junction":"dir")}],
  ];
  for(const [label,mutate] of cases)await expect("rollback",false,Object.defineProperty(mutate,"name",{value:label}));
  await restore("bootstrap");await rm(pointerFile(working));let response=await fetch(server.url);assert.notEqual(response.status,200,"deleted pointer cannot silently fall back");
  const compile=path.join(temporary,"compiled"),declarations=path.join(temporary,"resolver-test.d.ts");await writeFile(declarations,'declare module "server-only"; declare module "@/lib/dashboard-view-model" { export interface OverviewViewModel {} }');
  const emitted=spawnSync(process.execPath,["node_modules/typescript/bin/tsc","--outDir",compile,"--module","commonjs","--moduleResolution","node","--target","es2022","--esModuleInterop","--skipLibCheck","--noEmit","false","lib/runtime/active-model.ts","lib/runtime/model-lifecycle-policy.ts","lib/runtime/strict-json-schema.ts","lib/runtime/errors.ts",declarations],{cwd:root,encoding:"utf8",timeout:90000});assert.equal(emitted.status,0,emitted.stdout+emitted.stderr);await mkdir(path.join(compile,"node_modules/server-only"),{recursive:true});await writeFile(path.join(compile,"node_modules/server-only/index.js"),"");
  const require=createRequire(import.meta.url),{resolveActiveModel}=require(path.join(compile,"active-model.js")),repository=path.join(temporary,"repository");await cp(path.join(root,"config"),path.join(repository,"config"),{recursive:true});
  const quick=path.join(repository,"config/deployments/dhaka_south/quick_forecast_policy.json"),lifecycle=path.join(repository,"config/deployments/dhaka_south/model_lifecycle_policy.json"),quickOriginal=await readFile(quick,"utf8"),lifecycleOriginal=await readFile(lifecycle,"utf8");
  await writeFile(quick,quickOriginal+"\n");await assert.rejects(resolveActiveModel(repository,path.join(fixtureRoot,"profile")),error=>error.code==="active_model_integrity_error");
  await writeFile(quick,quickOriginal.replace('"feature_count": 18','"feature_count": 19'));await assert.rejects(resolveActiveModel(repository,path.join(fixtureRoot,"profile")),error=>error.code==="active_model_integrity_error");
  await writeFile(quick,quickOriginal);await writeFile(lifecycle,lifecycleOriginal.replace('"policy_status": "active"','"policy_status": "inactive"'));await assert.rejects(resolveActiveModel(repository,path.join(fixtureRoot,"profile")),error=>error.code==="model_lifecycle_policy_invalid");
 }finally{await stop(server.child);await rm(temporary,{recursive:true,force:true})}
});
