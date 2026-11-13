"""Immutable inventory of every active mother V1 SSQ/DLT research arm.

The V4.7 formal research models are frozen code dependencies, not promoted
predictors. Legacy supercompute remains a separate provenance family.
An unavailable physical model MUST be explicitly reported as ABSTAIN.
"""
from __future__ import annotations

REGISTERED_V47 = (
    "hot60", "ewma", "shrinkmix", "pairwise_d2", "challenger", "random_null",
)
EXPLORATORY_V47 = (
    "hot30", "hot120", "pair_margin", "pair_residual", "recency_pair_h45_120",
)
LEGACY_SUPERCOMPUTE = (
    "supercompute_hot60", "supercompute_ewma30", "supercompute_random_null",
)
PHYSICAL = (
    "physical_exit_order", "physical_ball_group",
)
ALL_MODELS = REGISTERED_V47 + EXPLORATORY_V47 + LEGACY_SUPERCOMPUTE + PHYSICAL
assert len(ALL_MODELS) == len(set(ALL_MODELS)) == 16

MODEL_FAMILIES = {
    **{name: "FROZEN_V47_RESEARCH" for name in REGISTERED_V47},
    **{name: "EXPLORATORY_V47_ABLATION" for name in EXPLORATORY_V47},
    **{name: "LEGACY_SUPERCOMPUTE_ISOLATED" for name in LEGACY_SUPERCOMPUTE},
    **{name: "PHYSICAL_EXPLORATORY" for name in PHYSICAL},
}
HISTORY_POLICIES = {
    "v47": "only preceding draw rows, no retrospective target labels",
    "physical": "original-byte-verified, pre-target physical observations only",
}
SCHEMA = "SSQDLT_UNIFIED_MOTHER_V1_SHADOW"
NO_EDGE = "NO_EDGE"
FORMAL_A = 0
