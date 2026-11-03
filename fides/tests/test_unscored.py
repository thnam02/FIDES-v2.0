"""/decide không kịp trả lời thì không phải mức 0 và không ghi người nhận mới."""

from __future__ import annotations

import json
import os
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import psycopg
import pytest
import redis
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "bank-core"), str(REPO)]
os.environ["FIDES_HMAC_KEY"] = "fides-demo-hmac"
os.environ["FIDES_API_KEY"] = "fides-demo-key"
os.environ["DATABASE_URL"] = "postgresql://hainamtran@localhost:5432/fides_w1"
os.environ["DEMO_REPLAY"] = "0"
os.environ["BANK_RESEED"] = "0"
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

from engine.common.hashing import account_hash, reset_key_cache
from enforce import FRAUD_CONFIRMED, GUARDIAN_DECLINED, UNSCORED_HEADLINE

SENDER = "A0002119"
NEW_PAYEE = "ZUNSCORED00000001"
SAVED_PAYEE = "ZSAVED0000000001"
PURPOSE = "pytest-unscored"
DATABASE = os.environ["DATABASE_URL"]


def _load():
    reset_key_cache()
    spec = spec_from_file_location("bank_core_unscored", REPO / "bank-core" / "app.py")
    module = module_from_spec(spec)
    sys.modules["bank_core_unscored"] = module
    spec.loader.exec_module(module)
    return module


def _balance(account: str) -> int:
    with psycopg.connect(DATABASE) as conn:
        row = conn.execute("SELECT balance FROM bank.accounts WHERE id = %s", (account,)).fetchone()
    assert row is not None
    return int(row[0])


def _cleanup(sender: str, balance: int) -> None:
    with psycopg.connect(DATABASE) as conn:
        rows = conn.execute("SELECT id FROM bank.transfers WHERE purpose_text = %s", (PURPOSE,)).fetchall()
        ids = [row[0] for row in rows]
        if ids:
            conn.execute("DELETE FROM bank.entries WHERE tx_id = ANY(%s) OR tx_id = ANY(%s)", (ids, [f"{item}:refund" for item in ids]))
            conn.execute("DELETE FROM bank.transfers WHERE id = ANY(%s)", (ids,))
        conn.execute("DELETE FROM bank.beneficiaries WHERE id = %s", ("BE-pytest-unscored",))
        conn.execute("UPDATE bank.accounts SET balance = %s WHERE id = %s", (balance, sender))
        conn.commit()


@pytest.fixture()
def bank():
    module = _load()
    mode = {"down": True, "level": 2}

    def engine_post(path: str, body: dict, timeout: float = 30) -> dict:
        del body, timeout
        if mode["down"] and path == "/decide":
            raise module.EngineUnavailable("timeout")
        if path == "/decide":
            return {
                "level": mode["level"],
                "funds_status": "held",
                "hold_until": None,
                "countdown_until": None,
                "actions": ["pause_and_verify"],
                "reasons": [{"code": "shown", "text": "giữ"}],
                "signals_present": ["new_payee"],
                "rules_fired": ["R_CALL_FUNDS_NEWPAYEE"],
                "headline": "giữ",
                "intervention": "three_button",
            }
        if path == "/respond":
            return {"level": "medium", "funds_status": "cancelled", "gate": "none", "hold_until": None, "countdown_until": None}
        return {}

    module.engine_post = engine_post
    before = _balance(SENDER)
    with TestClient(module.app) as client:
        yield module, client, mode
    _cleanup(SENDER, before)


def _transfer(client, payee: str, amount: int = 10_000) -> dict:
    response = client.post(
        "/transfer",
        json={"from_account": SENDER, "to_account": payee, "amount": amount, "purpose_text": PURPOSE},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_a_new_payee_is_a_level_1_sheet_and_is_not_recorded(bank, caplog):
    _module, client, _mode = bank
    before = _balance(SENDER)
    with caplog.at_level("WARNING"):
        payload = _transfer(client, NEW_PAYEE)
    assert payload["status"] == "awaiting_confirmation"
    assert payload["decision"]["unscored"] is True
    assert payload["decision"]["level"] == 1
    assert payload["decision"]["level"] != 0
    assert payload["decision"]["headline"] == UNSCORED_HEADLINE
    assert _balance(SENDER) == before
    with psycopg.connect(DATABASE) as conn:
        row = conn.execute(
            "SELECT posted, level FROM bank.transfers WHERE id = %s",
            (payload["transfer_id"],),
        ).fetchone()
    assert row[0] is False
    assert "engine_unavailable" in caplog.text


def test_a_saved_payee_proceeds_and_is_not_level_zero(bank):
    _module, client, _mode = bank
    before = _balance(SENDER)
    with psycopg.connect(DATABASE) as conn:
        conn.execute(
            """
            INSERT INTO bank.beneficiaries (id, owner_account, account_id, holder_name, saved_at, times_paid)
            VALUES (%s, %s, %s, %s, now(), 1)
            """,
            ("BE-pytest-unscored", SENDER, SAVED_PAYEE, "Đã lưu"),
        )
        conn.commit()
    payload = _transfer(client, SAVED_PAYEE, 20_000)
    assert payload["status"] == "done"
    assert payload["funds_status"] == "released"
    assert payload["decision"]["unscored"] is True
    assert payload["decision"]["level"] is None
    assert payload["decision"]["level"] != 0
    assert _balance(SENDER) == before - 20_000


def test_fraud_and_guardian_decline_refund_and_leave_the_episode(bank):
    module, client, mode = bank
    mode["down"] = False
    before = _balance(SENDER)
    payload = _transfer(client, NEW_PAYEE, 30_000)
    assert payload["status"] == "needs_verification"
    assert _balance(SENDER) == before - 30_000
    client_redis = redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    key = f"pol:v24:{account_hash(SENDER)}"
    previous = client_redis.get(key)
    marker = json.dumps({"episode_id": "ep-pytest-unscored", "expires_at": "2026-09-22T10:00:00+07:00"})
    client_redis.set(key, marker)
    try:
        fraud = client.post(f"/transfer/{payload['transfer_id']}/hotline-fraud")
        assert fraud.status_code == 200, fraud.text
        body = fraud.json()
        assert body["status"] == "cancelled"
        assert body["funds_status"] == "cancelled"
        assert body["message"] == FRAUD_CONFIRMED
        assert _balance(SENDER) == before
        assert client_redis.get(key) == marker
        again = _transfer(client, NEW_PAYEE, 15_000)
        decline = client.post(f"/transfer/{again['transfer_id']}/guardian-decline")
        assert decline.status_code == 200, decline.text
        assert decline.json()["message"] == GUARDIAN_DECLINED
        assert _balance(SENDER) == before
        assert client_redis.get(key) == marker
    finally:
        if previous is None:
            client_redis.delete(key)
        else:
            client_redis.set(key, previous)
        del module
