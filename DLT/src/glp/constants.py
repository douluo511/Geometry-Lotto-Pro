from __future__ import annotations

APP_NAME = "Geometry Lotto Pro"
APP_VERSION = "2.1.2"
GAME = "DLT"
FRONT_MAX = 35
FRONT_PICK = 5
BACK_MAX = 12
BACK_PICK = 2

NATIONAL_URL = "https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry"
JIANGSU_URL = "https://api.js-lottery.com/wfzq/dlt/data"
SOURCE_NAMES = {
    "national": "中国体育彩票官方开奖接口",
    "jiangsu": "江苏省体育彩票管理中心",
}
FOUR_ENTRIES = ("预测下一期", "一键更新", "一键修复", "高级分析")
DAN_STATES = ("NULL_DAN", "RESEARCH_DAN", "WATCHLIST_DAN", "CERTIFIED_DAN")

# Frozen/preregistered protocol. Changing any value changes selector/model hashes and
# therefore requires a new EXE build and a full acceptance run.
PROMOTION_POLICY = {
    "protocol_version": "false-edge-firewall-v2.1.2",
    "min_history": 600,
    "windows": (120, 240, 360),
    "seeds": (17, 29, 43, 71, 97),
    "walk_forward_points": 720,
    "untouched_holdout": 120,
    "min_era_count": 3,
    "alpha": 0.05,
    "min_front_recall_gain": 0.0,
    "min_back_recall_gain": 0.0,
    "min_bootstrap_lower": 0.0,
    "max_null_world_fpr": 0.10,
    "null_worlds": 100,
    "synthetic_null_worlds": 6,
    "synthetic_null_draws": 300,
    "synthetic_null_test_points": 60,
    "synthetic_null_max_false_edges": 0,
    "ablation_points": 240,
    "bootstrap_rounds": 800,
    "permutation_rounds": 1200,
    "loeo_bootstrap_rounds": 300,
    "loeo_permutation_rounds": 500,
    "dan_wilson_z": 1.959963984540054,
    "dan_min_coverage": 0.60,
    "dan_min_rank_support": 0.60,
    "dan_min_lift": 0.01,
    "dan_seed_jitter": 0.05,
    "min_validated_components": 1,
    "min_prospective_replays": 30,
}

MODEL_VERSION = "dlt-research-v2.1-geometry"
SELECTOR_VERSION = "dan-firewall-v2.1.2-scientific-gate"
