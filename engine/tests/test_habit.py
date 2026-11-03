"""Thói quen v2.5. Không flush Redis, không đọc truth."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO)]

from engine.features.habit import (
    FEATURES,
    GROUPS,
    MODEL_VERSION,
    WEEK_FEATURE,
    HabitModel,
    Population,
    Transfer,
    assess,
    hour_weekday,
)
from engine.policy.v24 import Facts, evaluate, load_policy

ICT = ZoneInfo("Asia/Ho_Chi_Minh")
NOW = datetime(2026, 9, 21, 10, tzinfo=ICT)


def _us(stamp: datetime) -> int:
    return int(stamp.timestamp() * 1_000_000)


def _pop(**overrides) -> Population:
    base = Population(
        median_amount=200_000,
        max_amount_ref=500_000,
        typical_7d=100_000,
        balance_median=0.1,
        balance_mad=0.05,
        typical_daily=1.0,
        typical_unseen_daily=0.2,
        feature_median={name: 0.0 for name in FEATURES},
        feature_mad={name: 1.0 for name in FEATURES},
        if_threshold=1.0,
        z_threshold=1.0e12,
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def _row(days: int, hour: int, amount: int = 200_000, balance: int = 5_000_000, payee: str = "known") -> Transfer:
    stamp = (NOW - timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0)
    return Transfer(_us(stamp), payee, amount, balance)


def test_feature_names_do_not_include_new_payee():
    assert "new_payee" not in FEATURES
    assert all("new_payee" not in name for name in FEATURES)
    assert WEEK_FEATURE in FEATURES
    assert GROUPS[WEEK_FEATURE] == "amount"


def test_short_history_uses_the_robust_profile_and_quality_low():
    history = [_row(10, 10), _row(20, 10), _row(30, 11)]
    result = assess(history, _us(NOW), "someone", 200_000, 5_000_000, _pop(), model=None)
    assert result.quality == "low"
    assert result.method == "robust_z"
    assert result.n < 5
    assert result.rare is False


def test_window_extends_to_twelve_months_when_ninety_days_are_thin():
    recent = [_row(day, 10) for day in (5, 15, 25)]
    older = [_row(day, 10) for day in range(120, 120 + 9 * 7, 7)]
    extended = assess(recent + older, _us(NOW), "someone", 200_000, 5_000_000, _pop(), model=None)
    assert extended.n90 < 10
    assert extended.window == "12m"
    assert extended.n == len(recent) + len(older)
    crowded = [_row(day, 10) for day in range(1, 11)]
    kept = assess(crowded + older, _us(NOW), "someone", 200_000, 5_000_000, _pop(), model=None)
    assert kept.window == "90d"
    assert kept.n == len(crowded)


def test_extreme_override_marks_money_even_when_the_profile_is_quiet():
    history = [_row(day, 10, amount=100_000) for day in (4, 8, 12, 16)]
    result = assess(history, _us(NOW), "new-person", 10_000_000, 40_000_000, _pop(), model=None)
    assert result.quality == "low"
    assert result.extreme is True
    assert result.rare is False
    assert result.money_rare is True
    assert result.top_group == "amount"


def test_timing_only_habit_rare_does_not_set_habit_money_rare():
    history = [_row(day, 10, payee=f"p{day % 3}") for day in range(1, 26)]

    class Stub:
        def __init__(self):
            self.model = self

        def decision_function(self, _row):
            return np.asarray([-10.0])

        def anomaly(self, _features):
            return 10.0, np.zeros(len(FEATURES))

        def top_feature(self, _features, _contrib):
            return "hour_rarity"

    result = assess(history, _us(NOW.replace(hour=3)), "fresh", 200_000, 5_000_000, _pop(), model=Stub())
    assert result.quality in {"medium", "high"}
    assert result.method == "isolation_forest"
    assert result.rare is True
    assert result.top_group == "timing"
    assert result.money_rare is False
    assert result.extreme is False


def test_timing_habit_with_a_call_stays_at_level_1():
    out = evaluate(
        Facts(
            sender="a" * 64,
            payee="b" * 64,
            amount=200_000,
            ts=NOW.replace(hour=3),
            call_state="active",
            task_type="new_typed",
            transfer_purpose="family_friends",
            device_state="none",
            funds_events=[],
            new_payee=True,
            payee_age_days=800.0,
            distinct_senders_7d=1.0,
            passthrough_24h=0.1,
            simo_listed=False,
            prior_payments=0,
            first_days_before_listing=0.0,
            p_fraud=0.0,
            habit_rare=True,
            habit_money_rare=False,
            habit_top_group="timing",
            habit_top_feature="hour_rarity",
            habit_quality="high",
        )
    )
    assert out.level == 1
    assert "R_HABIT_NEWPAYEE" in out.rules_fired
    assert "R_CALL_NEWPAYEE" in out.rules_fired
    assert "R_CALL_HABIT_NEWPAYEE" not in out.rules_fired
    assert "Bạn hiếm khi chuyển tiền vào giờ này." in out.reasons_vi


def test_hour_bucket_uses_vietnam_time():
    stamp = datetime(2026, 9, 21, 15, 30, tzinfo=ICT)
    assert stamp.weekday() == 0
    assert hour_weekday(_us(stamp)) == (15, 0)


def test_model_artifact_loads_and_matches_the_policy_threshold():
    loaded = HabitModel.load()
    assert loaded.version == MODEL_VERSION
    policy = load_policy()
    assert policy["thresholds"]["habit_score_above"]["value"] == loaded.population.if_threshold
    assert policy["thresholds"]["habit_profile_above"]["value"] == loaded.population.z_threshold
    assert "98th percentile" in policy["thresholds"]["habit_score_above"]["provenance"]
