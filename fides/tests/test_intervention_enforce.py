"""Máy chủ từ chối Tiếp tục. Không cần engine."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "bank-core"), str(ROOT)]

from enforce import (
    FRAUD_CONFIRMED,
    GUARDIAN_DECLINED,
    HANGUP_MESSAGE,
    LOCK_MESSAGE,
    UNSCORED_HEADLINE,
    block_proceed,
    flags_from_decision,
    rejection_choice,
    unscored_decision,
)

ICT = ZoneInfo("Asia/Ho_Chi_Minh")
NOW = datetime(2026, 9, 21, 10, 0, tzinfo=ICT)


def _flags(**overrides):
    base = {
        "continue_requires_hangup": False,
        "strengthened": False,
        "lock_until": None,
        "hotline_verified": False,
    }
    base.update(overrides)
    return base


def test_an_active_call_blocks_proceed_and_hangup_clears_it():
    flags = _flags(continue_requires_hangup=True)
    assert block_proceed(flags, NOW, "active", False) == HANGUP_MESSAGE
    assert block_proceed(flags, NOW, None, False) == HANGUP_MESSAGE
    assert block_proceed(flags, NOW, "unknown", False) == HANGUP_MESSAGE
    assert block_proceed(flags, NOW, "ended_in_session", False) is None
    assert block_proceed(flags, NOW, "none", False) is None
    assert rejection_choice(HANGUP_MESSAGE) == "proceed_rejected_call"


def test_strengthened_stays_locked_until_hotline_or_the_clock():
    lock = (NOW + timedelta(minutes=30)).isoformat()
    flags = _flags(strengthened=True, lock_until=lock, continue_requires_hangup=True)
    assert block_proceed(flags, NOW, "ended_in_session", False) == LOCK_MESSAGE
    assert block_proceed(flags, NOW, "active", True) == HANGUP_MESSAGE
    assert block_proceed(flags, NOW, "ended_in_session", True) is None
    later = NOW + timedelta(minutes=30)
    assert block_proceed(flags, later, "none", False) is None
    assert rejection_choice(LOCK_MESSAGE) == "proceed_rejected_lock"


def test_a_single_group_does_not_lock():
    flags = _flags(continue_requires_hangup=False, strengthened=False)
    assert block_proceed(flags, NOW, "active", False) is None


def test_missing_lock_time_is_filled_from_the_decision():
    stored = flags_from_decision(
        {"strengthened": True, "lock_minutes": 30, "continue_requires_hangup": True, "headline": "x", "groups_fired": ["A", "C"]},
        NOW,
    )
    assert stored["lock_until"] == (NOW + timedelta(minutes=30)).isoformat()
    assert stored["hotline_verified"] is False
    assert block_proceed(stored, NOW, "ended_in_session", False) == LOCK_MESSAGE


def test_flags_keep_the_evidence_card_for_a_later_screen():
    card = {"signals": [], "reasons_vi": ["gần hết số dư"], "restated_vi": ["cuộc gọi"], "baseline_quality": "none", "episode_id": "e1"}
    stored = flags_from_decision(
        {
            "headline": "câu lớn",
            "evidence_card": card,
            "signals_present": ["new_payee"],
            "rules_fired": ["R_CALL_FUNDS_NEWPAYEE"],
            "intervention": "three_button",
        },
        NOW,
    )
    assert stored["evidence_card"] == card
    assert stored["headline"] == "câu lớn"
    assert stored["intervention"] == "three_button"
    assert stored["signals_present"] == ["new_payee"]


def test_a_missed_decide_is_unscored_and_never_level_zero():
    known = unscored_decision(True)
    new = unscored_decision(False)
    assert known["level"] is None
    assert known["unscored"] is True
    assert known["funds_status"] == "released"
    assert new["level"] == 1
    assert new["headline"] == UNSCORED_HEADLINE
    assert new["level"] != 0
    assert FRAUD_CONFIRMED.startswith("Tổng đài đã xác nhận")
    assert "người thân" in GUARDIAN_DECLINED
