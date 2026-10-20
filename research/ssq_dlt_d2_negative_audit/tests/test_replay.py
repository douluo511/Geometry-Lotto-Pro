"""Small deterministic replay tests; the full 2,880 records run separately."""
import copy
from datetime import date, timedelta
import random
import unittest
from unittest.mock import patch

from research.ssq_dlt_d2_negative_audit import replay
from research.ssq_dlt_d2_next import simulation as prior


def fake_complete_document():
    """Structurally complete, explicitly artificial, not an efficacy dataset."""
    predictions = {model: [1, 2] for model in replay.ALL_IDS}
    return dict(spec=copy.deepcopy(prior.SPEC), periods=[
        dict(game=replay.GAME, scenario=replay.SCENARIO, replication=rep,
             index=index, training_end=index - 1,
             predictions=copy.deepcopy(predictions),
             hits={model: 1 for model in replay.ALL_IDS},
             draw_front=[1, 2, 3, 4, 5], cbpair_brier=0.02,
             formal_A=0, decision="NO_EDGE")
        for rep in range(12) for index in range(240, 480)])


class StreamTraceTests(unittest.TestCase):
    def test_three_original_streams_are_exact_row_for_row(self):
        for replication in (0, 1, 11):
            with self.subTest(replication=replication):
                rows, traces = replay.trace_stream(replication)
                old, _ = prior.synthetic_history("DLT", "SCRAMBLED_PAIR_STRONG", replication)
                self.assertEqual(rows, old)
                self.assertEqual(len(rows), 480)
                self.assertEqual(len(traces), 480)
                self.assertTrue(all(t["output"] == row["front"] for t, row in zip(traces, rows)))

    def test_rng_observation_consumes_no_randomness_including_unused_ring(self):
        rows, traces = replay.trace_stream(0)
        rng = random.Random(prior.stream_seed("DLT", "SCRAMBLED_PAIR_STRONG", 0))
        initial_sha = replay._state_sha(rng)
        ring = rng.sample(range(1, 36), 35)
        self.assertEqual(traces[0]["initialization"]["unused_ring"], ring)
        self.assertEqual(traces[0]["initialization"]["rng_state_before_sha256"], initial_sha)
        self.assertEqual(traces[0]["initialization"]["rng_state_after_sha256"], replay._state_sha(rng))
        for index, trace in enumerate(traces):
            self.assertEqual(trace["rng_state_before_sha256"], replay._state_sha(rng))
            latent = prior.tilted_uniform(rng, 35, 5, [1, 2], 8.0)
            self.assertEqual(trace["latent_front"], latent)
            self.assertEqual(trace["rng_state_after_tilt_sha256"], replay._state_sha(rng))
            permutation = rng.sample(range(1, 36), 35)
            self.assertEqual(trace["permutation"], permutation)
            self.assertEqual(rows[index]["front"], sorted(permutation[x - 1] for x in latent))
            self.assertEqual(trace["rng_state_after_sha256"], replay._state_sha(rng))

    def test_branch_and_rejections_match_latent_membership(self):
        _, traces = replay.trace_stream(0)
        self.assertEqual({t["tilt_branch"] for t in traces}, {"PAIR_HIT", "PAIR_MISS"})
        for trace in traces:
            if trace["tilt_branch"] == "PAIR_HIT":
                self.assertTrue({1, 2} <= set(trace["latent_front"]))
                self.assertEqual(trace["rejection_attempts"], 0)
                self.assertEqual(trace["rejected_draws"], [])
            else:
                self.assertFalse({1, 2} <= set(trace["latent_front"]))
                self.assertEqual(trace["rejection_attempts"], len(trace["rejected_draws"]) + 1)
                self.assertTrue(all({1, 2} <= set(front) for front in trace["rejected_draws"]))

    def test_stream_is_repeatable(self):
        self.assertEqual(replay.trace_stream(1), replay.trace_stream(1))

    def test_only_original_registered_replications(self):
        for value in (-1, 12, True, 1.0, "1", None):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "UNREGISTERED_REPLICATION"):
                replay.trace_stream(value)


class RecordAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.document = fake_complete_document()

    def reject(self, reason):
        # All malformed-document tests fail before old prediction execution.
        with patch.object(replay.candidates, "predict_candidates", side_effect=AssertionError("NO_MODEL_CALL_EXPECTED")):
            with self.assertRaisesRegex(ValueError, reason):
                replay.replay_target(self.document)

    def test_missing_period(self):
        self.document["periods"].pop()
        self.reject("MISSING_TARGET_RECORDS")

    def test_duplicate_period(self):
        self.document["periods"].append(copy.deepcopy(self.document["periods"][0]))
        self.reject("DUPLICATE_TARGET_RECORD")

    def test_out_of_range_extra_period(self):
        extra = copy.deepcopy(self.document["periods"][0])
        extra["index"] = 480
        self.document["periods"].append(extra)
        self.reject("TARGET_RECORD_OUT_OF_RANGE")

    def test_bool_replication_is_not_integer(self):
        self.document["periods"][0]["replication"] = False
        self.reject("TARGET_RECORD_OUT_OF_RANGE")

    def test_future_training_end(self):
        self.document["periods"][0]["training_end"] = 240
        self.reject("TRAINING_PREFIX_BOUNDARY_MISMATCH")

    def test_incomplete_training_end_is_also_not_original(self):
        self.document["periods"][0]["training_end"] = 238
        self.reject("TRAINING_PREFIX_BOUNDARY_MISMATCH")

    def test_wrong_score(self):
        self.document["periods"][0]["hits"][replay.TARGET_MODEL] = 0
        self.reject("STORED_HIT_SCORING_MISMATCH")

    def test_bool_score(self):
        self.document["periods"][0]["hits"][replay.TARGET_MODEL] = True
        self.reject("INVALID_STORED_HIT")

    def test_repeated_pair(self):
        self.document["periods"][0]["predictions"][replay.TARGET_MODEL] = [1, 1]
        self.reject("INVALID_STORED_D2")

    def test_unsorted_pair(self):
        self.document["periods"][0]["predictions"][replay.TARGET_MODEL] = [2, 1]
        self.reject("INVALID_STORED_D2")

    def test_extra_model(self):
        self.document["periods"][0]["predictions"]["POSTHOC"] = [1, 2]
        self.reject("EXACT_REGISTERED_MODELS_REQUIRED")

    def test_invalid_front(self):
        self.document["periods"][0]["draw_front"] = [1, 2, 3, 4, 36]
        self.reject("INVALID_STORED_FRONT")

    def test_changed_registered_seed(self):
        self.document["spec"]["seed"] += 1
        self.reject("REGISTERED_SPEC_MISMATCH")

    def test_nan_brier(self):
        self.document["periods"][0]["cbpair_brier"] = float("nan")
        self.reject("INVALID_STORED_BRIER")

    def test_formal_upgrade_rejected(self):
        self.document["periods"][0]["formal_A"] = 1
        self.reject("RESEARCH_BOUNDARY_MISMATCH")

    def test_legal_front_tamper_is_rejected_against_original_generator(self):
        # [1,2,3,4,5] is legal and internally scores consistently, yet does
        # not equal stream 0's actual front at index 240.
        self.reject("STORED_FRONT_GENERATOR_MISMATCH")

    def test_legal_pair_tamper_with_recomputed_hit_is_rejected(self):
        rows, _ = replay.trace_stream(0)
        first = self.document["periods"][0]
        first["draw_front"] = rows[240]["front"]
        first["hits"] = {m: int({1, 2} <= set(first["draw_front"])) for m in replay.ALL_IDS}
        with self.assertRaisesRegex(ValueError, "STORED_D2_REPLAY_MISMATCH"):
            replay.replay_target(self.document)


class PrefixBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, _ = replay.trace_stream(0)

    def test_target_future_mutation_does_not_change_prefix_prediction(self):
        expected, _ = replay._predictions(self.rows[:240], 0, 240)
        result = replay._prefix_check(self.rows, 0, 240, expected)
        self.assertTrue(result["target_and_future_mutation_unchanged"])
        self.assertTrue(result["target_inclusion_rejected"])

    def test_future_row_inclusion_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "PREFIX_LENGTH_OR_TARGET_INCLUSION"):
            replay._predictions(self.rows[:241], 0, 240)

    def test_future_identity_inside_same_size_prefix_is_rejected(self):
        prefix = list(self.rows[:240])
        prefix[-1] = self.rows[240]
        with self.assertRaisesRegex(ValueError, "PREFIX_INDEX_IDENTITY_MISMATCH"):
            replay._predictions(prefix, 0, 240)

    def test_wrong_date_identity_is_rejected(self):
        prefix = copy.deepcopy(self.rows[:240])
        prefix[0]["draw_date"] = (date(2000, 1, 1) + timedelta(days=1)).isoformat()
        with self.assertRaisesRegex(ValueError, "PREFIX_INDEX_IDENTITY_MISMATCH"):
            replay._guard_prefix(prefix, 240)


if __name__ == "__main__":
    unittest.main()
