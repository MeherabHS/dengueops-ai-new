import test from "node:test";
import assert from "node:assert/strict";
import {cp,mkdtemp,readFile,rm} from "node:fs/promises";
import {spawn,spawnSync} from "node:child_process";
import {tmpdir} from "node:os";
import path from "node:path";
import net from "node:net";

const root=process.cwd(),python="C:\\Users\\CUBE\\AppData\\Local\\Programs\\Python\\Python313\\python.exe",secret="phase-b-decision-secret-123";
async function port(){return await new Promise((resolve,reject)=>{const s=net.createServer();s.listen(0,"127.0.0.1",()=>{const a=s.address();s.close(()=>resolve(a.port))});s.on("error",reject)})}
async function start(runtime){const p=await port(),child=spawn(process.execPath,[path.join(root,"node_modules/next/dist/bin/next"),"dev","-H","127.0.0.1","-p",String(p)],{cwd:root,env:{...process.env,DENGUEOPS_RUNTIME_ROOT:runtime,DENGUEOPS_INTERNAL_DECISION_ENABLED:"true",DENGUEOPS_INTERNAL_DECISION_SECRET:secret,DENGUEOPS_INTERNAL_OPERATOR_ID:"phase-b-server-operator",DENGUEOPS_INTERNAL_MONITORING_ENABLED:"false",DENGUEOPS_INTERNAL_MODEL_LIFECYCLE_ENABLED:"false"},stdio:["ignore","pipe","pipe"]});let logs="";child.stdout.on("data",v=>logs+=v);child.stderr.on("data",v=>logs+=v);const url=`http://127.0.0.1:${p}`;for(let i=0;i<100;i++){try{await fetch(`${url}/api/dashboard/latest`);return{child,url,logs:()=>logs}}catch{await new Promise(r=>setTimeout(r,100))}}throw new Error(logs)}
async function stop(child){child.kill();await new Promise(r=>setTimeout(r,250))}
async function post(server,id,body){return fetch(`${server.url}/api/runtime/assessments/${id}/decisions`,{method:"POST",headers:{"content-type":"application/json","x-dengueops-internal-decision-secret":secret},body:JSON.stringify(body)})}

test("p2-v2 decision route functionally governs winner and eligible override",{timeout:180000},async()=>{
 const temporary=await mkdtemp(path.join(tmpdir(),"dengueops-phase-b-decision-")),built=spawnSync(python,["-m","tests.runtime_phase_b_fixture_cli",path.join(temporary,"base")],{cwd:root,env:{...process.env,PYTHONDONTWRITEBYTECODE:"1"},encoding:"utf8",timeout:150000});assert.equal(built.status,0,built.stderr);const fixture=JSON.parse(built.stdout.trim().split(/\r?\n/).at(-1));
 try{
  const winnerRuntime=path.join(temporary,"winner"),overrideRuntime=path.join(temporary,"override");await cp(fixture.runtime,winnerRuntime,{recursive:true});await cp(fixture.runtime,overrideRuntime,{recursive:true});
  let server=await start(winnerRuntime);try{const response=await post(server,fixture.assessmentId,{decision:"approve_technical_winner",reason:"Use the governed technical winner for this one run.",expectedAssessmentSummarySha256:fixture.summarySha256,uncertaintyLimitationsAcknowledged:true});if(response.status!==201)assert.fail(await response.text());const value=await response.json();const decision=JSON.parse(await readFile(path.join(winnerRuntime,"decisions",value.decisionId,"decision.json"),"utf8"));assert.equal(decision.decisionPolicyVersion,"p2-v2");assert.equal(decision.selectedModelId,fixture.winner);assert.equal(decision.deploymentModelAdopted,false);assert.equal(decision.operatorIdentifier,"phase-b-server-operator");assert.equal(decision.selectionType,"technical_winner")}finally{await stop(server.child)}
  server=await start(overrideRuntime);try{for(const body of [
    {decision:"approve_eligible_non_winner",reason:"Invalid baseline.",expectedAssessmentSummarySha256:fixture.summarySha256,selectedModelId:fixture.baseline,technicalWinnerNotSelectedAcknowledged:true,uncertaintyLimitationsAcknowledged:true},
    {decision:"approve_eligible_non_winner",reason:"Missing acknowledgement.",expectedAssessmentSummarySha256:fixture.summarySha256,selectedModelId:fixture.eligibleNonWinner,technicalWinnerNotSelectedAcknowledged:false,uncertaintyLimitationsAcknowledged:true},
    {decision:"approve_eligible_non_winner",reason:"Arbitrary model.",expectedAssessmentSummarySha256:fixture.summarySha256,selectedModelId:"arbitrary_model",technicalWinnerNotSelectedAcknowledged:true,uncertaintyLimitationsAcknowledged:true},
  ]){const response=await post(server,fixture.assessmentId,body);assert.notEqual(response.status,201)}
  const response=await post(server,fixture.assessmentId,{decision:"approve_eligible_non_winner",reason:"Use an eligible challenger for dataset-specific sensitivity evidence.",expectedAssessmentSummarySha256:fixture.summarySha256,selectedModelId:fixture.eligibleNonWinner,technicalWinnerNotSelectedAcknowledged:true,uncertaintyLimitationsAcknowledged:true});if(response.status!==201)assert.fail(await response.text());const value=await response.json(),decision=JSON.parse(await readFile(path.join(overrideRuntime,"decisions",value.decisionId,"decision.json"),"utf8"));assert.equal(decision.technicalWinnerModelId,fixture.winner);assert.equal(decision.selectedModelId,fixture.eligibleNonWinner);assert.equal(decision.selectionType,"eligible_non_winner_override");assert.equal(decision.technicalWinnerNotSelectedAcknowledged,true);assert.equal(decision.deploymentModelAdopted,false)}finally{await stop(server.child)}
 }finally{await rm(temporary,{recursive:true,force:true})}
});
