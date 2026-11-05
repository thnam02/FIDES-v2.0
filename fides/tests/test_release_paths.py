"""Release paths of held transfers, through the bank API only.

Runs against a running stack right after scripts/demo_reset.sh, never the live demo:
FIDES_STACK_BANK=http://127.0.0.1:8192 pytest fides/tests/test_release_paths.py
Changes the ledger of that stack. Run demo_reset.sh again afterwards.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid

import pytest

BANK = os.environ.get("FIDES_STACK_BANK", "").rstrip("/")
pytestmark = pytest.mark.skipif(not BANK, reason="FIDES_STACK_BANK is not set (needs an isolated stack)")

HUYNH = "A0072556"
HOANG = "A0051289"
MULE = "ZMULEDEMO0000001"
CALL = {"state": "active", "observability": "supported_observed", "transport": "cellular"}
ENDED = {"state": "ended_in_session", "observability": "supported_observed", "transport": "cellular"}
NONE = {"state": "none", "observability": "supported_observed", "transport": "unknown"}


def call(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json"}
    if path == "/transfer":
        headers["Idempotency-Key"] = str(uuid.uuid4())
    key = os.environ.get("BANK_API_KEY", "")
    if key:
        headers["X-Bank-Key"] = key
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(BANK + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read().decode()
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"detail": raw}


def ok(method: str, path: str, body: dict | None = None) -> dict:
    status, payload = call(method, path, body)
    assert status == 200, (path, status, payload)
    return payload


def balance(account: str) -> int:
    return int(ok("GET", f"/accounts/{account}")["balance"])


def send(sender: str, payee: str, amount: int, call_block: dict, purpose: str = "purchase") -> dict:
    return ok("POST", "/transfer", {
        "from_account": sender, "to_account": payee, "amount": amount,
        "task_type": "new_typed", "add_method": "typed", "device": {"state": "none"},
        "call": call_block, "transfer_purpose": purpose,
    })


def held_level2(payee: str, amount: int = 2_000_000, purpose: str = "purchase") -> dict:
    out = send(HUYNH, payee, amount, CALL, purpose)
    assert out["decision"]["level"] == 2, out["decision"]
    assert out["funds_status"] == "held"
    return out


def guardian_request(transfer_id: str) -> dict | None:
    rows = ok("GET", "/guardian/requests")["requests"]
    return next((row for row in rows if row["transfer_id"] == transfer_id), None)


@pytest.fixture(scope="module", autouse=True)
def huynh_ready():
    """Mrs. Mận's guardian is seeded by demo_reset.sh, past the cooling-off. Liquidate the savings book once."""
    ok("POST", "/savings/liquidate", {"account_id": HUYNH, "amount": 150_000_000})
    yield


def test_customer_cannot_release_through_guardian_confirm():
    out = held_level2("ZMED230000000001")
    assert "guardian_confirm" in out["decision"]["actions"]
    before = balance("ZMED230000000001")
    for body in ({"guardian_confirm": True}, {"guardian_confirm": True, "proceed": True, "call": NONE}):
        status, payload = call("POST", f"/transfer/{out['transfer_id']}/respond", body)
        assert status == 409, payload
    assert balance("ZMED230000000001") == before
    assert guardian_request(out["transfer_id"]) is not None


def test_send_guardian_request_never_releases():
    out = held_level2("ZMED220000000001")
    before = balance("ZMED220000000001")
    sent = ok("POST", f"/transfer/{out['transfer_id']}/guardian-request")
    assert sent["status"] == "sent"
    again = ok("POST", f"/transfer/{out['transfer_id']}/guardian-request")
    assert again["request_id"] == sent["request_id"]
    assert balance("ZMED220000000001") == before
    assert guardian_request(out["transfer_id"])["funds_status"] == "held"


def test_mixed_body_is_rejected():
    out = held_level2("ZLAN120000000001")
    before = balance("ZLAN120000000001")
    status, payload = call("POST", f"/transfer/{out['transfer_id']}/respond", {"cancel": True, "proceed": True, "call": NONE})
    assert status == 400, payload
    assert balance("ZLAN120000000001") == before


def test_proceed_needs_hang_up_then_pays_once():
    out = held_level2("ZANH000000000099")
    tid = out["transfer_id"]
    payee_before = balance("ZANH000000000099")
    status, payload = call("POST", f"/transfer/{tid}/respond", {"proceed": True, "call": CALL})
    assert status == 409, payload
    released = ok("POST", f"/transfer/{tid}/respond", {"proceed": True, "call": ENDED})
    assert released["funds_status"] == "released"
    assert balance("ZANH000000000099") == payee_before + 2_000_000
    sender_after = balance(HUYNH)
    for body in ({"proceed": True, "call": ENDED}, {"cancel": True}):
        status, payload = call("POST", f"/transfer/{tid}/respond", body)
        assert status == 409, payload
    status, payload = call("POST", f"/transfer/{tid}/hotline-fraud")
    assert status == 409, payload
    assert balance(HUYNH) == sender_after
    assert balance("ZANH000000000099") == payee_before + 2_000_000


def test_level3_is_never_decided_by_customer_or_guardian():
    out = send(HOANG, MULE, 500_000, NONE, "other")
    assert out["decision"]["level"] == 3, out["decision"]
    tid = out["transfer_id"]
    decision = f"dec-{tid}"
    mule_before = balance(MULE)
    for path, body in (
        (f"/transfer/{tid}/respond", {"proceed": True, "call": NONE}),
        (f"/transfer/{tid}/respond", {"cancel": True}),
        (f"/decisions/{decision}/choice", {"choice": "continue", "response_ms": 0, "call": NONE}),
        (f"/decisions/{decision}/choice", {"choice": "cancel", "response_ms": 0}),
        (f"/transfer/{tid}/guardian-request", None),
        (f"/transfer/{tid}/guardian-decline", None),
    ):
        status, payload = call("POST", path, body)
        assert status == 409, (path, payload)
    assert balance(MULE) == mule_before


def test_no_double_pay_after_a_cancel():
    sender_before = balance(HUYNH)
    out = held_level2("ZMED000000000001")
    tid = out["transfer_id"]
    request = guardian_request(tid)
    assert request is not None
    payee_before = balance("ZMED000000000001")
    ok("POST", f"/decisions/dec-{tid}/choice", {"choice": "cancel", "response_ms": 0})
    assert balance(HUYNH) == sender_before
    status, payload = call("POST", f"/guardian/requests/{request['id']}/confirm")
    assert status == 409, payload
    status, payload = call("POST", f"/transfer/{tid}/respond", {"proceed": True, "call": ENDED})
    assert status == 409, payload
    assert balance("ZMED000000000001") == payee_before
    assert balance(HUYNH) == sender_before


def test_paused_transfer_is_refunded_when_cancelled():
    sender_before = balance(HUYNH)
    out = held_level2("ZLANB40000000001", amount=3_000_000)
    tid = out["transfer_id"]
    paused = ok("POST", f"/decisions/dec-{tid}/choice", {"choice": "pause", "response_ms": 0})
    assert paused["status"] == "pending_draft"
    assert balance(HUYNH) == sender_before - 3_000_000
    ok("POST", f"/transfer/{tid}/hotline-fraud")
    assert balance(HUYNH) == sender_before


def test_guardian_confirms_an_open_request_once_even_inside_the_lock():
    out = held_level2("ZLANB40000000002", amount=4_000_000, purpose="authority_request")
    assert out["decision"]["strengthened"] is True
    tid = out["transfer_id"]
    request = guardian_request(tid)
    assert request is not None
    payee_before = balance("ZLANB40000000002")
    confirmed = ok("POST", f"/guardian/requests/{request['id']}/confirm")
    assert confirmed["funds_status"] == "released"
    assert balance("ZLANB40000000002") == payee_before + 4_000_000
    status, payload = call("POST", f"/guardian/requests/{request['id']}/confirm")
    assert status == 409, payload
    assert balance("ZLANB40000000002") == payee_before + 4_000_000


def test_a_guardian_added_during_the_scam_cannot_approve():
    """Last in this module: it replaces the seeded guardian."""
    out = held_level2("ZVAY000000000001", amount=2_500_000)
    tid = out["transfer_id"]
    request = guardian_request(tid)
    assert request is not None
    ok("POST", "/guardian", {"account_id": HUYNH, "phone": "0907654321", "relation": "con", "consent": True})
    payee_before = balance("ZVAY000000000001")
    status, payload = call("POST", f"/transfer/{tid}/guardian-request")
    assert status == 409 and "chưa thể xác nhận" in payload["detail"], payload
    status, payload = call("POST", f"/guardian/requests/{request['id']}/confirm")
    assert status == 409 and "chưa thể xác nhận" in payload["detail"], payload
    assert balance("ZVAY000000000001") == payee_before
    assert guardian_request(tid)["funds_status"] == "held"
