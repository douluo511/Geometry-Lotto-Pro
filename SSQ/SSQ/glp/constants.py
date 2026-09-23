from __future__ import annotations

APP_NAME = "Geometry Lotto Pro"
APP_VERSION = "8.4.2-verification"
GAME = "SSQ"
FRONT_MAX = 33
FRONT_PICK = 6
BACK_MAX = 16
BACK_PICK = 1

NATIONAL_URL = "https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice"
SHANGHAI_URL = "https://www.swlc.net.cn/lottery/ssq.html?limit=100&view=previous"
HEBEI_URL = "https://www.yzfcw.com/"
HEBEI_ANNOUNCE_URL = "https://www.yzfcw.com/game/ssqAnnounce"
SOURCE_NAMES = ("national", "shanghai", "hebei")
FOUR_ENTRIES = ("预测下一期", "一键更新", "一键修复", "高级分析")
DAN_STATES = ("NULL_DAN", "RESEARCH_DAN", "WATCHLIST_DAN", "CERTIFIED_DAN")

# Frozen, pre-registered validation contract.  These values are not tuned from
# the current holdout result.
PROMOTION_POLICY = {
    "schema": "false-edge-firewall-v8",
    "min_walk_forward": 1200,
    "min_prospective": 120,
    "min_era_count": 3,
    "alpha": 0.01,
    "min_front_recall_gain": 0.04,
    "min_back_recall_gain": 0.03,
    "min_bootstrap_lower": 0.0,
    "min_null_percentile": 0.95,
    "max_null_world_fpr": 0.05,
    "min_wilson_lower": 0.50,
    "min_model_coverage": 0.60,
    "min_rank_support": 0.60,
    "min_confirmation_n": 120,
    "windows": (30, 60, 120, 240),
    "seeds": (17, 43, 97, 193, 389),
    "ablation_modes": ("remove", "shuffle", "random_replace"),
    "bootstrap_rounds": 1999,
    "permutation_rounds": 2000,
    "null_worlds": 300,
}

MODEL_VERSION = "ssq-native-research-v8.1"
SELECTOR_VERSION = "ssq-false-edge-firewall-v8.1"
