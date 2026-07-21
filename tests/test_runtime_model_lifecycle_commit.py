import tempfile
import unittest
import json
import shutil
import copy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from tests.lifecycle_fixtures import build_promotion_chain
from tests.test_runtime_model_lifecycle import lifecycle_job
from runtime_model_lifecycle import execute
from runtime_model_lifecycle import prepare_bundle,verify_action_sources
import runtime_model_lifecycle_commit as lifecycle_commit
from runtime_model_lifecycle_commit import commit_lifecycle
from runtime_model_lifecycle_source import assignment_pointer_state
from runtime_commit import atomic_json,sha256_file
from runtime_active_model import PROFILE_SHA, resolve_active_model, resolve_historical_active_model_p2_v1

ROOT=Path(__file__).resolve().parents[1]


def resolve_historical(runtime: Path) -> dict:
    return resolve_historical_active_model_p2_v1(repository_root=ROOT, runtime_root=runtime)



def promotion_job(runtime:Path,chain:dict):
    fields={f"expected{key[0].upper()}{key[1:]}":value for key,value in chain.items() if key.endswith("Sha256") and key not in {"runtime"}}
    return lifecycle_job(runtime,"promote_selected_model",**fields)


def mutate_first_key(value,key):
    if isinstance(value,dict):
        if key in value:
            current=value[key]
            if isinstance(current,bool):value[key]=not current
            elif isinstance(current,str):value[key]="tampered-"+current
            elif isinstance(current,(int,float)):value[key]=current+1
            elif current is None:value[key]="tampered"
            elif isinstance(current,list):value[key]=current+[current[0] if current else "tampered"]
            else:value[key]={**current,"tampered":True}
            return True
        return any(mutate_first_key(child,key) for child in value.values())
    if isinstance(value,list):return any(mutate_first_key(child,key) for child in value)
    return False


class LifecycleCommitTests(unittest.TestCase):
    def test_absent_pointer_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:self.assertEqual(assignment_pointer_state(Path(directory)),("absent",None))

    def test_feature_order_identity_is_independent_and_reconciled(self):
        with tempfile.TemporaryDirectory() as directory:
            state=lifecycle_commit._protected_state(ROOT,Path(directory))
            self.assertEqual(state["featureOrderIdentity"],"aeccbe517da452e1132f08c02599418523fb003280b11ff9cda66cfb3aa55a85")
            self.assertNotEqual(state["featureOrderIdentity"],state["featureEngineering"])

    def test_every_protected_state_mutation_blocks_pointer_before_publication(self):
        keys=("profile","candidateRegistry","featureEngineering","featureOrderIdentity","quickPolicy","forecastLatest","monitoringLatest","degradationLatest","authorizationState")
        for key in keys:
            with self.subTest(protected=key),tempfile.TemporaryDirectory() as directory:
                runtime=Path(directory);job,path=lifecycle_job(runtime,expectedProfileSha256=PROFILE_SHA)
                original=lifecycle_commit._protected_state;calls=0
                def observed(repository_root,runtime_root):
                    nonlocal calls
                    calls+=1;state=original(repository_root,runtime_root)
                    if calls==2:state[key]="MUTATED"
                    return state
                with mock.patch.object(lifecycle_commit,"_protected_state",side_effect=observed):
                    with self.assertRaisesRegex(ValueError,"unrelated_protected_state_modified_before_pointer_publication"):
                        execute(path,runtime,runtime/"lifecycle-staging"/job["lifecycleDecisionId"],ROOT)
                self.assertEqual(assignment_pointer_state(runtime),("absent",None))
                self.assertTrue((runtime/"model-lifecycle"/job["lifecycleDecisionId"]).is_dir())

    def test_post_publication_protected_state_reverification_detects_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime=Path(directory);job,path=lifecycle_job(runtime,expectedProfileSha256=PROFILE_SHA);original=lifecycle_commit._protected_state;calls=0
            def observed(repository_root,runtime_root):
                nonlocal calls
                calls+=1;state=original(repository_root,runtime_root)
                if calls==3:state["featureOrderIdentity"]="MUTATED"
                return state
            with mock.patch.object(lifecycle_commit,"_protected_state",side_effect=observed):
                with self.assertRaisesRegex(ValueError,"unrelated_protected_state_modified"):
                    execute(path,runtime,runtime/"lifecycle-staging"/job["lifecycleDecisionId"],ROOT)
            self.assertEqual(assignment_pointer_state(runtime)[0],"present")

    def test_full_random_forest_promotion_chain_commits_assignment(self):
        with tempfile.TemporaryDirectory() as directory:
            chain=build_promotion_chain(Path(directory)/"fixture",ROOT,"random_forest");runtime=chain["runtime"];job,path=promotion_job(runtime,chain)
            result=execute(path,runtime,runtime/"lifecycle-staging"/job["lifecycleDecisionId"],ROOT)
            self.assertIsNotNone(result["assignmentId"]);self.assertEqual(assignment_pointer_state(runtime)[0],"present")
            assignment=runtime/"model-lifecycle"/job["lifecycleDecisionId"]/"artifacts/model_assignment.json"
            self.assertIn('"modelIdentityChanged": false',assignment.read_text())

    def test_first_promotion_from_profile_fallback_recovers_only_exact_orphan(self):
        with tempfile.TemporaryDirectory() as directory:
            chain=build_promotion_chain(Path(directory)/"fixture",ROOT,"random_forest");runtime=chain["runtime"];job,path=promotion_job(runtime,chain);staging=runtime/"lifecycle-staging"/job["lifecycleDecisionId"]
            active=resolve_historical(runtime);verified=verify_action_sources(ROOT,runtime,job,active);bundle=prepare_bundle(ROOT,runtime,job,active,verified)
            (staging/"artifacts").mkdir(parents=True);(staging/"metadata").mkdir()
            for relative,value in (("artifacts/lifecycle_decision.json",bundle["decision"]),("metadata/lifecycle_decision_commit.json",bundle["decisionCommit"]),("artifacts/model_assignment.json",bundle["assignment"]),("metadata/model_assignment_commit.json",bundle["assignmentCommit"])):atomic_json(staging/relative,value)
            with self.assertRaisesRegex(OSError,"injected_assignment_pointer_publication_failure"):commit_lifecycle(ROOT,runtime,path,staging,fail_pointer_publication_for_test=True)
            orphan=runtime/"model-lifecycle"/job["lifecycleDecisionId"];self.assertTrue(orphan.is_dir());self.assertFalse((runtime/"deployments/dhaka_south/model-assignment/latest.json").exists())
            with self.assertRaises(Exception):resolve_historical(runtime)

            original=copy.deepcopy(job)
            conflicts=[("reason","conflicting retry"),("manualActionAcknowledged",False),("expectedAssessmentCommitSha256","0"*64),("expectedDecisionCommitSha256","0"*64),("expectedAuthorizationCommitSha256","0"*64),("expectedApprovedForecastCommitSha256","0"*64),("expectedOutcomeCommitSha256","0"*64),("expectedMonitoringLatestSha256","0"*64),("expectedDegradationEvidenceSha256","0"*64)]
            for key,value in conflicts:
                with self.subTest(conflict=key):
                    conflicting={**original,key:value};atomic_json(path,conflicting)
                    with self.assertRaises(Exception):execute(path,runtime,runtime/f"conflict-{key}",ROOT)
                    self.assertFalse((runtime/"deployments/dhaka_south/model-assignment/latest.json").exists());self.assertTrue(orphan.is_dir())
            atomic_json(path,original);result=execute(path,runtime,runtime/"retry-staging",ROOT)
            self.assertTrue(result["recovered"]);self.assertEqual(len(list((runtime/"model-lifecycle").glob("*/artifacts/model_assignment.json"))),1)

    def test_promotion_orphan_with_active_prior_pointer_recovers_only_missing_pointer(self):
        with tempfile.TemporaryDirectory() as directory:
            chain=build_promotion_chain(Path(directory)/"fixture",ROOT,"random_forest");runtime=chain["runtime"]
            bootstrap,bootstrap_path=lifecycle_job(runtime,expectedProfileSha256=PROFILE_SHA);execute(bootstrap_path,runtime,runtime/"lifecycle-staging"/bootstrap["lifecycleDecisionId"],ROOT)
            pointer=runtime/"deployments/dhaka_south/model-assignment/latest.json";prior_pointer=pointer.read_bytes()
            job,path=promotion_job(runtime,chain);job.update({"expectedAssignmentPointerState":"present","expectedAssignmentPointerSha256":sha256_file(pointer)});atomic_json(path,job);staging=runtime/"lifecycle-staging"/job["lifecycleDecisionId"]
            active=resolve_historical(runtime);verified=verify_action_sources(ROOT,runtime,job,active);bundle=prepare_bundle(ROOT,runtime,job,active,verified)
            (staging/"artifacts").mkdir(parents=True);(staging/"metadata").mkdir()
            for relative,value in (("artifacts/lifecycle_decision.json",bundle["decision"]),("metadata/lifecycle_decision_commit.json",bundle["decisionCommit"]),("artifacts/model_assignment.json",bundle["assignment"]),("metadata/model_assignment_commit.json",bundle["assignmentCommit"])):atomic_json(staging/relative,value)
            with self.assertRaisesRegex(OSError,"injected_assignment_pointer_publication_failure"):commit_lifecycle(ROOT,runtime,path,staging,fail_pointer_publication_for_test=True)
            self.assertEqual(pointer.read_bytes(),prior_pointer)
            with self.assertRaises(Exception):resolve_historical(runtime)
            result=execute(path,runtime,runtime/"retry-staging",ROOT)
            self.assertTrue(result["recovered"]);self.assertNotEqual(pointer.read_bytes(),prior_pointer);self.assertEqual(len(list((runtime/"model-lifecycle").glob("*/artifacts/model_assignment.json"))),2)

    def test_first_promotion_recovery_rejects_arbitrary_and_incomplete_orphans(self):
        with tempfile.TemporaryDirectory() as directory:
            chain=build_promotion_chain(Path(directory)/"fixture",ROOT,"random_forest");runtime=chain["runtime"];job,path=promotion_job(runtime,chain);staging=runtime/"lifecycle-staging"/job["lifecycleDecisionId"]
            active=resolve_historical(runtime);bundle=prepare_bundle(ROOT,runtime,job,active,verify_action_sources(ROOT,runtime,job,active));(staging/"artifacts").mkdir(parents=True);(staging/"metadata").mkdir()

            for relative,value in (("artifacts/lifecycle_decision.json",bundle["decision"]),("metadata/lifecycle_decision_commit.json",bundle["decisionCommit"]),("artifacts/model_assignment.json",bundle["assignment"]),("metadata/model_assignment_commit.json",bundle["assignmentCommit"])):atomic_json(staging/relative,value)
            with self.assertRaises(OSError):commit_lifecycle(ROOT,runtime,path,staging,fail_pointer_publication_for_test=True)
            orphan=runtime/"model-lifecycle"/job["lifecycleDecisionId"];arbitrary=runtime/"model-lifecycle"/"00000000-0000-4000-8000-000000000091";shutil.copytree(orphan,arbitrary);(arbitrary/"metadata/model_assignment_commit.json").unlink()
            with self.assertRaises(Exception):execute(path,runtime,runtime/"retry-staging",ROOT)
            self.assertTrue(orphan.is_dir());self.assertTrue(arbitrary.is_dir());self.assertEqual(assignment_pointer_state(runtime),("absent",None))

    def test_non_random_forest_full_chains_reach_compatibility_rejection(self):
        for model_id in ("ridge_regression","poisson_regression","gradient_boosting"):
            with self.subTest(model=model_id),tempfile.TemporaryDirectory() as directory:
                chain=build_promotion_chain(Path(directory)/"fixture",ROOT,model_id);runtime=chain["runtime"];job,path=promotion_job(runtime,chain)
                with self.assertRaisesRegex(ValueError,"selected_model_not_active_quick_forecast_compatible"):
                    execute(path,runtime,runtime/"lifecycle-staging"/job["lifecycleDecisionId"],ROOT)
                self.assertEqual(assignment_pointer_state(runtime),("absent",None))

    def test_decision_choice_tampering_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            base=build_promotion_chain(Path(directory)/"fixture",ROOT,"random_forest")
            for index,(choice,status) in enumerate((("keep_current_model","current_model_retained"),("defer","deferred"),("reject","rejected"),("approve_technical_winner","incomplete"))):
                with self.subTest(choice=choice,status=status):
                    runtime=Path(directory)/f"choice-{index}";shutil.copytree(base["runtime"],runtime,copy_function=shutil.copyfile);chain={**base,"runtime":runtime};decision=runtime/"decisions"/chain["decisionId"]/"decision.json";value=json.loads(decision.read_text());value["decision"]=choice;value["decisionStatus"]=status;atomic_json(decision,value)
                    job,path=promotion_job(runtime,chain)
                    with self.assertRaises(Exception):execute(path,runtime,runtime/"lifecycle-staging"/job["lifecycleDecisionId"],ROOT)
                    self.assertEqual(assignment_pointer_state(runtime),("absent",None))

    def test_promotion_chain_tampering_matrix_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            base=build_promotion_chain(Path(directory)/"fixture",ROOT,"random_forest")
            relative=[f"assessments/{base['assessmentId']}/metadata/commit.json",f"decisions/{base['decisionId']}/commit.json",f"authorization-state/{base['authorizationId']}/consumption.json",f"runs/{base['runId']}/artifacts/forecast_output.json",f"forecast-outcomes/{base['outcomeId']}/artifacts/outcome_evaluation.json","deployments/dhaka_south/monitoring/latest.json","deployments/dhaka_south/degradation/latest.json"]
            for index,target in enumerate(relative):
                with self.subTest(target=target):
                    runtime=Path(directory)/f"tamper-{index}";shutil.copytree(base["runtime"],runtime,copy_function=shutil.copyfile);chain={**base,"runtime":runtime};path=runtime/target;path.write_bytes(path.read_bytes()+b"\n")
                    job,job_path=promotion_job(runtime,chain)
                    with self.assertRaises(Exception):execute(job_path,runtime,runtime/"lifecycle-staging"/job["lifecycleDecisionId"],ROOT)
                    self.assertEqual(assignment_pointer_state(runtime),("absent",None))

    def test_field_specific_complete_promotion_tampering_matrix(self):
        with tempfile.TemporaryDirectory() as directory:
            base=build_promotion_chain(Path(directory)/"fixture",ROOT,"random_forest")
            aid,did,auth,rid,oid=(base[key] for key in ("assessmentId","decisionId","authorizationId","runId","outcomeId"));eid=json.loads((base["runtime"]/"deployments/dhaka_south/degradation/latest.json").read_text())["evidenceId"]
            assessment=[(f"assessments/{aid}/metadata/assessment.json",key) for key in ("assessmentId","jobId","deploymentId","acceptedPeriod","candidateRegistrySha256","foldPlanSha256","plannedFoldCount","selectedEvaluationPeriod")]+[(f"assessments/{aid}/metadata/commit.json",key) for key in ("assessmentId","artifactHashes","candidateRegistrySha256","foldPlanSha256")]+[(f"assessments/{aid}/artifacts/assessment_summary.json",key) for key in ("technicalWinnerModelId","successfulFolds","failedFolds")]+[(f"assessments/{aid}/artifacts/rolling_validation.json",key) for key in ("folds","featureOrderSha256")]+[(f"assessments/{aid}/artifacts/candidate_model_comparison.json","winnerParameterSha256")]
            decision=[(f"decisions/{did}/decision.json",key) for key in ("decisionId","decision","decisionStatus","technicalWinnerModelId","selectedModelId","selectedModelParameterSha256","assessmentId","decisionPolicySha256","candidateRegistrySha256")]+[(f"decisions/{did}/commit.json",key) for key in ("decisionSha256","assessmentCommitSha256","status")]
            authorization=[(f"authorizations/{auth}/authorization.json",key) for key in ("authorizationId","decisionId","assessmentId","selectedModelId","selectedModelParameterSha256","scope","expiresAt","decisionCommitSha256")]+[(f"authorizations/{auth}/commit.json",key) for key in ("authorizationId","authorizationSha256","status")]+[(f"authorization-state/{auth}/reservation.json",key) for key in ("authorizationId","eventId","eventType","jobId","runId")]+[(f"authorization-state/{auth}/consumption.json",key) for key in ("authorizationId","decisionId","eventId","jobId","runId","createdAt")]
            forecast=[(f"runs/{rid}/metadata/run.json",key) for key in ("runId","jobId","selectedModelId","selectedModelParameterSha256","trainingRowCount")]+[(f"runs/{rid}/artifacts/forecast_output.json",key) for key in ("forecastReported","target","horizonWeeks","featureMatrixSha256")]+[(f"runs/{rid}/artifacts/model_card.json",key) for key in ("family","parameterHash","trainingRowCount")]+[(f"runs/{rid}/metadata/commit.json",key) for key in ("artifactHashes","forecastOutputSha256","modelCardSha256")]
            outcome=[(f"forecast-outcomes/{oid}/artifacts/outcome_evaluation.json",key) for key in ("outcomeId","sourceForecastRunId","sourceForecastCommitSha256","targetColumn","forecastHorizonWeeks","forecastTargetPeriod","observedRaw","modelId","modelFamily")]+[(f"forecast-outcomes/{oid}/metadata/commit.json","forecastCommitSha256")]
            monitoring=[("deployments/dhaka_south/monitoring/latest.json",key) for key in ("outcomeId","outcomeCommitSha256","monitoringSummarySha256")]+[(f"forecast-outcomes/{oid}/artifacts/monitoring_summary.json",key) for key in ("outcomeSetSha256","includedOutcomes","outcomeEvidenceSha256","modelBreakdowns","sourceFamily","policySha256","evaluatedForecastCount","outcomeId")]
            degradation=[("deployments/dhaka_south/degradation/latest.json",key) for key in ("commitSha256","evidenceSha256","summarySha256","monitoringLatestInputSha256")]+[(f"degradation-evidence/{eid}/metadata/commit.json",key) for key in ("artifactHashes","monitoringSummarySha256","includedOutcomeSetSha256","assessmentReferences")]+[(f"degradation-evidence/{eid}/artifacts/degradation_evidence.json",key) for key in ("monitoringInput","orderedOutcomes","cohortId","assessmentCommitSha256","modelId","evidenceStatus","materialWorseningStatus","lifecycleActionStatus")]+[(f"degradation-evidence/{eid}/artifacts/degradation_summary.json","cohortCount")]
            categories={"assessment":assessment,"decision":decision,"authorization_consumption":authorization,"approved_forecast":forecast,"outcome":outcome,"monitoring":monitoring,"degradation":degradation}
            self.assertEqual({key:len(value) for key,value in categories.items()},{"assessment":18,"decision":12,"authorization_consumption":22,"approved_forecast":15,"outcome":10,"monitoring":11,"degradation":17})
            case=0
            for category,values in categories.items():
                for relative,key in values:
                    case+=1
                    with self.subTest(category=category,field=key):
                        runtime=Path(directory)/f"field-{case}";shutil.copytree(base["runtime"],runtime,copy_function=shutil.copyfile)
                        target=runtime/relative;value=json.loads(target.read_text());self.assertTrue(mutate_first_key(value,key),f"missing {key} in {relative}");atomic_json(target,value)
                        protected=lifecycle_commit._protected_state(ROOT,runtime);job,path=promotion_job(runtime,{**base,"runtime":runtime})
                        with self.assertRaises(Exception) as failure:execute(path,runtime,runtime/"lifecycle-staging"/job["lifecycleDecisionId"],ROOT)
                        self.assertNotIn(str(runtime),str(failure.exception));self.assertEqual(assignment_pointer_state(runtime),("absent",None));self.assertEqual(lifecycle_commit._protected_state(ROOT,runtime),protected)
            self.assertEqual(case,105)

    def test_retention_defer_and_reject_verify_context_without_assignment(self):
        with tempfile.TemporaryDirectory() as directory:
            chain=build_promotion_chain(Path(directory)/"fixture",ROOT,"random_forest");runtime=chain["runtime"]
            context={"evidenceContextStatus":"verified_monitoring_and_degradation",**{f"expected{key[0].upper()}{key[1:]}":chain[key] for key in ("monitoringLatestSha256","monitoringSummarySha256","monitoringIncludedOutcomeSetSha256","degradationLatestSha256","degradationEvidenceCommitSha256","degradationEvidenceSha256")}}
            for action in ("retain_current_model","defer","reject"):
                job,path=lifecycle_job(runtime,action,**context);result=execute(path,runtime,runtime/"lifecycle-staging"/job["lifecycleDecisionId"],ROOT)
                self.assertIsNone(result["assignmentId"]);self.assertFalse((runtime/"model-lifecycle"/job["lifecycleDecisionId"]/"artifacts/model_assignment.json").exists())
            assessment_reject,path=lifecycle_job(runtime,"reject",evidenceContextStatus="verified_assessment_and_decision",expectedAssessmentCommitSha256=chain["assessmentCommitSha256"],expectedDecisionCommitSha256=chain["decisionCommitSha256"]);result=execute(path,runtime,runtime/"lifecycle-staging"/assessment_reject["lifecycleDecisionId"],ROOT)
            self.assertIsNone(result["assignmentId"]);self.assertFalse((runtime/"model-lifecycle"/assessment_reject["lifecycleDecisionId"]/"artifacts/model_assignment.json").exists())
            self.assertEqual(assignment_pointer_state(runtime),("absent",None))
            summary=next(runtime.glob("forecast-outcomes/*/artifacts/monitoring_summary.json"));summary.write_bytes(summary.read_bytes()+b"\n")
            job,path=lifecycle_job(runtime,"retain_current_model",**context)
            with self.assertRaises(Exception):execute(path,runtime,runtime/"lifecycle-staging"/job["lifecycleDecisionId"],ROOT)

    def test_rollback_creates_new_assignment_from_immediate_prior(self):
        with tempfile.TemporaryDirectory() as directory:
            chain=build_promotion_chain(Path(directory)/"fixture",ROOT,"random_forest");runtime=chain["runtime"]
            bootstrap,bootstrap_path=lifecycle_job(runtime,expectedProfileSha256=PROFILE_SHA);execute(bootstrap_path,runtime,runtime/"lifecycle-staging"/bootstrap["lifecycleDecisionId"],ROOT)
            first_pointer=runtime/"deployments/dhaka_south/model-assignment/latest.json";first_hash=sha256_file(first_pointer);first_assignment=resolve_historical(runtime)["assignmentId"]
            promotion,promotion_path=promotion_job(runtime,chain);promotion["expectedAssignmentPointerState"]="present";promotion["expectedAssignmentPointerSha256"]=first_hash;promotion_path.write_text(json.dumps(promotion),encoding="utf-8");execute(promotion_path,runtime,runtime/"lifecycle-staging"/promotion["lifecycleDecisionId"],ROOT)
            promoted=resolve_historical(runtime);promoted_hash=sha256_file(first_pointer)
            rollback,rollback_path=lifecycle_job(runtime,"rollback_previous_assignment",expectedAssignmentPointerState="present",expectedAssignmentPointerSha256=promoted_hash);execute(rollback_path,runtime,runtime/"lifecycle-staging"/rollback["lifecycleDecisionId"],ROOT)
            restored=resolve_historical(runtime);self.assertNotEqual(restored["assignmentId"],first_assignment);self.assertEqual(restored["priorAssignmentId"],promoted["assignmentId"])
            assignment=json.loads((runtime/"model-lifecycle"/rollback["lifecycleDecisionId"]/"artifacts/model_assignment.json").read_text());self.assertEqual(assignment["rollbackSourceAssignmentId"],first_assignment);self.assertFalse(assignment["modelIdentityChanged"])


    def test_two_promotions_with_same_expected_pointer_publish_exactly_one(self):
        with tempfile.TemporaryDirectory() as directory:
            chain=build_promotion_chain(Path(directory)/"fixture",ROOT,"random_forest");runtime=chain["runtime"];jobs=[promotion_job(runtime,chain) for _ in range(2)]
            def run(pair):
                job,path=pair
                try:return execute(path,runtime,runtime/"lifecycle-staging"/job["lifecycleDecisionId"],ROOT)
                except Exception as error:return error
            with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,jobs))
            self.assertEqual(sum(isinstance(result,dict) for result in results),1);self.assertEqual(assignment_pointer_state(runtime)[0],"present")

    def test_assignment_race_combinations_publish_at_most_one_new_assignment(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);chain=build_promotion_chain(root/"fixture",ROOT,"random_forest");base=chain["runtime"]
            bootstrap,bootstrap_path=lifecycle_job(base,expectedProfileSha256=PROFILE_SHA);execute(bootstrap_path,base,base/"lifecycle-staging"/bootstrap["lifecycleDecisionId"],ROOT)
            pointer=base/"deployments/dhaka_south/model-assignment/latest.json";pointer_hash=sha256_file(pointer)
            initial,initial_path=promotion_job(base,chain);initial.update({"expectedAssignmentPointerState":"present","expectedAssignmentPointerSha256":pointer_hash});initial_path.write_text(json.dumps(initial),encoding="utf-8");execute(initial_path,base,base/"lifecycle-staging"/initial["lifecycleDecisionId"],ROOT)
            context={"evidenceContextStatus":"verified_monitoring_and_degradation",**{f"expected{key[0].upper()}{key[1:]}":chain[key] for key in ("monitoringLatestSha256","monitoringSummarySha256","monitoringIncludedOutcomeSetSha256","degradationLatestSha256","degradationEvidenceCommitSha256","degradationEvidenceSha256")}}

            for label in ("promotion_rollback","rollback_rollback","retention_promotion"):
                runtime=root/label;shutil.copytree(base,runtime);expected=sha256_file(runtime/"deployments/dhaka_south/model-assignment/latest.json")
                promotion,promotion_path=promotion_job(runtime,chain);promotion.update({"expectedAssignmentPointerState":"present","expectedAssignmentPointerSha256":expected});promotion_path.write_text(json.dumps(promotion),encoding="utf-8")
                rollback_a,rollback_a_path=lifecycle_job(runtime,"rollback_previous_assignment",expectedAssignmentPointerState="present",expectedAssignmentPointerSha256=expected)
                if label=="promotion_rollback":jobs=[(promotion,promotion_path),(rollback_a,rollback_a_path)]
                elif label=="rollback_rollback":
                    rollback_b,rollback_b_path=lifecycle_job(runtime,"rollback_previous_assignment",expectedAssignmentPointerState="present",expectedAssignmentPointerSha256=expected);jobs=[(rollback_a,rollback_a_path),(rollback_b,rollback_b_path)]
                else:
                    retain,retain_path=lifecycle_job(runtime,"retain_current_model",expectedAssignmentPointerState="present",expectedAssignmentPointerSha256=expected,**context);jobs=[(retain,retain_path),(promotion,promotion_path)]
                before=len(list((runtime/"model-lifecycle").glob("*/artifacts/model_assignment.json")))
                def run(pair):
                    job,path=pair
                    try:return execute(path,runtime,runtime/"lifecycle-staging"/job["lifecycleDecisionId"],ROOT)
                    except Exception as error:return error
                with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,jobs))
                after=len(list((runtime/"model-lifecycle").glob("*/artifacts/model_assignment.json")))
                self.assertEqual(after-before,1,label);self.assertEqual(assignment_pointer_state(runtime)[0],"present",label)


if __name__=="__main__":unittest.main()
