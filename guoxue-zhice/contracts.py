from service import GuoxueService
REQUIRED_SERVICE_METHODS=("analyze_goal","one_click_update","one_click_repair","save_review","stats")
def assert_service_contract(service: GuoxueService):
    missing=[name for name in REQUIRED_SERVICE_METHODS if not callable(getattr(service,name,None))]
    if missing: raise AssertionError(f"service contract missing: {missing}")
def assert_analysis_contract(value):
    required={"goal","timestamp","scenarios","questions","methods","five_whys","reverse_validation","status"}
    missing=required.difference(value)
    if missing: raise AssertionError(f"analysis contract missing: {sorted(missing)}")
    if value["status"]!="ACTION_HYPOTHESIS": raise AssertionError("analysis must not masquerade as verified fact")
    if len(value["five_whys"])!=5: raise AssertionError("5 Why contract violated")
