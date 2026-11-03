"""Nhóm, strengthened và khoá. Không đổi luật khớp."""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO)]

from engine.policy.v24 import HEADLINES, LEVEL1_HEADLINE, evaluate
from engine.tests.test_policy_v24 import _at, _facts, _funds


def test_one_group_is_not_strengthened_and_a_call_rule_requires_hangup():
    out = evaluate(
        _facts(
            call_state="active",
            task_type="new_typed",
            new_payee=True,
            funds_events=_funds(_at(9) - timedelta(hours=2)),
            habit_money_rare=True,
            habit_rare=True,
        )
    )
    assert out.level == 2
    assert "R_CALL_FUNDS_NEWPAYEE" in out.rules_fired
    assert "R_CALL_HABIT_NEWPAYEE" in out.rules_fired
    assert out.groups_fired == ["A"]
    assert out.strengthened is False
    assert out.continue_requires_hangup is True
    assert out.lock_minutes == 0
    assert out.lock_until is None
    assert out.headline == HEADLINES["R_CALL_FUNDS_NEWPAYEE"]


def test_two_groups_lock_for_thirty_minutes_and_the_earlier_rule_is_the_headline():
    when = _at(9)
    out = evaluate(
        _facts(
            ts=when,
            call_state="active",
            task_type="new_typed",
            new_payee=True,
            transfer_purpose="authority_request",
            habit_money_rare=True,
        )
    )
    assert out.groups_fired == ["A", "C"]
    assert out.strengthened is True
    assert out.continue_requires_hangup is True
    assert out.lock_minutes == 30
    assert out.lock_until == when + timedelta(minutes=30)
    assert out.headline == HEADLINES["R_PURPOSE_HIGH_RISK"]


def test_capture_and_guided_are_group_b_only():
    capture = evaluate(_facts(device_state="active_capture", call_state="none"))
    assert capture.level == 2
    assert capture.groups_fired == ["B"]
    assert capture.strengthened is False
    assert capture.continue_requires_hangup is False
    assert capture.lock_minutes == 0
    assert capture.headline == HEADLINES["R_CAPTURE"]
    guided = evaluate(
        _facts(
            call_state="active",
            new_payee=True,
            task_type="new_typed",
            behaviour_p_rarity=0.01,
            same_task_sessions=8,
        )
    )
    assert guided.level == 2
    assert "R_BEHAVIOUR_GUIDED" in guided.rules_fired
    assert guided.groups_fired == ["B"]
    assert guided.strengthened is False
    assert guided.continue_requires_hangup is True
    assert guided.headline == HEADLINES["R_BEHAVIOUR_GUIDED"]


def test_level_1_uses_the_default_headline_and_does_not_lock():
    out = evaluate(_facts(call_state="active", new_payee=True, task_type="new_typed"))
    assert out.level == 1
    assert "R_CALL_NEWPAYEE" in out.rules_fired
    assert out.groups_fired == []
    assert out.strengthened is False
    assert out.continue_requires_hangup is False
    assert out.lock_minutes == 0
    assert out.headline == LEVEL1_HEADLINE


def test_model_high_and_simo_share_the_written_sentences():
    high = evaluate(_facts(p_fraud=0.8125, call_state="none", new_payee=False))
    assert "R_MODEL_HIGH" in high.rules_fired
    assert high.headline == HEADLINES["R_MODEL_HIGH"]
    assert high.groups_fired == ["D"]
    assert high.strengthened is False
