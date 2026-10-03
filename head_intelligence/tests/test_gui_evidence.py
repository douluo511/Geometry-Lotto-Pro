import copy
import pytest
from head_intelligence.bind_physical_gui import OPERATIONS, REPAIR_CHECKS, bind


def evidence_pair():
    buttons=[{"operation":name,"status":"PASS","visual_changed":True,"process_id":100+i,
              "operation_status":"BLOCKED" if name in {"software_update","repair"} else "PASS"}
             for i,name in enumerate(OPERATIONS)]
    value={"schema":"head-intelligence-physical-gui-v2","status":"PASS","gui_run_id":"fresh-run","buttons":buttons}
    by_name={name:{"status":button["operation_status"],"process_id":button["process_id"],"gui_run_id":"fresh-run","completed_at":"2026-10-03T00:00:00+00:00"}
             for name,button in zip(OPERATIONS,buttons)}
    snapshot={"status":"PASS","items":[{"title":"official data"}]}
    by_name["information_judgment"]["snapshot"]=snapshot
    by_name["advanced_analysis"].update(snapshot=snapshot,business_dimensions=list(range(6)))
    by_name["repair"].update(local_integrity_status="PASS",actions=["RESTORED_VERIFIED_SNAPSHOT"],
                           checks={key:{"status":"BLOCKED" if key=="network_configuration" else "PASS"} for key in REPAIR_CHECKS})
    return value,{"schema":"head-intelligence-gui-operations-v1","main_exe_sha256":"a"*64,"gui_run_id":"fresh-run","operations":by_name}


def test_blocked_release_gui_is_explicitly_stage_only():
    value,operations=evidence_pair()
    assert bind(value,operations,"a"*64)["release_mode"]=="BlockedRelease"


@pytest.mark.parametrize("field,value",[("gui_run_id","stale-run"),("process_id",999),("status","FAIL")])
def test_unrelated_or_failed_backend_cannot_bind(field,value):
    physical,operations=evidence_pair()
    operations["operations"]["repair"][field]=value
    with pytest.raises(ValueError):bind(physical,operations,"a"*64)


def test_duplicate_clicks_cannot_satisfy_four_operations():
    physical,operations=evidence_pair()
    physical["buttons"][3]=copy.deepcopy(physical["buttons"][0])
    with pytest.raises(ValueError):bind(physical,operations,"a"*64)


def test_repair_must_check_all_eight_keys():
    physical,operations=evidence_pair()
    operations["operations"]["repair"]["checks"].pop("data_integrity")
    with pytest.raises(ValueError):bind(physical,operations,"a"*64)
