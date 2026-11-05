"""Nhóm, strengthened và khoá. Không đổi luật khớp."""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO)]

from engine.policy.v24 import CALL_NEWPAYEE_TEXT, HEADLINES, LEVEL1_HEADLINE, LEVEL1_HEADLINES, PURPOSE_HEADLINES, evaluate
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


def test_purpose_outranks_the_money_pattern_for_the_headline():
    out = evaluate(
        _facts(
            call_state="active",
            task_type="new_typed",
            new_payee=True,
            funds_events=_funds(_at(9) - timedelta(hours=2)),
            habit_money_rare=True,
            habit_rare=True,
            transfer_purpose="authority_request",
        )
    )
    assert out.rules_fired.index("R_CALL_FUNDS_NEWPAYEE") < out.rules_fired.index("R_PURPOSE_HIGH_RISK")
    assert out.groups_fired == ["A", "C"]
    assert out.strengthened is True
    assert out.headline == PURPOSE_HEADLINES["authority_request"]
    assert out.reason_codes[:2] == ["purpose_high_risk", "call_active"]


def test_guidance_outranks_the_money_pattern_for_the_headline():
    out = evaluate(
        _facts(
            call_state="active",
            new_payee=True,
            task_type="new_typed",
            funds_events=_funds(_at(9) - timedelta(hours=2)),
            behaviour_p_rarity=0.5,
            behaviour_guided_p=0.01,
            same_task_sessions=8,
            behaviour_guided_group="dictation",
        )
    )
    assert "R_CALL_FUNDS_NEWPAYEE" in out.rules_fired
    assert "R_BEHAVIOUR_GUIDED" in out.rules_fired
    assert out.headline == HEADLINES["R_BEHAVIOUR_GUIDED"]
    assert out.reason_codes[:3] == ["behaviour_guided", "call_active", "funds_mobilised"]


def test_money_pattern_reasons_put_call_and_funds_before_habit_and_payee():
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
    assert out.reason_codes[:2] == ["call_active", "funds_mobilised"]
    assert out.reason_codes[2] == "new_payee"


def test_restated_lines_are_the_signals_the_headline_rule_names():
    money = evaluate(
        _facts(
            call_state="active",
            task_type="new_typed",
            new_payee=True,
            funds_events=_funds(_at(9) - timedelta(hours=2)),
            habit_money_rare=True,
            habit_rare=True,
        )
    )
    assert money.headline == HEADLINES["R_CALL_FUNDS_NEWPAYEE"]
    assert money.restated_vi == [
        text for code, text in zip(money.reason_codes, money.reasons_vi) if code in {"call_active", "funds_mobilised", "new_payee"}
    ]
    assert money.evidence_card["restated_vi"] == money.restated_vi
    purpose = evaluate(
        _facts(
            call_state="active",
            task_type="new_typed",
            new_payee=True,
            funds_events=_funds(_at(9) - timedelta(hours=2)),
            habit_money_rare=True,
            transfer_purpose="authority_request",
        )
    )
    assert purpose.restated_vi == ["Mục đích chuyển là yêu cầu của cơ quan hoặc phí để nhận tiền."]
    call = evaluate(_facts(call_state="active", new_payee=True, task_type="new_typed"))
    assert call.level == 1
    assert call.restated_vi == [CALL_NEWPAYEE_TEXT]


def test_the_guided_headline_restates_no_reason_line():
    guided = evaluate(
        _facts(
            call_state="active",
            new_payee=True,
            task_type="new_typed",
            behaviour_p_rarity=0.5,
            behaviour_guided_p=0.01,
            same_task_sessions=8,
            behaviour_guided_group="dictation",
        )
    )
    assert guided.headline == HEADLINES["R_BEHAVIOUR_GUIDED"]
    assert guided.restated_vi == []
    assert guided.reason_codes[:2] == ["behaviour_guided", "call_active"]


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
    assert out.headline == PURPOSE_HEADLINES["authority_request"]


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
            behaviour_p_rarity=0.5,
            behaviour_guided_p=0.01,
            same_task_sessions=8,
            behaviour_guided_group="dictation",
        )
    )
    assert guided.level == 2
    assert "R_BEHAVIOUR_GUIDED" in guided.rules_fired
    assert guided.groups_fired == ["B"]
    assert guided.strengthened is False
    assert guided.continue_requires_hangup is True
    assert guided.headline == HEADLINES["R_BEHAVIOUR_GUIDED"]


def test_level_1_call_and_habit_use_their_own_headlines():
    call = evaluate(_facts(call_state="active", new_payee=True, task_type="new_typed"))
    assert call.level == 1
    assert "R_CALL_NEWPAYEE" in call.rules_fired
    assert call.groups_fired == []
    assert call.strengthened is False
    assert call.continue_requires_hangup is False
    assert call.lock_minutes == 0
    assert call.headline == LEVEL1_HEADLINES["R_CALL_NEWPAYEE"]
    habit = evaluate(_facts(call_state="none", new_payee=True, task_type="new_typed", habit_rare=True))
    assert habit.level == 1
    assert "R_HABIT_NEWPAYEE" in habit.rules_fired
    assert "R_CALL_NEWPAYEE" not in habit.rules_fired
    assert habit.headline == LEVEL1_HEADLINES["R_HABIT_NEWPAYEE"]
    other = evaluate(_facts(call_state="none", new_payee=False, p_fraud=0.42))
    if other.level == 1:
        assert other.headline == LEVEL1_HEADLINE


def test_model_high_and_simo_share_the_written_sentences():
    high = evaluate(_facts(p_fraud=0.8125, call_state="none", new_payee=False))
    assert "R_MODEL_HIGH" in high.rules_fired
    assert high.headline == HEADLINES["R_MODEL_HIGH"]
    assert high.groups_fired == ["D"]
    assert high.strengthened is False
