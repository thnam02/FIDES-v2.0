"""Tiền vào bất thường, luật đi qua 70%, và mục đích đầu tư."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO)]

from engine.policy.inflows import classify_inflows, is_recurring
from engine.policy.v24 import HEADLINES, MemoryState, evaluate, load_policy
from engine.tests.test_policy_v24 import _facts

ICT = ZoneInfo("Asia/Ho_Chi_Minh")
WHEN = datetime(2026, 9, 21, 10, tzinfo=ICT)


def _row(**overrides):
    base = {
        "ts": WHEN - timedelta(hours=3),
        "amount": 25_000_000,
        "direction": "in",
        "tx_type": "transfer",
        "counterparty_id": "S1",
        "counterparty_name": "NGUYEN VAN A",
        "counterparty_customer": "OTHER",
        "customer_id": "HUYNH",
        "channel": "app",
    }
    base.update(overrides)
    return base


def _inflow(kind: str, amount: int, when: datetime = WHEN) -> list[dict]:
    return [{"type": kind, "at": (when - timedelta(hours=2)).isoformat(), "channel": "app", "amount": amount}]


def test_each_inflow_kind_and_a_monthly_pension_is_left_out():
    policy = load_policy()
    people = [
        _row(counterparty_id=f"S{index}", counterparty_name=f"NGUOI {index}", amount=25_000_000)
        for index in range(4)
    ]
    p2p = classify_inflows(people, WHEN, policy)
    assert [item["type"] for item in p2p] == ["p2p_inflow"]
    assert p2p[0]["amount"] == 100_000_000
    assert p2p[0]["channel"] == "app"

    lone = classify_inflows([_row(counterparty_id="NEW", amount=15_000_000)], WHEN, policy)
    assert lone[0]["type"] == "p2p_inflow"
    assert lone[0]["amount"] == 15_000_000

    lender = classify_inflows(
        [_row(counterparty_name="CONG TY TAI CHINH ABC", amount=40_000_000, tx_type="transfer")],
        WHEN,
        policy,
    )
    assert [item["type"] for item in lender] == ["lender_inflow"]

    cash = classify_inflows([_row(tx_type="cash_deposit", amount=20_000_000, channel="branch")], WHEN, policy)
    assert cash[0]["type"] == "cash_deposit" and cash[0]["channel"] == "branch"
    small = classify_inflows([_row(tx_type="cash_deposit", amount=5_000_000)], WHEN, policy)
    assert small == []

    own = classify_inflows([_row(tx_type="own_transfer", amount=12_000_000, counterparty_customer="ELSE")], WHEN, policy)
    assert [item["type"] for item in own] == ["own_transfer_in"]
    internal = classify_inflows(
        [_row(tx_type="own_transfer", amount=12_000_000, counterparty_customer="HUYNH")],
        WHEN,
        policy,
    )
    assert internal == []

    pension = []
    for months in (3, 2, 1, 0):
        pension.append(
            _row(
                ts=WHEN - timedelta(days=30 * months),
                amount=8_000_000,
                counterparty_id="BHXH",
                counterparty_name="BAO HIEM XA HOI",
            )
        )
    assert classify_inflows(pension, WHEN, policy) == []
    assert is_recurring(pension[-1], pension[:-1], policy) is True


def test_passthrough_needs_seventy_percent_and_a_new_personal_account():
    when = WHEN
    fired = evaluate(
        _facts(
            ts=when,
            amount=70_000_000,
            call_state="none",
            new_payee=True,
            task_type="new_typed",
            funds_events=_inflow("p2p_inflow", 100_000_000, when),
            habit_money_rare=True,
            payee_account_type="personal",
            payee_holder_name="NGUYEN VAN A",
            p_fraud=0.0,
        )
    )
    assert fired.level == 2
    assert "R_FUNDS_PASSTHROUGH" in fired.rules_fired
    assert fired.continue_requires_hangup is False
    assert fired.headline == HEADLINES["R_FUNDS_PASSTHROUGH"]
    card = fired.evidence_card["funds"][0]
    assert card == {"kind": "p2p_inflow", "amount": 100_000_000, "channel": "app", "at": card["at"]}

    short = evaluate(
        _facts(
            ts=when,
            amount=69_000_000,
            sender="a" * 64,
            call_state="none",
            new_payee=True,
            task_type="new_typed",
            funds_events=_inflow("p2p_inflow", 100_000_000, when),
            habit_money_rare=True,
            payee_account_type="personal",
            p_fraud=0.0,
        )
    )
    assert "R_FUNDS_PASSTHROUGH" not in short.rules_fired

    company = evaluate(
        _facts(
            ts=when,
            amount=100_000_000,
            sender="b" * 64,
            call_state="none",
            new_payee=True,
            task_type="new_typed",
            funds_events=_inflow("p2p_inflow", 100_000_000, when),
            habit_money_rare=True,
            payee_holder_name="CONG TY TNHH BENH VIEN",
            p_fraud=0.0,
        )
    )
    assert "R_FUNDS_PASSTHROUGH" not in company.rules_fired

    securities = evaluate(
        _facts(
            ts=when,
            amount=100_000_000,
            sender="c" * 64,
            call_state="none",
            new_payee=True,
            funds_events=_inflow("lender_inflow", 100_000_000, when),
            habit_money_rare=True,
            payee_account_type="securities",
            payee_holder_name="NGUYEN VAN B",
            p_fraud=0.0,
        )
    )
    assert "R_FUNDS_PASSTHROUGH" not in securities.rules_fired


def test_investment_is_high_risk_only_for_a_new_personal_account():
    personal = evaluate(
        _facts(
            ts=WHEN,
            amount=50_000_000,
            call_state="none",
            new_payee=True,
            task_type="new_typed",
            transfer_purpose="investment",
            funds_events=[],
            payee_account_type="personal",
            payee_holder_name="TRAN VAN C",
            p_fraud=0.0,
            sender="d" * 64,
        )
    )
    assert personal.level == 2
    assert "R_PURPOSE_HIGH_RISK" in personal.rules_fired

    firm = evaluate(
        _facts(
            ts=WHEN,
            amount=50_000_000,
            call_state="none",
            new_payee=True,
            transfer_purpose="investment",
            funds_events=[],
            payee_account_type="securities",
            payee_holder_name="CONG TY CHUNG KHOAN DEMO",
            p_fraud=0.0,
            sender="e" * 64,
        )
    )
    assert "R_PURPOSE_HIGH_RISK" not in firm.rules_fired

    known = evaluate(
        _facts(
            ts=WHEN,
            amount=50_000_000,
            call_state="none",
            new_payee=False,
            task_type="saved_payee",
            transfer_purpose="investment",
            funds_events=[],
            payee_account_type="personal",
            p_fraud=0.0,
            sender="f" * 64,
        )
    )
    assert "R_PURPOSE_HIGH_RISK" not in known.rules_fired


def test_a_level_2_episode_still_floors_another_new_payee_twelve_hours_later():
    state = MemoryState()
    sender = "9" * 64
    opened = evaluate(
        _facts(
            sender=sender,
            payee="1" * 64,
            ts=WHEN,
            amount=100_000_000,
            call_state="none",
            new_payee=True,
            task_type="new_typed",
            funds_events=_inflow("p2p_inflow", 100_000_000),
            habit_money_rare=True,
            payee_account_type="personal",
            p_fraud=0.0,
        ),
        state,
    )
    assert opened.level == 2
    later = evaluate(
        _facts(
            sender=sender,
            payee="2" * 64,
            ts=WHEN + timedelta(hours=12),
            amount=1_000_000,
            call_state="none",
            new_payee=True,
            task_type="new_typed",
            funds_events=[],
            habit_money_rare=False,
            p_fraud=0.0,
        ),
        state,
    )
    assert later.level == 2
    assert later.episode_id == opened.episode_id
    assert "R_FUNDS_PASSTHROUGH" not in later.rules_fired
