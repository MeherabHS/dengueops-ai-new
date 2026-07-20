"""Build complete lifecycle resolver fixtures under a caller-owned temporary root."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"analytics"))

from runtime_active_model import PROFILE_SHA
from runtime_commit import atomic_json, sha256_file
from runtime_model_lifecycle import execute
from tests.lifecycle_fixtures import build_promotion_chain
from tests.test_runtime_model_lifecycle import lifecycle_job
from tests.test_runtime_model_lifecycle_commit import promotion_job

def snapshot(source: Path, destination: Path) -> None:
    if destination.exists(): shutil.rmtree(destination)
    shutil.copytree(source,destination,copy_function=shutil.copyfile)


def main(output: Path) -> None:
    output.mkdir(parents=True,exist_ok=True)
    chain=build_promotion_chain(output/"source",ROOT,"random_forest")
    runtime=chain["runtime"]
    profile=output/"profile";profile.mkdir()
    bootstrap,bootstrap_path=lifecycle_job(runtime,expectedProfileSha256=PROFILE_SHA)
    execute(bootstrap_path,runtime,runtime/"lifecycle-staging"/bootstrap["lifecycleDecisionId"],ROOT)
    snapshot(runtime,output/"bootstrap")
    promotion,promotion_path=promotion_job(runtime,chain)
    pointer=runtime/"deployments/dhaka_south/model-assignment/latest.json"
    promotion.update(expectedAssignmentPointerState="present",expectedAssignmentPointerSha256=sha256_file(pointer));atomic_json(promotion_path,promotion)
    execute(promotion_path,runtime,runtime/"lifecycle-staging"/promotion["lifecycleDecisionId"],ROOT)
    snapshot(runtime,output/"promotion")
    rollback,rollback_path=lifecycle_job(runtime,"rollback_previous_assignment",expectedAssignmentPointerState="present",expectedAssignmentPointerSha256=sha256_file(pointer))
    execute(rollback_path,runtime,runtime/"lifecycle-staging"/rollback["lifecycleDecisionId"],ROOT)
    snapshot(runtime,output/"rollback")
    print(json.dumps({"profile":str(profile),"bootstrap":str(output/"bootstrap"),"promotion":str(output/"promotion"),"rollback":str(output/"rollback")}))


if __name__=="__main__": main(Path(sys.argv[1]).resolve())
