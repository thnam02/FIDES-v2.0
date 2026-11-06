"""Five demo scenes by API, in order, right after one scripts/demo_reset.sh.

Bodies mirror what the app sends. Changes the ledger: run demo_reset.sh again before the live demo.
Exit code 1 when a scene does not match docs/demo_manual.md.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def dotenv() -> dict[str, str]:
    """Same .env as the demo scripts. The shell environment wins."""
    path = ROOT / ".env"
    if not path.is_file():
        return {}
    pairs = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            pairs[key.strip()] = value.strip()
    return pairs


SETTINGS = {**dotenv(), **os.environ}
BANK = SETTINGS.get("BANK_URL") or f"http://127.0.0.1:{SETTINGS.get('BANK_PORT', '8092')}"
NONE = {"state": "none", "observability": "supported_observed", "transport": "unknown"}
CALL = {"state": "active", "observability": "supported_observed", "transport": "cellular"}
ENDED = {"state": "ended_in_session", "observability": "supported_observed", "transport": "cellular"}
DEVICE = {"state": "none"}

SCENE3_HEADLINE = "Bạn vừa rút tiền tiết kiệm hoặc nhận tiền và đang chuyển cho người lạ trong lúc nghe điện thoại. Đây là cách kẻ giả danh công an thường lừa tiền."
SCENE4_HEADLINE = "Cách bạn thao tác giống như đang được người khác đọc cho từng bước."
SCENE5_HEADLINE = SCENE4_HEADLINE
DICTATION = "Bạn nhập số tài khoản theo từng cụm, như đang được đọc cho."
CALL_LINE = "Có cuộc gọi đang diễn ra trong phiên này."
NEAR_BALANCE = "Bạn đang chuyển gần hết số dư."


def guided_features() -> dict:
    """Same numbers as the app's "Demo: phiên có hướng dẫn" switch."""
    text = (ROOT / "bank-app" / "src" / "dev" / "guided.ts").read_text(encoding="utf-8")
    return {key: float(value) if "." in value else int(value) for key, value in re.findall(r"(\w+): ([0-9.]+),", text)}


def call(method: str, path: str, body: dict | None = None, key: bool = False) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json"}
    if SETTINGS.get("BANK_API_KEY"):
        headers["X-Bank-Key"] = SETTINGS["BANK_API_KEY"]
    if key:
        headers["Idempotency-Key"] = str(uuid.uuid4())
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


def visible(decision: dict) -> list[str]:
    card = decision.get("evidence_card") or {}
    said = set(card.get("restated_vi") or [])
    return [line for line in card.get("reasons_vi") or [] if line not in said][:2]


def hidden(decision: dict) -> list[str]:
    card = decision.get("evidence_card") or {}
    reasons = list(card.get("reasons_vi") or [])
    shown = visible(decision)
    rest = [line for line in reasons if line not in shown]
    return rest


FAILED: list[str] = []


def check(label: str, ok: bool, detail: object) -> None:
    print(f"{'PASS' if ok else 'FAIL'} {label}: {json.dumps(detail, ensure_ascii=False)}")
    if not ok:
        FAILED.append(label)


def transfer(body: dict) -> tuple[int, dict]:
    return call("POST", "/transfer", body, key=True)


def summary(status: int, payload: dict) -> dict:
    decision = payload.get("decision") or {}
    return {
        "http": status,
        "level": decision.get("level"),
        "groups": decision.get("groups_fired"),
        "strengthened": decision.get("strengthened"),
        "headline": decision.get("headline"),
        "visible": visible(decision),
        "hidden": hidden(decision),
        "actions": decision.get("actions"),
        "detail": payload.get("detail"),
        "status": payload.get("status"),
    }


def report(label: str, payload: dict) -> None:
    decision = payload.get("decision") or {}
    print(f"REPORT {label}: {json.dumps({'headline': decision.get('headline'), 'visible': visible(decision), 'xem_chi_tiet': hidden(decision), 'actions': decision.get('actions'), 'strengthened': decision.get('strengthened'), 'lock_minutes': decision.get('lock_minutes')}, ensure_ascii=False)}")


def main() -> None:
    status, saved = call("GET", "/accounts/A0051289/beneficiaries")
    vo = next((row for row in saved.get("beneficiaries", []) if "Võ Tiến Hà" in (row.get("holder_name") or "")), None)
    check("1 saved payee Võ Tiến Hà", vo is not None, {"http": status})
    if vo is None:
        sys.exit(1)

    status, out = transfer({
        "from_account": "A0051289", "to_account": vo["account_id"], "amount": 500_000,
        "task_type": "saved_payee", "add_method": "contact", "device": DEVICE, "call": NONE,
        "transfer_purpose": "not_asked",
    })
    got = summary(status, out)
    check("1 Hoàng level 0", got["level"] == 0 and out.get("status") == "done", got)

    status, out = transfer({
        "from_account": "A0031239", "to_account": "A0119434", "amount": 60_000,
        "task_type": "qr", "add_method": "qr", "device": DEVICE, "call": CALL, "transfer_purpose": "purchase",
    })
    got = summary(status, out)
    check("2 Lê level 1 sheet", got["level"] == 1 and out.get("status") == "awaiting_confirmation" and got["visible"] == [], got)

    status, out = transfer({
        "from_account": "A9900001", "to_account": "0902102002", "amount": 120_000_000,
        "task_type": "new_typed", "add_method": "typed", "device": DEVICE, "call": NONE, "transfer_purpose": "purchase",
    })
    check("3 Vũ refused before liquidation", status == 400, summary(status, out))

    status, out = call("POST", "/savings/liquidate", {"account_id": "A9900001", "amount": 150_000_000, "device": DEVICE})
    check("3 liquidate 150 million", status == 200, {"http": status})

    status, held = transfer({
        "from_account": "A9900001", "to_account": "0902102002", "amount": 120_000_000,
        "task_type": "new_typed", "add_method": "typed", "device": DEVICE, "call": CALL, "transfer_purpose": "purchase",
    })
    got = summary(status, held)
    report("3 Vũ group A", held)
    check(
        "3 Vũ 120 million level 2 group A",
        got["level"] == 2 and got["groups"] == ["A"] and not got["strengthened"]
        and got["headline"] == SCENE3_HEADLINE
        and got["visible"] == [NEAR_BALANCE],
        got,
    )
    check("3 no guardian button", "guardian_confirm" not in (got["actions"] or []), got["actions"])
    tid = held.get("transfer_id")
    status, blocked = call("POST", f"/transfer/{tid}/respond", {"proceed": True, "call": CALL})
    check("3 proceed while still on the call rejected", status == 409, blocked)
    status, released = call("POST", f"/transfer/{tid}/respond", {"proceed": True, "call": ENDED})
    check("3 hang-up unlocks continue", status == 200 and released.get("status") in {"done", "released"}, {"http": status, "status": released.get("status"), "funds": released.get("funds_status")})

    status, out = transfer({
        "from_account": "A0072556", "to_account": "0902101002", "amount": 120_000_000,
        "task_type": "new_typed", "add_method": "typed", "device": DEVICE, "call": NONE, "transfer_purpose": "purchase",
    })
    check("4 Huỳnh refused before liquidation", status == 400, summary(status, out))

    status, out = call("POST", "/savings/liquidate", {"account_id": "A0072556", "amount": 150_000_000, "device": DEVICE})
    check("4 liquidate 150 million", status == 200, {"http": status})

    status, step4 = transfer({
        "from_account": "A0072556", "to_account": "0902101002", "amount": 120_000_000,
        "task_type": "new_typed", "add_method": "typed", "device": DEVICE, "call": CALL,
        "behaviour_features": guided_features(), "transfer_purpose": "purchase",
    })
    got = summary(status, step4)
    report("4 Huỳnh A+B", step4)
    check(
        "4 Huỳnh 120 million strengthened A + B",
        got["level"] == 2 and got["groups"] == ["A", "B"] and got["strengthened"]
        and got["headline"] == SCENE4_HEADLINE
        and got["visible"] == [DICTATION, CALL_LINE],
        got,
    )
    check("4 guardian button offered (seeded guardian)", "guardian_confirm" in (got["actions"] or []), got["actions"])
    tid = step4.get("transfer_id")
    status, rejected = call("POST", f"/transfer/{tid}/respond", {"proceed": True, "call": ENDED})
    check("4 proceed after hang-up rejected", status == 409, rejected)
    _, before = call("GET", "/accounts/A0072556")
    status, fraud = call("POST", f"/transfer/{tid}/hotline-fraud")
    _, after = call("GET", "/accounts/A0072556")
    refund = int(after.get("balance", 0)) - int(before.get("balance", 0))
    check("4 hotline fraud cancels and refunds", status == 200 and fraud.get("status") == "cancelled" and refund == 120_000_000, {"refund": refund})

    status, out = transfer({
        "from_account": "A0002119", "to_account": "0902402001", "amount": 500_000,
        "task_type": "new_typed", "add_method": "typed", "device": DEVICE, "call": CALL,
        "behaviour_features": guided_features(), "transfer_purpose": "other",
    })
    got = summary(status, out)
    report("5 Trương group B", out)
    check(
        "5 Trương level 2 group B dictation",
        got["level"] == 2 and got["groups"] == ["B"] and not got["strengthened"]
        and got["headline"] == SCENE5_HEADLINE
        and got["visible"] == [DICTATION, CALL_LINE],
        got,
    )

    print("all scenes match" if not FAILED else f"{len(FAILED)} failed: {', '.join(FAILED)}")
    print("The ledger changed. Run sh scripts/demo_reset.sh before the live demo.")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
