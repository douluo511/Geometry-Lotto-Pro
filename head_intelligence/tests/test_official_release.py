import hashlib
import json
import pytest
from head_intelligence.software_release_gate import official_releases


class Receipt:
    def __init__(self,url):self.url=url
    def to_dict(self):return {"final_url":self.url,"http_status":200}


class FixtureNetwork:
    """Offline validator regression; never production release evidence."""
    def __init__(self,mutate=None):self.mutate=mutate
    def get_bytes(self,url,*,source_id):
        binary=b"MZ-offline-test-only"
        if source_id=="official_release_n1_commit":return json.dumps({"sha":"a"*40}).encode(),Receipt(url)
        if source_id.startswith("official_asset"):return binary,Receipt(url)
        label="n1" if source_id.endswith("n1") else "n"
        tag="v0.4.1" if label=="n1" else "v0.4.0"
        value={"tag_name":tag,"id":2 if label=="n1" else 1,"draft":False,"prerelease":False,
               "published_at":"2026-10-03T00:00:00Z","html_url":f"https://github.com/owner/HeadIntelligence/releases/tag/{tag}",
               "assets":[{"name":name,"size":len(binary),"state":"uploaded","browser_download_url":f"https://github.com/owner/HeadIntelligence/releases/download/{tag}/{name}"}
                         for name in ("HeadIntelligence.exe","HeadIntelligence_Updater.exe")]}
        if self.mutate:self.mutate(value)
        return json.dumps(value).encode(),Receipt(url)


def releases():
    digest=hashlib.sha256(b"MZ-offline-test-only").hexdigest()
    return tuple({"version":version,"tag":"v"+version,"release_id":i+1,
                  "release_url":f"https://github.com/owner/HeadIntelligence/releases/tag/v{version}",
                  "main_exe_sha256":digest,"updater_exe_sha256":digest} for i,version in enumerate(("0.4.0","0.4.1")))


def test_validator_fetches_metadata_and_actual_asset_bytes():
    n,n1=releases()
    checks,receipts=official_releases(n,n1,"owner/HeadIntelligence","a"*40,net=FixtureNetwork())
    assert all(check["status"]=="PASS" for check in checks.values())
    assert len(receipts)==7


@pytest.mark.parametrize("change",[lambda value:value.update(draft=True),lambda value:value.update(prerelease=True),
                                  lambda value:value["assets"][0].update(size=1),lambda value:value["assets"][0].update(browser_download_url="https://unrelated.example/file.exe")])
def test_declared_pass_cannot_override_official_metadata(change):
    n,n1=releases()
    checks,_=official_releases(n,n1,"owner/HeadIntelligence","a"*40,net=FixtureNetwork(change))
    assert checks["official_release_n1"]["status"]=="FAIL"


def test_wrong_tag_commit_fails_source_binding():
    n,n1=releases()
    checks,_=official_releases(n,n1,"owner/HeadIntelligence","b"*40,net=FixtureNetwork())
    assert checks["official_tag_source_binding"]["status"]=="FAIL"
