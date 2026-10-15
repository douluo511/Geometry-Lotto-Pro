"""Synthetic fault injection only; never official data or formal P0 acceptance."""
import base64
import copy
import hashlib
import importlib.util
import unittest

from research.ssq_dlt_d2_v44.admission import (
    FORMAL_SLOTS, AdmissionBlocked, admission_report, canonical_bytes, fingerprint,
    prediction_commitment, replay_dual_holdout, validate_candidate_slots, validate_challengers,
    validate_registry, validate_source_pair, verify_ed25519_authorization,
)

VERSIONS = {slot: "synthetic-v1-" + slot for slot in FORMAL_SLOTS}
AS_OF = "2026-01-01T10:00:00+00:00"
CUTOFF = "2026-01-01T11:00:00+00:00"
NOW = "2026-01-01T12:00:00+00:00"
PUBLISHED = "2026-01-01T08:00:00+00:00"


def source(url, *, front=None, publication=PUBLISHED):
    raw = canonical_bytes({"issue": "SYNTH-01", "publication_time": publication,
                           "draw_front": front or [1, 2, 3, 4, 5, 6]})
    return {"origin": "official_original", "requested_url": url, "final_url": url,
            "redirect_chain": [], "raw_bytes": raw,
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "publication_time": publication, "observed_time": "2026-01-01T09:00:00+00:00",
            "publication_path": "/publication_time", "issue_path": "/issue",
            "draw_path": "/draw_front"}


def sources():
    return [source("https://www.cwl.gov.cn/synthetic"),
            source("https://www.swlc.net.cn/synthetic")]


def check_sources(value=None):
    return validate_source_pair("SSQ", "SYNTH-01", sources() if value is None else value,
                                as_of=AS_OF, cutoff=CUTOFF, now=NOW)


def slots():
    # Independent Dk lists deliberately are not prefixes of a ranked five.
    return {slot: {"version": VERSIONS[slot], "D1": [7], "D2": [1, 2],
                   "D3": [3, 4, 8], "D4": [9, 10, 11, 12],
                   "D5": [13, 14, 15, 16, 17]} for slot in FORMAL_SLOTS}


def registry():
    return {"game": "SSQ", "family": "FORMAL-12", "versions": dict(VERSIONS),
            "primary_m05_slot": "M05-2", "registered_at": PUBLISHED,
            "cutoff": CUTOFF, "test_ids": ["SYNTH-test-" + str(k) for k in range(12)],
            "sequential_plan": {"looks": [152, 304], "alpha": "fixed externally"}}


def replay_fixture(size=2):
    ids = ["SYNTH-" + str(i).zfill(3) for i in range(size * 2)]
    rows = []
    for i, issue in enumerate(ids):
        value = slots()
        # A separate null identity, with same-issue success only on a different issue.
        value["M07"]["D2"] = [30, 31]
        rows.append({"game": "SSQ", "issue": issue, "draw_front": [1, 2, 3, 4, 5, 6],
                     "slots": value})
    return rows, ids, {"holdout_a": ids[:size], "holdout_b": ids[size:]}


def replay(rows=None, ids=None, holdouts=None, claimed=None):
    default_rows, default_ids, default_holdouts = replay_fixture()
    selected_rows = default_rows if rows is None else rows
    selected_holdouts = default_holdouts if holdouts is None else holdouts
    return replay_dual_holdout("SSQ", selected_rows,
                               expected_issues=default_ids if ids is None else ids,
                               versions=VERSIONS, primary_m05_slot="M05-2",
                               holdouts=selected_holdouts,
                               expected_holdouts_sha256=fingerprint(selected_holdouts),
                               prediction_commitments={r["issue"]: prediction_commitment(r)
                                                       for r in selected_rows},
                               claimed=claimed)


class TestSources(unittest.TestCase):
    def test_original_hash_and_matching_independent_sources_remain_unproven(self):
        result = check_sources()
        self.assertEqual(result["contract_status"], "PASS")
        self.assertEqual(result["external_publication_proof"], "BLOCKED")
        self.assertEqual(result["official_network"], "NOT_RUN")
        self.assertEqual(result["formal_a_samples"], 0)

    def test_anysearch_discovery_cannot_be_evidence(self):
        value = sources()
        value[0]["origin"] = "AnySearch"
        with self.assertRaisesRegex(AdmissionBlocked, "DISCOVERY"):
            check_sources(value)

    def test_suffix_credentials_http_and_cross_host_redirect_rejected(self):
        for url in ("https://www.cwl.gov.cn.attacker.invalid/a", "http://www.cwl.gov.cn/a",
                    "https://attacker@www.cwl.gov.cn/a", "https://www.cwl.gov.cn:444/a"):
            with self.subTest(url=url), self.assertRaises(AdmissionBlocked):
                value = sources()
                value[0]["final_url"] = url
                check_sources(value)
        value = sources()
        value[0]["redirect_chain"] = ["https://www.swlc.net.cn/a"]
        with self.assertRaisesRegex(AdmissionBlocked, "CROSS_HOST"):
            check_sources(value)

    def test_same_host_is_not_a_second_independent_source(self):
        value = sources()
        value[1] = source("https://www.cwl.gov.cn/second")
        with self.assertRaisesRegex(AdmissionBlocked, "INDEPENDENT_OFFICIAL"):
            check_sources(value)

    def test_raw_hash_tamper_rejected(self):
        value = sources()
        value[0]["raw_bytes"] += b" "
        with self.assertRaisesRegex(AdmissionBlocked, "RAW_HASH"):
            check_sources(value)

    def test_duplicate_raw_publication_fields_rejected(self):
        value = sources()
        value[0]["raw_bytes"] = (b'{"publication_time":"2026-01-01T08:00:00+00:00",'
                                  b'"publication_time":"2026-01-01T08:00:00+00:00"}')
        value[0]["raw_sha256"] = hashlib.sha256(value[0]["raw_bytes"]).hexdigest()
        with self.assertRaisesRegex(AdmissionBlocked, "DUPLICATE_RAW_JSON"):
            check_sources(value)

    def test_conflicting_official_draws_rejected(self):
        value = sources()
        value[1] = source("https://www.swlc.net.cn/a", front=[1, 2, 3, 4, 5, 7])
        with self.assertRaisesRegex(AdmissionBlocked, "SOURCE_CONFLICT"):
            check_sources(value)

    def test_future_publication_observation_and_naive_timestamp_rejected(self):
        for field, time in (("publication_time", "2026-01-01T10:01:00+00:00"),
                            ("observed_time", "2026-01-01T10:01:00+00:00"),
                            ("observed_time", "2026-01-01T09:00:00")):
            with self.subTest(field=field, time=time), self.assertRaises(AdmissionBlocked):
                value = sources()
                if field == "publication_time":
                    value[0] = source("https://www.cwl.gov.cn/a", publication=time)
                else:
                    value[0][field] = time
                check_sources(value)

    def test_missing_or_forged_publication_proof_cannot_pass(self):
        value = sources()
        value[0]["publication_path"] = "/nonexistent"
        value[0]["publication_verified"] = True
        with self.assertRaisesRegex(AdmissionBlocked, "NOT_IN_RAW"):
            check_sources(value)
        value = sources()
        value[0]["publication_time"] = "2026-01-01T07:00:00+00:00"
        with self.assertRaisesRegex(AdmissionBlocked, "PUBLICATION_NOT_BOUND"):
            check_sources(value)


class TestCandidateIdentity(unittest.TestCase):
    def test_non_nested_d1_d5_lists_supported_and_fingerprint_stable(self):
        value = slots()
        before = copy.deepcopy(value)
        digest = validate_candidate_slots("SSQ", value, VERSIONS, "M05-2")
        self.assertEqual(value, before)
        self.assertEqual(len(digest), 64)
        self.assertEqual(digest, validate_candidate_slots("SSQ", copy.deepcopy(value),
                                                        VERSIONS, "M05-2"))

    def test_missing_null_alias_version_swap_and_duplicate_numbers_rejected(self):
        for mutation in ("missing", "alias", "version", "duplicate", "bool", "wrong_k"):
            with self.subTest(mutation=mutation), self.assertRaises(AdmissionBlocked):
                value = slots()
                if mutation == "missing":
                    del value["M05-5"]
                elif mutation == "alias":
                    value["M07-NULL-SHADOW"] = value.pop("M07")
                elif mutation == "version":
                    value["M05-1"]["version"] = "post-result-v2"
                elif mutation == "duplicate":
                    value["M04"]["D2"] = [1, 1]
                elif mutation == "bool":
                    value["M04"]["D1"] = [True]
                else:
                    value["M04"]["D3"] = [1, 2]
                validate_candidate_slots("SSQ", value, VERSIONS, "M05-2")

    def test_m05_primary_cannot_be_chosen_from_results(self):
        with self.assertRaisesRegex(AdmissionBlocked, "PRIMARY"):
            validate_candidate_slots("SSQ", slots(), VERSIONS, "M06")

    def test_registry_hash_prevents_silent_version_or_primary_swap(self):
        value = registry()
        digest = fingerprint(value)
        report = validate_registry(value, digest)
        self.assertEqual(report["external_registration"], "BLOCKED")
        self.assertEqual(report["formal_family_semantics"], "BLOCKED")
        self.assertFalse(report["formal_test_ids_verified"])
        value["primary_m05_slot"] = "M05-5"
        with self.assertRaisesRegex(AdmissionBlocked, "HASH_MISMATCH"):
            validate_registry(value, digest)

    def test_formal_family_requires_twelve_separate_test_ids_and_plan(self):
        value = registry()
        value["test_ids"] = ["same"] * 12
        with self.assertRaisesRegex(AdmissionBlocked, "12_TESTS"):
            validate_registry(value, fingerprint(value))

    def test_new_challenger_cannot_replace_formal_slot_or_family(self):
        good = {"trial_id": "CHALLENGER/pairwise-v1", "family": "trial-family-1",
                "version": "v1", "registered_at": PUBLISHED, "cutoff": CUTOFF}
        self.assertEqual(len(validate_challengers([good], registry())), 64)
        for update in ({"trial_id": "M04"}, {"family": "FORMAL-12"},
                       {"registered_at": CUTOFF}):
            with self.subTest(update=update), self.assertRaises(AdmissionBlocked):
                validate_challengers([dict(good, **update)], registry())


class TestIndependentReplay(unittest.TestCase):
    def test_read_only_replay_scores_actual_dk_and_same_issue_d2(self):
        rows, ids, holdouts = replay_fixture()
        original = copy.deepcopy(rows)
        result = replay(rows, ids, holdouts)
        self.assertEqual(rows, original)
        model = result["summary"]["holdout_a"]["M04"]
        self.assertEqual(model["D1_D5_full"], {"D1": 0, "D2": 2, "D3": 0, "D4": 0, "D5": 0})
        self.assertEqual(model["D2_vs_M07"]["wins"], 2)
        self.assertEqual(model["D2_vs_M07"]["ties"], 0)
        self.assertEqual(result["decision"], "NO_EDGE")

    def test_corrupted_ten_of_152_to_150_of_152_rejected(self):
        rows, ids, holdouts = replay_fixture(152)
        for i, row in enumerate(rows):
            if i % 152 >= 10:
                row["slots"]["M04"]["D2"] = [20, 21]
        result = replay(rows, ids, holdouts)
        self.assertEqual(result["summary"]["holdout_a"]["M04"]["D1_D5_full"]["D2"], 10)
        claimed = copy.deepcopy(result["summary"])
        claimed["holdout_a"]["M04"]["D1_D5_full"]["D2"] = 150
        with self.assertRaisesRegex(AdmissionBlocked, "CLAIM_MISMATCH"):
            replay(rows, ids, holdouts, claimed)

    def test_missing_duplicate_issue_and_holdout_partition_tamper_rejected(self):
        for mutation in ("missing", "duplicate", "partition", "version"):
            with self.subTest(mutation=mutation), self.assertRaises(AdmissionBlocked):
                rows, ids, holdouts = replay_fixture()
                if mutation == "missing":
                    rows.pop()
                elif mutation == "duplicate":
                    rows[1]["issue"] = rows[0]["issue"]
                elif mutation == "partition":
                    holdouts["holdout_b"][0] = holdouts["holdout_a"][0]
                else:
                    rows[0]["slots"]["M04"]["version"] = "post-draw"
                replay(rows, ids, holdouts)

    def test_ties_stay_in_d2_effect_denominator(self):
        rows, ids, holdouts = replay_fixture()
        rows[0]["slots"]["M07"]["D2"] = [1, 2]
        result = replay(rows, ids, holdouts)
        pair = result["summary"]["holdout_a"]["M04"]["D2_vs_M07"]
        self.assertEqual((pair["wins"], pair["losses"], pair["ties"]), (1, 0, 1))
        self.assertEqual(pair["paired_delta"], 0.5)
        self.assertEqual(pair["p_one_sided_exploratory"], 0.5)

    def test_pre_draw_hash_and_independent_holdout_hash_reject_tamper(self):
        for target in ("prediction", "holdout"):
            with self.subTest(target=target), self.assertRaises(AdmissionBlocked):
                rows, ids, holdouts = replay_fixture()
                original_holdout_hash = fingerprint(holdouts)
                commitments = {r["issue"]: prediction_commitment(r) for r in rows}
                if target == "prediction":
                    rows[0]["slots"]["M04"]["D2"] = [20, 21]
                else:
                    holdouts["holdout_a"][0], holdouts["holdout_b"][0] = (
                        holdouts["holdout_b"][0], holdouts["holdout_a"][0])
                replay_dual_holdout("SSQ", rows, expected_issues=ids, versions=VERSIONS,
                                    primary_m05_slot="M05-2", holdouts=holdouts,
                                    expected_holdouts_sha256=original_holdout_hash,
                                    prediction_commitments=commitments)


@unittest.skipUnless(importlib.util.find_spec("cryptography"), "cryptography runtime unavailable")
class TestSyntheticCryptographicAuthorization(unittest.TestCase):
    """Ephemeral synthetic keys only: these are not real 01/04 authority keys."""

    def setUp(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        self.private = {role: Ed25519PrivateKey.generate() for role in ("01", "04")}
        self.trusted = {role: {"SYNTHETIC-" + role: key.public_key().public_bytes(
            Encoding.Raw, PublicFormat.Raw)} for role, key in self.private.items()}

    def authorization(self, role="01", **changes):
        claims = {"schema": "ssq-dlt-auth-v1", "role": role, "key_id": "SYNTHETIC-" + role,
                  "payload_sha256": "a" * 64, "nonce": "SYNTHETIC-NONCE-0001",
                  "issued_at": PUBLISHED, "expires_at": CUTOFF, "cutoff": CUTOFF}
        claims.update(changes)
        return {"claims": claims, "signature": base64.b64encode(
            self.private[role].sign(canonical_bytes(claims))).decode("ascii")}

    def verify(self, envelope, role="01", consumed=None):
        return verify_ed25519_authorization(
            envelope, expected_role=role, payload_sha256="a" * 64, trusted_keys=self.trusted,
            now=AS_OF, cutoff=CUTOFF, consumed_nonces=set() if consumed is None else consumed)

    def test_actual_ed25519_signature_for_both_roles_still_not_formal(self):
        for role in ("01", "04"):
            with self.subTest(role=role):
                result = self.verify(self.authorization(role), role)
                self.assertEqual(result["cryptographic_signature"], "PASS")
                self.assertEqual(result["formal_admission"], "BLOCKED")

    def test_tamper_wrong_key_and_wrong_role_rejected(self):
        forged = self.authorization()
        forged["claims"]["nonce"] += "-tampered"
        with self.assertRaisesRegex(AdmissionBlocked, "INVALID_AUTHORITY_SIGNATURE"):
            self.verify(forged)
        self.trusted["01"]["SYNTHETIC-01"] = self.trusted["04"]["SYNTHETIC-04"]
        with self.assertRaisesRegex(AdmissionBlocked, "INVALID_AUTHORITY_SIGNATURE"):
            self.verify(self.authorization())
        with self.assertRaisesRegex(AdmissionBlocked, "SCOPE_MISMATCH"):
            self.verify(self.authorization("04"))

    def test_expiry_future_replay_and_payload_swap_rejected(self):
        for changes in ({"expires_at": AS_OF}, {"issued_at": CUTOFF},
                        {"payload_sha256": "b" * 64}):
            with self.subTest(changes=changes), self.assertRaises(AdmissionBlocked):
                self.verify(self.authorization(**changes))
        envelope = self.authorization()
        with self.assertRaisesRegex(AdmissionBlocked, "REPLAY"):
            self.verify(envelope, consumed={envelope["claims"]["nonce"]})

    def test_supplied_verified_boolean_is_not_a_signature(self):
        with self.assertRaisesRegex(AdmissionBlocked, "SIGNED_AUTHORIZATION_REQUIRED"):
            self.verify({"verified": True, "role": "01", "signature": "forged"})


class TestNoPromotion(unittest.TestCase):
    def test_malformed_unhashable_game_and_role_fail_closed_with_contract_error(self):
        malformed_game = ["SSQ"]
        malformed_registry = registry()
        malformed_registry["game"] = malformed_game
        calls = [
            lambda: validate_source_pair(malformed_game, "SYNTH-01", sources(),
                                         as_of=AS_OF, cutoff=CUTOFF, now=NOW),
            lambda: validate_registry(malformed_registry, fingerprint(malformed_registry)),
            lambda: validate_candidate_slots(malformed_game, slots(), VERSIONS, "M05-2"),
            lambda: validate_challengers([], None),
            lambda: verify_ed25519_authorization({}, expected_role=["01"],
                                                 payload_sha256="a" * 64, trusted_keys={},
                                                 now=AS_OF, cutoff=CUTOFF, consumed_nonces=set()),
        ]
        for call in calls:
            with self.subTest(call=call), self.assertRaises(AdmissionBlocked):
                call()

    def test_all_synthetic_checks_cannot_promote_r2_formal_a_or_edge(self):
        check_sources()
        replay()
        report = admission_report()
        self.assertEqual((report["R2"], report["formal_A"], report["decision"]),
                         ("BLOCKED", 0, "NO_EDGE"))
        self.assertEqual(report["final_gate"], "FAIL")
        self.assertNotIn("PASS", report["p0"].values())


if __name__ == "__main__":
    unittest.main()
