"""Thói quen v2.5. Không flush Redis, không đọc truth."""

from __future__ import annotations

import json
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
    Ledger,
    Population,
    Transfer,
    _blocked,
    _named,
    vector_of,
    assess,
    dispute_from_event,
    dispute_hold,
    hour_weekday,
    mark_hold,
    verify_legitimate,
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

        def explain(self, _features):
            return np.zeros(len(FEATURES))

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


class _Hash:
    def __init__(self):
        self.hashes: dict[str, dict[str, str]] = {}
        self.values: dict[str, str] = {}

    def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    def hset(self, key, field, value):
        self.hashes.setdefault(key, {})[field] = value

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = value


def test_unconfirmed_alert_stays_out_of_the_baseline_but_inside_the_week_sum():
    clean = Transfer(_us(NOW - timedelta(days=10)), "old", 2_000_000, 80_000_000, True)
    flagged = Transfer(_us(NOW - timedelta(days=1)), "scam-1", 20_000_000, 80_000_000, False)
    ledger = Ledger()
    ledger.add(clean)
    ledger.add(flagged)
    raw = ledger.snapshot(_us(NOW), "scam-2", 20_000_000, 80_000_000)
    assert raw.n == 2
    assert raw.n_base == 1
    assert raw.personal_max == 2_000_000
    assert raw.personal_median == 2_000_000
    assert raw.max_12m == 2_000_000
    assert raw.week_sum == 40_000_000
    assert raw.week_median == 2_000_000
    assert raw.ratios == [2_000_000 / 80_000_000]
    confirmed = Transfer(_us(NOW - timedelta(days=1)), "scam-1", 20_000_000, 80_000_000, True)
    again = Ledger()
    again.add(clean)
    again.add(confirmed)
    back = again.snapshot(_us(NOW), "scam-2", 20_000_000, 80_000_000)
    assert back.personal_max == 20_000_000
    assert back.n_base == 2


def _hold(client: _Hash, sender: str = "sender") -> dict[str, str]:
    return client.hashes.get(f"f:habithold:{sender}", {})


def test_customer_actions_leave_the_twenty_million_out_of_the_baseline():
    client = _Hash()
    stamp = _us(NOW - timedelta(days=1))
    mark_hold(client, "sender", stamp, "scam-1", 20_000_000, "dec-1")
    for _action in ("continue", "proceed", "guardian_confirm"):
        assert client.hget("f:habithold:sender", f"{stamp}|scam-1|20000000") == "0"
    assert f"{stamp}|scam-1|20000000" in _blocked(_hold(client), _us(NOW))
    ledger = Ledger()
    ledger.add(Transfer(_us(NOW - timedelta(days=10)), "old", 2_000_000, 80_000_000, True))
    ledger.add(Transfer(stamp, "scam-1", 20_000_000, 80_000_000, False))
    raw = ledger.snapshot(_us(NOW), "scam-2", 20_000_000, 80_000_000)
    assert raw.personal_max == 2_000_000
    assert raw.personal_median == 2_000_000
    assert raw.week_median == 2_000_000
    assert raw.ratios == [2_000_000 / 80_000_000]
    assert raw.week_sum == 40_000_000


def test_a_quiet_hold_returns_after_thirty_days_and_a_dispute_does_not():
    client = _Hash()
    quiet = _us(NOW - timedelta(days=30))
    recent = _us(NOW - timedelta(days=29))
    reported = _us(NOW - timedelta(days=40))
    mark_hold(client, "sender", quiet, "payee", 20_000_000, "dec-quiet")
    mark_hold(client, "sender", recent, "payee", 20_000_000, "dec-recent")
    mark_hold(client, "sender", reported, "payee", 20_000_000, "dec-reported")
    dispute_hold(client, "dec-reported")
    dispute_from_event(client, {"type": "complaint", "decision_id": "dec-recent"})
    dispute_from_event(client, {"type": "txn", "fraud_report": True})
    blocked = _blocked(_hold(client), _us(NOW))
    assert f"{quiet}|payee|20000000" not in blocked
    assert f"{recent}|payee|20000000" in blocked
    assert f"{reported}|payee|20000000" in blocked
    assert client.hget("f:habithold:sender", f"{recent}|payee|20000000") == "d"


def test_bank_verification_waits_until_the_episode_closes():
    client = _Hash()
    stamp = _us(NOW - timedelta(days=1))
    mark_hold(client, "sender", stamp, "payee", 20_000_000, "dec-bank")
    assert verify_legitimate(client, "dec-bank", _us(NOW)) is True
    assert client.hget("f:habithold:sender", f"{stamp}|payee|20000000") == "1"
    mark_hold(client, "sender", stamp, "payee", 20_000_000, "dec-bank")
    assert client.hget("f:habithold:sender", f"{stamp}|payee|20000000") == "1"
    mark_hold(client, "sender", stamp, "other", 20_000_000, "dec-open")
    client.set(
        "pol:v24:sender",
        json.dumps({"episode_id": "ep-1", "expires_at": (NOW + timedelta(hours=2)).isoformat()}),
    )
    assert verify_legitimate(client, "dec-open", _us(NOW)) is False
    assert client.hget("f:habithold:sender", f"{stamp}|other|20000000") == "0"
    client.set(
        "pol:v24:sender",
        json.dumps({"episode_id": "ep-1", "expires_at": (NOW - timedelta(hours=1)).isoformat()}),
    )
    dispute_hold(client, "dec-open")
    assert verify_legitimate(client, "dec-open", _us(NOW)) is True
    assert client.hget("f:habithold:sender", f"{stamp}|other|20000000") == "1"


def test_hour_bucket_uses_vietnam_time():
    stamp = datetime(2026, 9, 21, 15, 30, tzinfo=ICT)
    assert stamp.weekday() == 0
    assert hour_weekday(_us(stamp)) == (15, 0)


def test_single_row_score_matches_the_forest():
    loaded = HabitModel.load()
    features = {name: 0.2 * (index + 1) for index, name in enumerate(FEATURES)}
    frame = _named(vector_of(features).reshape(1, -1))
    official = float(-loaded.model.decision_function(frame)[0])
    assert loaded.score_one(features) == official


def test_model_artifact_loads_and_matches_the_policy_threshold():
    loaded = HabitModel.load()
    assert loaded.version == MODEL_VERSION
    policy = load_policy()
    assert policy["thresholds"]["habit_score_above"]["value"] == loaded.population.if_threshold
    assert policy["thresholds"]["habit_profile_above"]["value"] == loaded.population.z_threshold
    assert "98th percentile" in policy["thresholds"]["habit_score_above"]["provenance"]
