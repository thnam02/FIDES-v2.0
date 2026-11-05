"""Bank-core. Đóng dấu đồng hồ demo, gọi engine bằng API key, giữ tiền mức 2 và 3."""

from __future__ import annotations

import json
import logging
import hmac
import os
import threading
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta
from typing import Annotated, Literal

import pandas as pd
import psycopg
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from clock import ICT, DemoClock
from enforce import (
    FRAUD_CONFIRMED,
    GUARDIAN_DECLINED,
    HANGUP_MESSAGE,
    LOCK_MESSAGE,
    block_proceed,
    flags_from_decision,
    rejection_choice,
    unscored_decision,
)
from engine.common.hashing import account_hash, require_key
from engine.policy.inflows import classify_inflows, recent_outflows
from engine.policy.v24 import load_policy
from load import CUT, OBSERVED, PERSONAS, SCHEMA, load
from notice import notice_allowed, notice_limits

log = logging.getLogger("bank")
DECIDE_TIMEOUT_S = 0.3
PURPOSE_AMOUNT_VND = int(os.environ.get("PURPOSE_AMOUNT_VND", "10000000"))
# Khớp funds_fresh_hours. Kênh lấy từ sổ: app, branch, hoặc unknown khi sổ không ghi.
FUNDS_HOURS = 72
BRANCH_CLOSURE_ID = "P-demo-branch-closure"
FUNDS_KINDS = (
    "term_deposit_closure",
    "savings_liquidation",
    "fast_loan_disbursement",
    "quick_loan_disbursement",
    "limit_increase",
    "limit_raise",
    "card_cash_advance",
    "credit_card_cash_advance",
)
# Danh sách demo, gắn nhãn. Không phải hồ sơ đường dây thật.
DEMO_MULE_ACCOUNTS = frozenset({"ZMULEDEMO0000001"})
RESET_AT = datetime.fromisoformat("2026-09-20T09:00:00+07:00")

CLOCK = DemoClock(speed=float(os.environ.get("DEMO_CLOCK_SPEED", "1")))
# Người nhận chỉ có trong các cảnh demo. Không phải khách thật.
DEMO_PAYEES = {
    "A0119434": "Công ty TNHH Thành Công",
    "ZCAP400000000001": "Đặng Quốc Bảo",
    "ZGUIDE4000000001": "Ngô Thanh Hà",
    "ZMULEDEMO0000001": "Trịnh Văn Khôi",
    "ZMED230000000001": "Lý Minh Châu",
    "ZMED220000000001": "Lý Hồng Nhung",
    "ZMED000000000001": "Lý Hồng Nhung",
    "ZLANB40000000001": "Phạm Thu Ngân",
    "ZLANB40000000002": "Mai Phương Thảo",
    "ZLAN120000000001": "Phạm Thu Ngân",
    "ZANH000000000099": "Võ Anh Thư",
    "ZVAY000000000001": "Bùi Hải Yến",
}
# Cùng bảng với bank-app/src/format.ts. Hậu tố giữ nguyên để fixture engine khớp. Thiếu thì đệm trái thành 10 số.
DEMO_NUMBERS = {
    "A0119434": "0901119434",
    "ZCAP400000000001": "0902401001",
    "ZGUIDE4000000001": "0902402001",
    "ZMULEDEMO0000001": "0902003001",
    "ZMED230000000001": "0902230230",
    "ZMED220000000001": "0902220220",
    "ZMED000000000001": "0902000001",
    "ZLANB40000000001": "0902101002",
    "ZLANB40000000002": "0902102002",
    "ZLAN120000000001": "0902120120",
    "ZANH000000000099": "0902000099",
    "ZVAY000000000001": "0902004001",
}
SKIP: set[str] = set()
SESSIONS: set[str] = set()
FEED: list[tuple[datetime, dict]] = []
FEED_CURSOR = 0
RESET_ID = ""
LEDGER_MISMATCH = False
_REPLAY_STARTED = False


def database_url() -> str:
    raw = os.environ.get("DATABASE_URL", "")
    if not raw:
        raise RuntimeError("DATABASE_URL thiếu, không khởi động")
    return raw


def connect():
    return psycopg.connect(database_url(), row_factory=psycopg.rows.dict_row)


class EngineUnavailable(Exception):
    pass


def reset_id() -> str:
    return RESET_ID


def remember_reset(conn, value: str) -> None:
    global RESET_ID
    RESET_ID = value
    conn.execute(
        """
        INSERT INTO bank.demo_state (id, reset_id) VALUES (1, %s)
        ON CONFLICT (id) DO UPDATE SET reset_id = EXCLUDED.reset_id
        """,
        (value,),
    )


def load_reset(conn) -> None:
    global RESET_ID
    conn.execute(SCHEMA)
    row = conn.execute("SELECT reset_id FROM bank.demo_state WHERE id = 1").fetchone()
    RESET_ID = str(row["reset_id"]) if row else ""


def engine_reset_id() -> str | None:
    url = os.environ.get("ENGINE_URL", "http://127.0.0.1:8091").rstrip("/") + "/health"
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            payload = json.loads(response.read().decode())
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None
    return str(payload.get("reset_id", ""))


def engine_post(path: str, body: dict, timeout: float = 30) -> dict:
    global LEDGER_MISMATCH
    url = os.environ.get("ENGINE_URL", "http://127.0.0.1:8091").rstrip("/") + path
    request = urllib.request.Request(
        url,
        data=json.dumps(body, default=str).encode(),
        headers={
            "Content-Type": "application/json",
            "X-API-Key": os.environ.get("FIDES_API_KEY", ""),
            "X-Reset-Id": RESET_ID,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()
        if exc.code == 409 and "ledger_mismatch" in detail:
            LEDGER_MISMATCH = True
            log.warning("ledger_mismatch")
            raise HTTPException(409, "ledger_mismatch") from exc
        if exc.code >= 500:
            raise EngineUnavailable(detail) from exc
        raise HTTPException(exc.code, detail) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise EngineUnavailable(str(exc)) from exc


def _us(stamp: datetime) -> int:
    return int(stamp.timestamp() * 1_000_000)


_ACCOUNT_KEYS = {"account", "account_id", "from_account", "to_account", "payee", "sender", "counterparty"}


def _is_hmac(text: str) -> bool:
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def hash_accounts(value):
    """Băm mã tài khoản trước khi ghi. Hash 64 hex giữ nguyên."""
    if isinstance(value, dict):
        hashed = {}
        for key, item in value.items():
            if key in _ACCOUNT_KEYS and isinstance(item, str) and not _is_hmac(item):
                hashed[key] = account_hash(item)
            else:
                hashed[key] = hash_accounts(item)
        return hashed
    if isinstance(value, list):
        return [hash_accounts(item) for item in value]
    return value


def _plain(value):
    if value is None:
        return None
    if isinstance(value, BaseModel):
        # Số cụm vắng nghĩa là không biết. Không gửi null như thể bằng không.
        if type(value).__name__ == "BehaviourIn":
            return value.model_dump(exclude_none=True)
        return value.model_dump()
    return value


def _ensure_experiment_column(conn) -> None:
    conn.execute("ALTER TABLE bank.experiment_sessions ADD COLUMN IF NOT EXISTS decision jsonb")


def touch_session(account: str, device: dict | None, now: datetime) -> str:
    session = f"demo-{account}"
    hashed = account_hash(account)
    try:
        if account not in SESSIONS:
            mode = (device or {}).get("acct_input") or "typed"
            with connect() as conn:
                customer = conn.execute("SELECT customer_id FROM bank.accounts WHERE id = %s", (account,)).fetchone()
            engine_post(
                "/events",
                {
                    "type": "session",
                    "session": session,
                    "account": hashed,
                    "start": _us(now),
                    "end": _us(datetime.fromisoformat("2026-09-29T00:00:00+07:00")),
                    "customer": (customer or {}).get("customer_id") or "",
                    "first_input": mode,
                },
                timeout=DECIDE_TIMEOUT_S,
            )
            SESSIONS.add(account)
        if device:
            engine_post(
                "/events",
                {
                    "type": "device_signal",
                    "ts": _us(now),
                    "session": session,
                    "in_call": "1" if device.get("in_call") else "0",
                    "ended": "1" if device.get("call_ended_in_session") else "0",
                },
                timeout=DECIDE_TIMEOUT_S,
            )
            if device.get("acct_input"):
                engine_post(
                    "/events",
                    {"type": "session_event", "ts": _us(now), "session": session, "event_type": f"acct_input_{device['acct_input']}"},
                    timeout=DECIDE_TIMEOUT_S,
                )
    except EngineUnavailable:
        log.warning("engine_unavailable")
    return session


def post_ledger(event: dict) -> None:
    try:
        engine_post("/events", event)
    except EngineUnavailable:
        log.warning("engine_unavailable")


def _payee_established(conn, sender: str, payee: str) -> bool:
    """Đã lưu, hoặc đã có lệnh thật sự ghi sổ. Lệnh chờ và lệnh huỷ không làm người nhận thành người quen."""
    saved = conn.execute(
        """
        SELECT 1 FROM bank.beneficiaries
        WHERE owner_account = %s AND account_id = %s
        LIMIT 1
        """,
        (sender, payee),
    ).fetchone()
    if saved:
        return True
    settled = conn.execute(
        """
        SELECT 1
        FROM bank.transfers t
        JOIN bank.accounts sender ON sender.id = t.from_account
        WHERE sender.customer_id = (SELECT customer_id FROM bank.accounts WHERE id = %s)
          AND t.to_account = %s
          AND t.posted = true
        LIMIT 1
        """,
        (sender, payee),
    ).fetchone()
    return settled is not None


def _level_number(level) -> int | None:
    if level in (None, "", "unscored"):
        return None
    if isinstance(level, bool):
        return 0
    if isinstance(level, int):
        return level
    try:
        return int(level)
    except (TypeError, ValueError):
        return numeric_level(level)


def numeric_level(level) -> int:
    """/decide trả 0–3. /respond cũ vẫn trả chữ; cửa ngân hàng đổi về số trước khi trả khách."""
    if isinstance(level, bool):
        return 0
    if isinstance(level, int):
        return level
    if level in (None, "unscored"):
        return 0
    return {"none": 0, "info": 0, "banner": 1, "medium": 2, "high": 3}.get(str(level), 0)


def _fallback(conn, sender: str, payee: str, amount: int) -> dict:
    """Không chấm được thì không phải mức 0, và không ghi người nhận mới vào sổ."""
    del amount
    log.warning("engine_unavailable")
    return unscored_decision(_payee_established(conn, sender, payee))


def status_of(level: int, funds: str, hung_up: bool) -> str:
    if funds == "cancelled":
        return "cancelled"
    if funds == "released":
        return "done" if level <= 1 else "released"
    if level >= 3 and not hung_up:
        return "blocked_pending_hangup"
    if level == 2:
        return "needs_verification"
    return "held"


def credit(conn, account: str, amount: int) -> None:
    conn.execute("UPDATE bank.accounts SET balance = balance + %s WHERE id = %s", (amount, account))


ADD_METHODS = frozenset({"typed", "paste", "qr", "contact"})


def add_method_for(task_type: str | None, entry_detail: str | None, explicit: str | None) -> str | None:
    """Cách nhập mà model-v2.1 đã học. Ảnh không có cột riêng, nên dùng paste."""
    if explicit in ADD_METHODS:
        return explicit
    if entry_detail in {"paste", "image_capture", "image_upload"}:
        return "paste"
    if task_type == "qr":
        return "qr"
    if task_type == "saved_payee":
        return "contact"
    if task_type == "new_pasted":
        return "paste"
    if task_type == "new_typed":
        return "typed"
    return None


def spent_today(conn, account: str, now: datetime) -> int:
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    spent = conn.execute(
        """
        SELECT COALESCE(SUM(amount), 0) AS n FROM bank.transfers
        WHERE from_account = %s AND created_at >= %s
          AND status NOT IN ('cancelled', 'awaiting_confirmation', 'expired')
        """,
        (account, start),
    ).fetchone()
    return int(spent["n"])


def load_account(conn, account: str):
    row = conn.execute(
        "SELECT balance, segment, has_guardian, limit_per_txn, limit_per_day FROM bank.accounts WHERE id = %s",
        (account,),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "không có tài khoản")
    return row


def reject_if_cannot_pay(row, amount: int, spent: int) -> None:
    if int(row["balance"]) < amount:
        raise HTTPException(400, "không đủ số dư")
    if amount > int(row["limit_per_txn"]):
        raise HTTPException(400, "vượt hạn mức giao dịch")
    if spent + amount > int(row["limit_per_day"]):
        raise HTTPException(400, "vượt hạn mức ngày")


def debit(conn, account: str, amount: int, now: datetime) -> None:
    row = load_account(conn, account)
    reject_if_cannot_pay(row, amount, spent_today(conn, account, now))
    conn.execute("UPDATE bank.accounts SET balance = balance - %s WHERE id = %s", (amount, account))


def entry(conn, account: str, tx_id: str, ts, direction: str, amount: int, tx_type: str, purpose: str, status: str, counterparty: str | None = None) -> None:
    conn.execute(
        """
        INSERT INTO bank.entries (account_id, tx_id, ts, direction, amount, tx_type, purpose_text, status, counterparty_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (account, tx_id, ts, direction, amount, tx_type, purpose, status, counterparty or None),
    )


def release_payee(conn, transfer: dict, now: datetime) -> None:
    if transfer["posted"]:
        return
    owned = conn.execute("SELECT 1 FROM bank.accounts WHERE id = %s", (transfer["to_account"],)).fetchone()
    if owned:
        credit(conn, transfer["to_account"], int(transfer["amount"]))
        entry(conn, transfer["to_account"], transfer["id"], now, "in", int(transfer["amount"]), "transfer", transfer["purpose_text"], "done", transfer["from_account"])
    balance = conn.execute("SELECT balance FROM bank.accounts WHERE id = %s", (transfer["from_account"],)).fetchone()
    session = f"demo-{transfer['from_account']}"
    post_ledger(
        {
            "event_id": f"txn:{transfer['id']}",
            "type": "txn",
            "ts": now.isoformat(),
            "account_hash": account_hash(transfer["from_account"]),
            "counterparty_hash": account_hash(transfer["to_account"]),
            "tx_type": "transfer",
            "amount": int(transfer["amount"]),
            "balance": int(balance["balance"]) if balance else 0,
            "session_id": session,
        }
    )
    conn.execute("UPDATE bank.transfers SET posted = true WHERE id = %s", (transfer["id"],))


def sync_entry(conn, transfer_id: str, account: str, funds: str, status: str) -> None:
    shown = "done" if funds == "released" else "cancelled" if funds == "cancelled" else status
    conn.execute(
        "UPDATE bank.entries SET status = %s WHERE tx_id = %s AND account_id = %s",
        (shown, transfer_id, account),
    )


def apply_funds(conn, transfer: dict, previous: str, funds: str, now: datetime) -> None:
    """Tiền chỉ rời trạng thái giữ. Đã huỷ thì không trả người nhận, đã trả thì không hoàn lại."""
    if funds == previous:
        return
    if previous != "held":
        raise HTTPException(409, "Lệnh không còn bị giữ.")
    if funds == "released":
        release_payee(conn, transfer, now)
    if funds == "cancelled":
        credit(conn, transfer["from_account"], int(transfer["amount"]))
        entry(conn, transfer["from_account"], transfer["id"] + ":refund", now, "in", int(transfer["amount"]), "transfer", "hoàn", "cancelled")


class CallIn(BaseModel):
    state: Literal["active", "ended_in_session", "none", "unknown"]
    observability: Literal["supported_observed", "supported_not_observed", "unavailable"]
    transport: Literal["cellular", "voip", "unknown"]


class BehaviourIn(BaseModel):
    median_gap_ms: float
    p90_gap_ms: float
    burst_count: int
    pause_to_action_ratio: float
    review_dwell_ms: int
    edit_count: int
    backtrack_count: int
    screen_revisit_count: int
    background_count: int
    background_total_ms: int
    session_duration_ms: int
    payee_burst_count: int | None = None
    payee_mean_burst_len: float | None = None
    payee_inter_burst_gap_median_ms: float | None = None


class ExperimentIn(BaseModel):
    participant_id: str
    condition: str
    session_index: int


class TransferIn(BaseModel):
    from_account: str
    to_account: str
    amount: int
    purpose_text: str | None = None
    device: dict | None = None
    task_type: Literal["saved_payee", "new_typed", "new_pasted", "qr"] | None = None
    add_method: Literal["typed", "paste", "qr", "contact"] | None = None
    entry_detail: Literal["paste", "image_capture", "image_upload"] | None = None
    call: CallIn | None = None
    behaviour_features: BehaviourIn | None = None
    transfer_purpose: Literal[
        "authority_request",
        "fee_to_receive",
        "investment",
        "refund_request",
        "purchase",
        "family_friends",
        "debt_salary",
        "other",
        "not_asked",
    ] | None = None
    experiment: ExperimentIn | None = None
    recent_funds_events: list[dict] | None = None
    payee_holder_name: str | None = None


class ExperimentSessionIn(BaseModel):
    participant_id: str
    condition: str
    session_index: int
    task_type: Literal["saved_payee", "new_typed", "new_pasted", "qr"]
    call: CallIn
    behaviour_features: BehaviourIn
    raw_events: list[dict] | None = None


class Level1Action(BaseModel):
    response_ms: int = 0


class RespondIn(BaseModel):
    who_guides: str | None = None
    guardian_confirm: bool | None = None
    hung_up: bool | None = None
    proceed: bool | None = None
    cancel: bool | None = None
    call: CallIn | None = None


class ProductIn(BaseModel):
    account_id: str
    amount: int
    device: dict | None = None


class LimitIn(BaseModel):
    account_id: str
    limit_per_txn: int
    limit_per_day: int
    device: dict | None = None


class GuardianIn(BaseModel):
    account_id: str
    guardian_phone_hash: str | None = None
    phone: str | None = None
    relation: str
    consent: bool = False


class ChoiceIn(BaseModel):
    choice: Literal["pause", "cancel", "continue", "abandoned"]
    response_ms: int
    call: CallIn | None = None


class PersonaIn(BaseModel):
    customer_id: str


app = FastAPI(title="Bank core")


@app.middleware("http")
async def require_bank_key(request: Request, call_next):
    """BANK_API_KEY đặt thì mọi lệnh ghi cần X-Bank-Key. Không đặt thì như cũ, để tắt nhanh trên sân khấu."""
    key = os.environ.get("BANK_API_KEY", "")
    if key and request.method not in {"GET", "HEAD", "OPTIONS"}:
        sent = request.headers.get("x-bank-key", "")
        if not hmac.compare_digest(sent.encode("utf-8"), key.encode("utf-8")):
            return JSONResponse(status_code=401, content={"detail": "Thiếu hoặc sai X-Bank-Key."})
    return await call_next(request)


def _persona_accounts(customer_id: str) -> set[str]:
    payload = json.loads(PERSONAS.read_text(encoding="utf-8"))
    for person in payload["personas"]:
        if person["customer_id"] == customer_id:
            return set(person["account_ids"])
    return set()


def _build_feed() -> None:
    global FEED
    start = pd.Timestamp(CUT)
    end = pd.Timestamp("2026-09-29T00:00:00+07:00")
    tx = pd.read_parquet(OBSERVED / "transactions.parquet", columns=["tx_id", "ts", "from_account", "to_account", "amount", "tx_type", "from_balance_before"])
    tx["ts"] = pd.to_datetime(tx["ts"])
    tx = tx.loc[(tx["ts"] >= start) & (tx["ts"] < end)]
    rows = []
    for record in tx.itertuples(index=False):
        stamp = pd.Timestamp(record.ts).to_pydatetime()
        sender = str(record.from_account)
        rows.append(
            (
                stamp,
                sender,
                {
                    "event_id": f"txn:{record.tx_id}",
                    "type": "txn",
                    "ts": stamp.isoformat(),
                    "account_hash": account_hash(sender),
                    "counterparty_hash": account_hash(str(record.to_account)) if pd.notna(record.to_account) else None,
                    "tx_type": str(record.tx_type),
                    "amount": int(record.amount),
                    "balance": int(record.from_balance_before or 0),
                },
            )
        )
    rows.sort(key=lambda item: item[0])
    FEED = rows


def _play() -> None:
    global FEED_CURSOR
    while True:
        if CLOCK.paused or not CLOCK.feed or FEED_CURSOR >= len(FEED):
            threading.Event().wait(0.2)
            continue
        stamp, sender, event = FEED[FEED_CURSOR]
        if CLOCK.now() < stamp:
            threading.Event().wait(0.05)
            continue
        FEED_CURSOR += 1
        if sender in SKIP:
            continue
        try:
            post_ledger(event)
        except Exception:
            continue


def _fund_channel(value) -> str:
    text = str(value or "").strip().lower()
    if text in {"app", "branch"}:
        return text
    return "unknown"


def ensure_fund_channel(conn) -> None:
    conn.execute("ALTER TABLE bank.products ADD COLUMN IF NOT EXISTS channel text")
    conn.execute("ALTER TABLE bank.entries ADD COLUMN IF NOT EXISTS channel text")


BANK_PREFIX = "1903"


def display_digits(account_id: str) -> str:
    """Số hiển thị 10 chữ số. Không đệm bằng số 0: giữ hậu tố và gắn tiền tố ngân hàng.

    HMAC băm cả mã nội bộ (account_hash), không băm số hiển thị và không cắt hậu tố.
    """
    mapped = DEMO_NUMBERS.get(account_id)
    raw = mapped if mapped is not None else "".join(char for char in account_id if char.isdigit())
    if not raw:
        return ""
    if mapped or len(raw) >= 10:
        return raw[-10:]
    return f"{BANK_PREFIX}{raw[-6:].zfill(6)}"


def seed_demo_payees(conn) -> None:
    """Tên cho số tài khoản chỉ xuất hiện trong demo. Không đè khách có trong sổ mô phỏng."""
    for account_id, name in DEMO_PAYEES.items():
        shown = display_digits(account_id)
        if len(shown) != 10 or not shown.isdigit():
            raise RuntimeError(f"số demo không đủ 10 chữ số: {account_id}")
        conn.execute(
            """
            INSERT INTO bank.accounts
            (id, customer_id, holder_name, segment, balance, status, has_guardian, account_type, bank_id, limit_per_txn, limit_per_day)
            VALUES (%s, NULL, %s, 'thường', 0, 'open', false, 'personal', 'B01', 0, 0)
            ON CONFLICT (id) DO UPDATE SET holder_name = EXCLUDED.holder_name
            WHERE bank.accounts.customer_id IS NULL
            """,
            (account_id, name),
        )


def _varied_stamp(key: str, funds: bool) -> datetime:
    """Giờ khác nhau trên các ngày trước 20/09. Khoản tiền vào thì trước cửa sổ 72 giờ."""
    import hashlib

    digest = int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16)
    day = 15 + (digest % 2) if funds else 17 + (digest % 3)
    return datetime(2026, 9, day, 7 + (digest % 12), (digest // 7) % 60, (digest // 13) % 60, tzinfo=ICT)


def spread_frozen_stamps(conn) -> None:
    """Dòng demo từng đóng cùng một mốc được trải ra các ngày trước, để sổ không còn một giờ."""
    epoch = datetime(2026, 9, 20, tzinfo=ICT)
    frozen = (epoch, RESET_AT)
    funds = set(FUNDS_KINDS)
    for table, column, key in (
        ("bank.entries", "ts", "tx_id"),
        ("bank.transfers", "created_at", "id"),
        ("bank.products", "ts", "id"),
    ):
        rows = conn.execute(
            f"SELECT {key} AS key, {column} AS ts FROM {table} WHERE {column} = %s OR {column} = %s",
            frozen,
        ).fetchall()
        for row in rows:
            if table == "bank.products" and row["key"] == BRANCH_CLOSURE_ID:
                continue
            kind = ""
            if table == "bank.products":
                kind = conn.execute("SELECT kind FROM bank.products WHERE id = %s", (row["key"],)).fetchone()["kind"]
            elif table == "bank.entries":
                kind = conn.execute("SELECT tx_type FROM bank.entries WHERE tx_id = %s LIMIT 1", (row["key"],)).fetchone()["tx_type"]
            stamp = _varied_stamp(str(row["key"]), kind in funds)
            conn.execute(f"UPDATE {table} SET {column} = %s WHERE {key} = %s AND ({column} = %s OR {column} = %s)", (stamp, row["key"], epoch, RESET_AT))


def backfill_counterparties(conn) -> None:
    """Gắn số tài khoản bên kia vào sổ, để lịch sử hiện tên thay vì mã giao dịch."""
    conn.execute("ALTER TABLE bank.entries ADD COLUMN IF NOT EXISTS counterparty_id text")
    conn.execute("CREATE TABLE IF NOT EXISTS bank.meta (key text PRIMARY KEY, value text)")
    conn.execute(
        """
        UPDATE bank.entries e
        SET counterparty_id = CASE
            WHEN e.direction = 'out' THEN NULLIF(t.to_account, '')
            ELSE NULLIF(t.from_account, '')
        END
        FROM bank.transfers t
        WHERE t.id = e.tx_id AND (e.counterparty_id IS NULL OR e.counterparty_id = '')
        """
    )
    from load import OBSERVED

    path = OBSERVED / "transactions.parquet"
    if not path.exists():
        return
    wanted = {
        row["tx_id"]
        for row in conn.execute(
            """
            SELECT DISTINCT tx_id FROM bank.entries
            WHERE (counterparty_id IS NULL OR counterparty_id = '')
              AND tx_type IN ('transfer', 'own_transfer', 'own_transfer_drain', 'passthrough_in', 'passthrough_out')
            """
        ).fetchall()
    }
    if not wanted:
        conn.execute("INSERT INTO bank.meta (key, value) VALUES ('parties_v1', '1') ON CONFLICT (key) DO NOTHING")
        return
    frame = pd.read_parquet(path, columns=["tx_id", "from_account", "to_account"])
    frame["tx_id"] = frame["tx_id"].astype(str)
    frame = frame.loc[frame["tx_id"].isin(wanted)]
    pairs = [
        (str(row.to_account), str(row.from_account), str(row.tx_id))
        for row in frame.itertuples(index=False)
        if str(row.to_account) not in {"", "nan", "None"}
    ]
    if pairs:
        conn.execute("CREATE TEMP TABLE party_fill (to_account text, from_account text, tx_id text) ON COMMIT DROP")
        with conn.cursor() as cur:
            with cur.copy("COPY party_fill (to_account, from_account, tx_id) FROM STDIN") as stream:
                for row in pairs:
                    stream.write_row(row)
        conn.execute(
            """
            UPDATE bank.entries e
            SET counterparty_id = CASE WHEN e.direction = 'out' THEN p.to_account ELSE p.from_account END
            FROM party_fill p
            WHERE e.tx_id = p.tx_id AND (e.counterparty_id IS NULL OR e.counterparty_id = '')
            """
        )
    conn.execute("INSERT INTO bank.meta (key, value) VALUES ('parties_v1', '1') ON CONFLICT (key) DO NOTHING")


def ensure_scene_capacity(conn) -> None:
    """Cảnh B chuyển 120 triệu. Sổ parquet để hạn mức 100 triệu."""
    conn.execute(
        """
        UPDATE bank.accounts
        SET limit_per_txn = GREATEST(limit_per_txn, 500000000),
            limit_per_day = GREATEST(limit_per_day, 5000000000)
        WHERE id = 'A0072556'
        """
    )


def seed_branch_closure(conn) -> None:
    """Một tất toán tại quầy, gắn nhãn demo. Không nằm trên tài khoản các cảnh Maestro."""
    ensure_fund_channel(conn)
    conn.execute(
        """
        INSERT INTO bank.products (id, account_id, amount, kind, ts, channel)
        VALUES (%s, 'A0119955', 1000000, 'savings_liquidation', %s, 'branch')
        ON CONFLICT (id) DO NOTHING
        """,
        (BRANCH_CLOSURE_ID, datetime.fromisoformat("2026-09-20T07:12:00+07:00")),
    )
    conn.execute(
        "UPDATE bank.products SET ts = %s WHERE id = %s",
        (datetime.fromisoformat("2026-09-20T07:12:00+07:00"), BRANCH_CLOSURE_ID),
    )


def boot() -> None:
    """Không nạp lại sổ. BANK_RESEED=1 mới nạp, và sinh reset_id mới chỉ ở phía ngân hàng."""
    global LEDGER_MISMATCH, _REPLAY_STARTED
    require_key()
    with connect() as conn:
        if os.environ.get("BANK_RESEED", "0") == "1":
            SESSIONS.clear()
            load(conn)
            remember_reset(conn, str(uuid.uuid4()))
            LEDGER_MISMATCH = True
        else:
            load_reset(conn)
        seed_branch_closure(conn)
        seed_demo_payees(conn)
        ensure_scene_capacity(conn)
        spread_frozen_stamps(conn)
        backfill_counterparties(conn)
        conn.commit()
    CLOCK.reanchor()
    if os.environ.get("DEMO_REPLAY", "1") == "1" and not _REPLAY_STARTED:
        threading.Thread(target=_build_feed, daemon=True).start()
        threading.Thread(target=_play, daemon=True).start()
        _REPLAY_STARTED = True


@app.on_event("startup")
def startup() -> None:
    boot()


@app.get("/health")
def health() -> dict:
    global LEDGER_MISMATCH
    remote = engine_reset_id()
    if remote is not None and remote != RESET_ID:
        LEDGER_MISMATCH = True
    return {"status": "ok", "service": "bank-core", "reset_id": RESET_ID, "ledger_mismatch": LEDGER_MISMATCH}


@app.get("/clock")
def clock() -> dict:
    return CLOCK.state()


@app.post("/clock/pause")
def pause() -> dict:
    CLOCK.pause()
    return CLOCK.state()


@app.post("/clock/resume")
def resume() -> dict:
    CLOCK.resume()
    return CLOCK.state()


class ClockSeek(BaseModel):
    ts: str


class ClockAdvance(BaseModel):
    seconds: float


@app.post("/clock/seek")
def seek(body: ClockSeek) -> dict:
    CLOCK.seek(datetime.fromisoformat(body.ts))
    return CLOCK.state()


@app.post("/clock/advance")
def advance(body: ClockAdvance) -> dict:
    CLOCK.advance(body.seconds)
    return CLOCK.state()


class ResetIn(BaseModel):
    reset_id: str


@app.post("/demo/reset")
def demo_reset(body: ResetIn) -> dict:
    global SKIP, FEED_CURSOR, LEDGER_MISMATCH
    CLOCK.pause()
    SESSIONS.clear()
    SKIP = set()
    FEED_CURSOR = 0
    with connect() as conn:
        _note_expired(_expire_holds(conn, CLOCK.now()))
        load(conn)
        ensure_scene_capacity(conn)
        seed_demo_payees(conn)
        remember_reset(conn, body.reset_id)
        conn.commit()
    LEDGER_MISMATCH = False
    CLOCK.reanchor()
    return {"status": "ok", "reset_id": RESET_ID, **CLOCK.state()}


class NoticeIn(BaseModel):
    demo: bool = False


@app.post("/accounts/{account_id}/call-notice")
def call_notice(account_id: str, body: NoticeIn) -> dict:
    limit, days = notice_limits()
    now = CLOCK.now()
    cutoff = now - timedelta(days=days)
    with connect() as conn:
        found = conn.execute("SELECT 1 FROM bank.accounts WHERE id = %s", (account_id,)).fetchone()
        if found is None:
            raise HTTPException(404, "không có tài khoản")
        used = int(
            conn.execute(
                "SELECT count(*) AS n FROM bank.call_notices WHERE account_id = %s AND shown_at >= %s",
                (account_id, cutoff),
            ).fetchone()["n"]
        )
        show = notice_allowed(used, limit, body.demo)
        if show and not body.demo:
            conn.execute("INSERT INTO bank.call_notices (account_id, shown_at) VALUES (%s, %s)", (account_id, now))
            conn.commit()
    return {"show": show, "used": used, "max": limit}


@app.post("/demo/persona")
def persona(body: PersonaIn) -> dict:
    global SKIP
    SKIP = _persona_accounts(body.customer_id)
    return {"customer_id": body.customer_id, "skipped_accounts": sorted(SKIP)}


def lookup_account(conn, token: str):
    """Mã nội bộ, hoặc số hiển thị 10 chữ số của người nhận demo. Không có thì None."""
    raw = token.strip()
    row = conn.execute("SELECT * FROM bank.accounts WHERE id = %s", (raw,)).fetchone()
    if row is not None:
        return row
    compact = "".join(raw.split())
    if compact != raw:
        row = conn.execute("SELECT * FROM bank.accounts WHERE id = %s", (compact,)).fetchone()
        if row is not None:
            return row
    digits = "".join(char for char in raw if char.isdigit())
    account_id = next((key for key, shown in DEMO_NUMBERS.items() if shown == digits), None)
    if account_id is None:
        return None
    return conn.execute("SELECT * FROM bank.accounts WHERE id = %s", (account_id,)).fetchone()


@app.get("/accounts/{account_id}")
def get_account(account_id: str) -> dict:
    expired: list[str] = []
    with connect() as conn:
        row = lookup_account(conn, account_id)
        if row is not None:
            expired = _expire_holds(conn, CLOCK.now(), row["id"])
            if expired:
                conn.commit()
                row = lookup_account(conn, account_id)
    _note_expired(expired)
    if row is None:
        raise HTTPException(404, "không có tài khoản")
    return {
        "id": row["id"],
        "customer_id": row["customer_id"],
        "holder_name": row["holder_name"],
        "segment": row["segment"] if row["segment"] in {"thường", "cao tuổi", "doanh nghiệp nhỏ"} else "thường",
        "balance": int(row["balance"]),
        "status": row["status"] if row["status"] in {"open", "frozen", "closed"} else "open",
        "has_guardian": bool(row["has_guardian"]),
        "account_type": row["account_type"] if row["account_type"] in {"personal", "savings", "business", "securities", "ewallet"} else "personal",
        "limit_per_txn": int(row["limit_per_txn"]),
        "limit_per_day": int(row["limit_per_day"]),
    }


@app.get("/accounts/{account_id}/history")
def history(account_id: str, before: str | None = None) -> dict:
    with connect() as conn:
        found = conn.execute("SELECT 1 FROM bank.accounts WHERE id = %s", (account_id,)).fetchone()
        if found is None:
            raise HTTPException(404, "không có tài khoản")
        expired = _expire_holds(conn, CLOCK.now(), account_id)
        if expired:
            conn.commit()
            _note_expired(expired)
        # Sau khi hết hạn, để dòng hoàn tiền vừa ghi nằm trong mốc.
        cutoff = datetime.fromisoformat(before) if before else CLOCK.now()
        rows = conn.execute(
            """
            SELECT e.tx_id, e.ts, e.direction, e.amount, e.tx_type, e.purpose_text, e.status,
                   COALESCE(NULLIF(e.counterparty_id, ''), x.other_id, pair.other_id) AS counterparty_id,
                   COALESCE(NULLIF(cp.holder_name, ''), NULLIF(ben.holder_name, '')) AS counterparty_name
            FROM bank.entries e
            LEFT JOIN bank.transfers t ON t.id = e.tx_id
            LEFT JOIN LATERAL (
                SELECT CASE
                    WHEN e.direction = 'out' THEN NULLIF(t.to_account, '')
                    ELSE NULLIF(t.from_account, '')
                END AS other_id
            ) x ON true
            LEFT JOIN LATERAL (
                SELECT e2.account_id AS other_id
                FROM bank.entries e2
                WHERE e2.tx_id = e.tx_id AND e2.account_id <> e.account_id
                ORDER BY e2.id
                LIMIT 1
            ) pair ON true
            LEFT JOIN bank.accounts cp ON cp.id = COALESCE(NULLIF(e.counterparty_id, ''), x.other_id, pair.other_id)
            LEFT JOIN bank.beneficiaries ben
                ON ben.owner_account = e.account_id
               AND ben.account_id = COALESCE(NULLIF(e.counterparty_id, ''), x.other_id, pair.other_id)
            WHERE e.account_id = %s AND e.ts <= %s
            ORDER BY e.ts, e.id
            """,
            (account_id, cutoff),
        ).fetchall()
    return {
        "account_id": account_id,
        "entries": [
            {
                "tx_id": row["tx_id"],
                "ts": row["ts"].isoformat(),
                "direction": row["direction"],
                "amount": int(row["amount"]),
                "tx_type": row["tx_type"],
                "purpose_text": row["purpose_text"],
                "status": row["status"],
                "counterparty_id": row["counterparty_id"],
                "counterparty_name": row["counterparty_name"],
            }
            for row in rows
        ],
    }


@app.get("/accounts/{account_id}/beneficiaries")
def list_beneficiaries(account_id: str) -> dict:
    with connect() as conn:
        found = conn.execute("SELECT 1 FROM bank.accounts WHERE id = %s", (account_id,)).fetchone()
        if found is None:
            raise HTTPException(404, "không có tài khoản")
        rows = conn.execute(
            """
            SELECT id, account_id, holder_name, saved_at, times_paid
            FROM bank.beneficiaries WHERE owner_account = %s ORDER BY times_paid DESC, holder_name
            """,
            (account_id,),
        ).fetchall()
    return {
        "account_id": account_id,
        "beneficiaries": [
            {
                "id": row["id"],
                "account_id": row["account_id"],
                "holder_name": row["holder_name"],
                "saved_at": row["saved_at"].isoformat(),
                "times_paid": int(row["times_paid"]),
            }
            for row in rows
        ],
    }


@app.get("/accounts/{account_id}/savings")
def list_savings(account_id: str) -> dict:
    with connect() as conn:
        owner = conn.execute("SELECT customer_id FROM bank.accounts WHERE id = %s", (account_id,)).fetchone()
        if owner is None:
            raise HTTPException(404, "không có tài khoản")
        rows = conn.execute(
            """
            SELECT id, holder_name, balance
            FROM bank.accounts
            WHERE customer_id = %s AND account_type = 'savings' AND status = 'open'
            ORDER BY id
            """,
            (owner["customer_id"],),
        ).fetchall()
    return {
        "account_id": account_id,
        "books": [{"id": row["id"], "holder_name": row["holder_name"], "balance": int(row["balance"])} for row in rows],
    }


@app.get("/beneficiaries/{beneficiary_id}")
def beneficiary(beneficiary_id: str) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM bank.beneficiaries WHERE id = %s", (beneficiary_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "không có người thụ hưởng")
    return {
        "id": row["id"],
        "account_id": row["account_id"],
        "holder_name": row["holder_name"],
        "saved_at": row["saved_at"].isoformat(),
        "times_paid": int(row["times_paid"]),
    }


def _next_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


def _customer_ledger(conn, account: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT e.ts, e.amount, e.direction, e.tx_type, e.channel, e.counterparty_id,
               COALESCE(cp.holder_name, '') AS counterparty_name,
               cp.customer_id AS counterparty_customer,
               a.customer_id
        FROM bank.entries e
        JOIN bank.accounts a ON a.id = e.account_id
        LEFT JOIN bank.accounts cp ON cp.id = e.counterparty_id
        WHERE a.customer_id = (SELECT customer_id FROM bank.accounts WHERE id = %s)
          AND e.status <> 'cancelled'
        """,
        (account,),
    ).fetchall()
    found = []
    for row in rows:
        stamp = row["ts"]
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=ICT)
        found.append(
            {
                "ts": stamp,
                "amount": int(row["amount"]),
                "direction": row["direction"],
                "tx_type": row["tx_type"],
                "channel": row["channel"],
                "counterparty_id": row["counterparty_id"] or "",
                "counterparty_name": row["counterparty_name"] or "",
                "counterparty_customer": row["counterparty_customer"],
                "customer_id": row["customer_id"],
            }
        )
    return found


def ledger_funds(conn, account: str, now: datetime) -> list[dict]:
    """Sổ của bank-core. App không biết các lệnh này. Gồm sản phẩm của ngân hàng và tiền vào bất thường."""
    start = now - timedelta(hours=FUNDS_HOURS)
    rows = conn.execute(
        """
        SELECT type, ts, channel, amount FROM (
            SELECT kind AS type, ts, channel, amount FROM bank.products
            WHERE account_id = %s AND kind = ANY(%s) AND ts >= %s AND ts <= %s
            UNION ALL
            SELECT tx_type AS type, ts, channel, amount FROM bank.entries
            WHERE account_id = %s AND tx_type = ANY(%s) AND direction = 'in' AND ts >= %s AND ts <= %s
        ) events
        ORDER BY ts
        """,
        (account, list(FUNDS_KINDS), start, now, account, list(FUNDS_KINDS), start, now),
    ).fetchall()
    events: dict[tuple[str, str], dict] = {}
    for row in rows:
        stamp = row["ts"]
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=ICT)
        at = stamp.isoformat()
        kind = str(row["type"])
        channel = _fund_channel(row["channel"])
        key = (kind, at)
        current = events.get(key)
        if current is None or (current["channel"] == "unknown" and channel != "unknown"):
            events[key] = {"type": kind, "at": at, "channel": channel, "amount": int(row["amount"] or 0)}
    ledger = _customer_ledger(conn, account)
    policy = load_policy()
    return list(events.values()) + classify_inflows(ledger, now, policy)


def ledger_outflows(conn, account: str, now: datetime) -> list[dict]:
    return recent_outflows(_customer_ledger(conn, account), now, load_policy())


def verified_mule(account: str) -> list[dict]:
    if account not in DEMO_MULE_ACCOUNTS:
        return []
    return [
        {
            "signal_id": "recipient_bank_confirmed_mule",
            "status": "present",
            "source": "core_banking",
            "active": True,
        }
    ]


@app.post("/transfer")
def transfer(
    body: TransferIn,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict:
    now = CLOCK.now()
    key = (idempotency_key or "").strip() or None
    if key:
        stored, abandoned_id = _take_replay(key, now)
        if abandoned_id:
            log_choice(abandoned_id, "abandoned", 0)
        if stored is not None:
            return stored
    session = touch_session(body.from_account, body.device, now)
    with connect() as conn:
        expired = _expire_holds(conn, now, body.from_account)
        if expired:
            conn.commit()
            _note_expired(expired)
        account = load_account(conn, body.from_account)
        spent = spent_today(conn, body.from_account, now)
        reject_if_cannot_pay(account, body.amount, spent)
        transfer_id = _next_id("X")
        decision_id = f"dec-{transfer_id}"
        method = add_method_for(body.task_type, body.entry_detail, body.add_method)
        if method:
            try:
                engine_post(
                    "/events",
                    {
                        "type": "payee_add",
                        "ts": _us(now),
                        "account": account_hash(body.from_account),
                        "payee": account_hash(body.to_account),
                        "method": method,
                    },
                    timeout=DECIDE_TIMEOUT_S,
                )
            except EngineUnavailable:
                log.warning("payee_add failed")
        request = {
            "decision_id": decision_id,
            "profile": "advanced",
            "sender_hash": account_hash(body.from_account),
            "payee_hash": account_hash(body.to_account),
            "amount": body.amount,
            "balance": int(account["balance"]),
            "ts": now.isoformat(),
            "session_id": session,
            "score_request": True,
            "limit_per_txn": int(account["limit_per_txn"]),
            "limit_per_day": int(account["limit_per_day"]),
            "spent_today": spent,
        }
        if method:
            request["add_method"] = method
        if body.device is not None:
            request["device"] = body.device
        for field in ("task_type", "call", "behaviour_features", "transfer_purpose", "experiment"):
            sent = _plain(getattr(body, field))
            if sent is not None:
                request[field] = sent
        request["recent_funds_events"] = ledger_funds(conn, body.from_account, now)
        request["recent_outflows"] = ledger_outflows(conn, body.from_account, now)
        payee = conn.execute(
            "SELECT holder_name, account_type FROM bank.accounts WHERE id = %s",
            (body.to_account,),
        ).fetchone()
        if payee is not None:
            request["payee_account_type"] = payee["account_type"]
            request["payee_holder_name"] = payee["holder_name"]
        elif body.payee_holder_name:
            request["payee_holder_name"] = body.payee_holder_name
        request["guardian_consent"] = _guardian_consented(conn, body.from_account)
        mule = verified_mule(body.to_account)
        if mule:
            request["signals"] = mule
        try:
            decided = engine_post("/decide", request, timeout=DECIDE_TIMEOUT_S)
        except EngineUnavailable:
            decided = _fallback(conn, body.from_account, body.to_account, body.amount)
            decision_id = None
        unscored = bool(decided.get("unscored"))
        level = None if unscored and decided.get("level") is None else numeric_level(decided.get("level"))
        funds = decided["funds_status"]
        experiment = body.experiment
        if experiment is not None:
            record = {
                "experiment": _plain(experiment),
                "level": decided.get("level"),
                "rules_fired": list(decided.get("rules_fired") or []),
                "evidence_card": decided.get("evidence_card") or {},
            }
            log.info("experiment decision %s", json.dumps(record, ensure_ascii=False))
            funds = "released"
            decided["hold_until"] = None
        waiting = level == 1 and experiment is None
        if waiting:
            funds = "held"
            status = "awaiting_confirmation"
        else:
            debit(conn, body.from_account, body.amount, now)
            status = "done" if experiment is not None or level is None else status_of(level, funds, False)
        _ensure_intervention(conn)
        stored_flags = flags_from_decision(decided, now)
        if level == 2 and experiment is None:
            decided["hold_until"] = (now + timedelta(hours=level2_hold_hours())).isoformat()
        conn.execute(
            """
            INSERT INTO bank.transfers
            (id, from_account, to_account, amount, purpose_text, decision_id, level, funds_status, status,
             hold_until, countdown_until, gate, hung_up, posted, actions, reasons, created_at, intervention)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,false,false,%s::jsonb,%s::jsonb,%s,%s::jsonb)
            """,
            (
                transfer_id,
                body.from_account,
                body.to_account,
                body.amount,
                body.purpose_text,
                decision_id,
                "unscored" if unscored and level is None else str(level),
                funds,
                status,
                decided.get("hold_until"),
                decided.get("countdown_until"),
                "none",
                json.dumps(decided.get("actions") or []),
                json.dumps(decided.get("reasons") or []),
                now,
                json.dumps(stored_flags, ensure_ascii=False),
            ),
        )
        if not waiting:
            entry(conn, body.from_account, transfer_id, now, "out", body.amount, "transfer", body.purpose_text or "", status, body.to_account)
            stored = conn.execute("SELECT * FROM bank.transfers WHERE id = %s", (transfer_id,)).fetchone()
            if funds == "released":
                release_payee(conn, stored, now)
        if experiment is not None:
            _save_experiment_decision(conn, body, decided, now)
        guardian_offered = "guardian_confirm" in (decided.get("actions") or [])
        if level == 2 and experiment is None and guardian_offered and _guardian_consented(conn, body.from_account):
            stored = conn.execute("SELECT * FROM bank.transfers WHERE id = %s", (transfer_id,)).fetchone()
            _open_guardian_request(conn, stored)
        conn.commit()
    decision = _decision_payload(level, decided)
    if waiting:
        decision["intervention"] = "reminder"
    result = {
        "transfer_id": transfer_id,
        "status": status,
        "funds_status": funds,
        "hold_until": decided.get("hold_until"),
        "decision": decision,
    }
    if key:
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO bank.idempotency (key, transfer_id, response)
                VALUES (%s, %s, %s::jsonb)
                ON CONFLICT (key) DO NOTHING
                """,
                (key, transfer_id, json.dumps(result, ensure_ascii=False)),
            )
            conn.commit()
            prior = conn.execute("SELECT response FROM bank.idempotency WHERE key = %s", (key,)).fetchone()
        stored = prior["response"]
        return stored if isinstance(stored, dict) else json.loads(stored)
    return result


EXPIRED_DETAIL = "Lệnh đã hết hạn, vui lòng thực hiện lại"
LEVEL1_TTL = timedelta(minutes=10)


def _drop_idempotency(conn, transfer_id: str) -> None:
    conn.execute("DELETE FROM bank.idempotency WHERE transfer_id = %s", (transfer_id,))


def _mark_expired(conn, transfer: dict, now: datetime) -> str:
    """fresh, expired_now, or expired. Hết hạn không trừ tiền."""
    if transfer["status"] == "expired":
        _drop_idempotency(conn, transfer["id"])
        return "expired"
    if transfer["status"] != "awaiting_confirmation":
        return "fresh"
    created = transfer["created_at"]
    if created.tzinfo is None:
        created = created.replace(tzinfo=now.tzinfo or ICT)
    if now - created <= LEVEL1_TTL:
        return "fresh"
    conn.execute(
        """
        UPDATE bank.transfers
        SET status = 'expired', funds_status = 'cancelled'
        WHERE id = %s AND status = 'awaiting_confirmation'
        """,
        (transfer["id"],),
    )
    _drop_idempotency(conn, transfer["id"])
    return "expired_now"


def _take_replay(key: str, now: datetime) -> tuple[dict | None, str | None]:
    """Trả lệnh đã lưu, hoặc decision_id vừa hết hạn để ghi abandoned rồi tạo lệnh mới."""
    with connect() as conn:
        prior = conn.execute(
            "SELECT transfer_id, response FROM bank.idempotency WHERE key = %s",
            (key,),
        ).fetchone()
        if prior is None:
            return None, None
        row = conn.execute("SELECT * FROM bank.transfers WHERE id = %s FOR UPDATE", (prior["transfer_id"],)).fetchone()
        if row is None:
            stored = prior["response"]
            return stored if isinstance(stored, dict) else json.loads(stored), None
        state = _mark_expired(conn, row, now)
        if state == "fresh":
            stored = prior["response"]
            return stored if isinstance(stored, dict) else json.loads(stored), None
        decision_id = row["decision_id"] if state == "expired_now" else None
        conn.commit()
        return None, decision_id


def _ensure_intervention(conn) -> None:
    conn.execute("ALTER TABLE bank.transfers ADD COLUMN IF NOT EXISTS intervention jsonb")


def _load_flags(transfer) -> dict:
    if transfer is None:
        return {}
    try:
        raw = transfer["intervention"]
    except (KeyError, IndexError):
        return {}
    if not raw:
        return {}
    if isinstance(raw, str):
        return json.loads(raw)
    return dict(raw)


LEVEL2_HELD = frozenset({"needs_verification", "pending_draft"})
LEVEL3_DETAIL = "Giao dịch này do ngân hàng xem xét. Khách và người giám hộ không mở được."
NOT_HELD_DETAIL = "Lệnh không còn bị giữ."
GUARDIAN_ONLY_DETAIL = "Chỉ người giám hộ xác nhận được. Hãy gửi yêu cầu cho người giám hộ."


def _release_block(transfer: dict, now: datetime, call_state: str | None, *, guardian: bool = False) -> str | None:
    """None khi được nhả. Chỉ lệnh mức 2 còn giữ. Người giám hộ bỏ qua luật cúp máy và khoá, khách thì không."""
    if (_level_number(transfer["level"]) or 0) >= 3:
        return LEVEL3_DETAIL
    if transfer["funds_status"] != "held" or transfer["status"] not in LEVEL2_HELD:
        return NOT_HELD_DETAIL
    if guardian:
        return None
    flags = _load_flags(transfer)
    return block_proceed(flags, now, call_state, bool(flags.get("hotline_verified")))


def _close_guardian_requests(conn, transfer_id: str, status: str, funds: str) -> None:
    conn.execute(
        "UPDATE bank.guardian_requests SET status = %s, funds_status = %s WHERE transfer_id = %s AND status = 'open'",
        (status, funds, transfer_id),
    )


def _open_guardian_request(conn, transfer: dict) -> str:
    request_id = f"G-{transfer['id']}"
    conn.execute(
        """
        INSERT INTO bank.guardian_requests (id, account_id, transfer_id, level, funds_status, status)
        VALUES (%s,%s,%s,%s,%s,'open')
        ON CONFLICT (id) DO UPDATE SET status = 'open', funds_status = EXCLUDED.funds_status
        WHERE bank.guardian_requests.status <> 'confirmed'
        """,
        (request_id, transfer["from_account"], transfer["id"], str(transfer["level"]), transfer["funds_status"]),
    )
    log.info("guardian notify mock account=%s transfer=%s", transfer["from_account"], transfer["id"])
    return request_id


def _settle(conn, transfer: dict, funds: str, status: str, now: datetime) -> None:
    """Một chỗ đổi tiền và trạng thái của lệnh đang giữ. Rời trạng thái giữ thì đóng yêu cầu giám hộ."""
    apply_funds(conn, transfer, transfer["funds_status"], funds, now)
    conn.execute("UPDATE bank.transfers SET funds_status = %s, status = %s WHERE id = %s", (funds, status, transfer["id"]))
    sync_entry(conn, transfer["id"], transfer["from_account"], funds, status)
    if funds != "held":
        _close_guardian_requests(conn, transfer["id"], "confirmed" if funds == "released" else "closed", funds)


def level2_hold_hours() -> float:
    try:
        hours = float(os.environ.get("LEVEL2_HOLD_HOURS", "24"))
    except ValueError:
        return 24.0
    return hours if hours > 0 else 24.0


def expired_hold_detail() -> str:
    hours = level2_hold_hours()
    shown = int(hours) if float(hours).is_integer() else hours
    return f"Lệnh đã chờ quá {shown} giờ mà chưa ai xác minh, nên đã được huỷ và hoàn tiền."


def _expire_hold(conn, transfer: dict | None, now: datetime) -> bool:
    """Mức 2 còn giữ quá LEVEL2_HOLD_HOURS: huỷ và hoàn tiền. Không có tiến trình quét; gọi mỗi lần đọc hay ghi lệnh."""
    if transfer is None or (_level_number(transfer["level"]) or 0) != 2:
        return False
    if transfer["funds_status"] != "held" or transfer["status"] not in LEVEL2_HELD:
        return False
    created = transfer["created_at"]
    if created.tzinfo is None:
        created = created.replace(tzinfo=now.tzinfo or ICT)
    if now - created < timedelta(hours=level2_hold_hours()):
        return False
    _settle(conn, transfer, "cancelled", "cancelled", now)
    return True


def _expire_holds(conn, now: datetime, account_id: str | None = None) -> list[str]:
    """Hết hạn mọi lệnh mức 2 quá hạn, của một tài khoản hoặc tất cả. Trả decision_id để ghi engine sau commit."""
    cutoff = now - timedelta(hours=level2_hold_hours())
    rows = conn.execute(
        """
        SELECT * FROM bank.transfers
        WHERE level = '2' AND funds_status = 'held' AND status IN ('needs_verification', 'pending_draft')
          AND created_at <= %s AND (%s::text IS NULL OR from_account = %s::text)
        FOR UPDATE
        """,
        (cutoff, account_id, account_id),
    ).fetchall()
    expired = []
    for row in rows:
        if _expire_hold(conn, row, now):
            expired.append(row["decision_id"])
    return expired


def _note_expired(decision_ids: list[str]) -> None:
    for decision_id in decision_ids:
        log_choice(decision_id, "expired", 0)


def _engine_note(path: str, body: dict) -> None:
    """Engine chỉ ghi sổ phản hồi. Tiền do ngân hàng quyết."""
    try:
        engine_post(path, body)
    except EngineUnavailable as exc:
        log.warning("engine note failed: %s", exc)
    except HTTPException as exc:
        log.warning("engine note failed: %s", exc.detail)


def log_choice(decision_id: str | None, choice: str, response_ms: int) -> None:
    if not decision_id:
        return
    try:
        engine_post(
            f"/decisions/{decision_id}/choice",
            {"choice": choice, "response_ms": max(0, int(response_ms))},
        )
    except EngineUnavailable as exc:
        log.warning("choice not logged: %s", exc)
    except HTTPException as exc:
        if exc.status_code != 409:
            log.warning("choice not logged: %s", exc.detail)


def _level1_decision(transfer: dict) -> dict:
    reasons = transfer["reasons"] if isinstance(transfer["reasons"], list) else json.loads(transfer["reasons"] or "[]")
    actions = transfer["actions"] if isinstance(transfer["actions"], list) else json.loads(transfer["actions"] or "[]")
    return {
        "level": 1,
        "actions": actions,
        "reasons": reasons,
        "signals_present": [],
        "rules_fired": [],
        "evidence_card": {"signals": [], "reasons_vi": [], "baseline_quality": "none", "episode_id": ""},
        "intervention": "reminder",
    }


def _settle_level1(conn, transfer: dict, now: datetime) -> None:
    debit(conn, transfer["from_account"], int(transfer["amount"]), now)
    entry(
        conn,
        transfer["from_account"],
        transfer["id"],
        now,
        "out",
        int(transfer["amount"]),
        "transfer",
        transfer["purpose_text"] or "",
        "done",
        transfer["to_account"],
    )
    conn.execute(
        "UPDATE bank.transfers SET funds_status = 'released', status = 'done' WHERE id = %s",
        (transfer["id"],),
    )
    stored = conn.execute("SELECT * FROM bank.transfers WHERE id = %s", (transfer["id"],)).fetchone()
    release_payee(conn, stored, now)


@app.post("/transfers/{transfer_id}/confirm")
def confirm_level1(transfer_id: str, body: Level1Action | None = None) -> dict:
    """Mức 1: trừ tiền và hoàn tất. Gọi lại trả cùng kết quả, không trừ lần hai."""
    now = CLOCK.now()
    response_ms = 0 if body is None else body.response_ms
    if response_ms < 0:
        raise HTTPException(400, "response_ms không hợp lệ")
    abandoned = False
    with connect() as conn:
        transfer = conn.execute("SELECT * FROM bank.transfers WHERE id = %s FOR UPDATE", (transfer_id,)).fetchone()
        if transfer is None:
            raise HTTPException(404, "không có lệnh")
        if transfer["status"] == "done" and _level_number(transfer["level"]) == 1:
            conn.commit()
            return {
                "transfer_id": transfer_id,
                "status": "done",
                "funds_status": "released",
                "hold_until": None,
                "decision": _level1_decision(transfer),
            }
        state = _mark_expired(conn, transfer, now)
        if state != "fresh":
            abandoned = state == "expired_now"
            conn.commit()
        elif transfer["status"] != "awaiting_confirmation":
            raise HTTPException(409, "chỉ lệnh mức 1 đang chờ mới xác nhận được")
        else:
            _settle_level1(conn, transfer, now)
            conn.commit()
            log_choice(transfer["decision_id"], "continue", response_ms)
            return {
                "transfer_id": transfer_id,
                "status": "done",
                "funds_status": "released",
                "hold_until": None,
                "decision": _level1_decision(transfer),
            }
    if abandoned:
        log_choice(transfer["decision_id"], "abandoned", response_ms)
    raise HTTPException(409, EXPIRED_DETAIL)


@app.post("/transfers/{transfer_id}/cancel")
def cancel_level1(transfer_id: str, body: Level1Action | None = None) -> dict:
    """Mức 1: bỏ lệnh. Chưa trừ tiền."""
    response_ms = 0 if body is None else body.response_ms
    if response_ms < 0:
        raise HTTPException(400, "response_ms không hợp lệ")
    now = CLOCK.now()
    abandoned = False
    with connect() as conn:
        transfer = conn.execute("SELECT * FROM bank.transfers WHERE id = %s FOR UPDATE", (transfer_id,)).fetchone()
        if transfer is None:
            raise HTTPException(404, "không có lệnh")
        state = _mark_expired(conn, transfer, now)
        if state != "fresh":
            abandoned = state == "expired_now"
            conn.commit()
        elif transfer["status"] == "cancelled" and _level_number(transfer["level"]) == 1:
            _drop_idempotency(conn, transfer_id)
            conn.commit()
            return {"transfer_id": transfer_id, "status": "cancelled", "funds_status": "cancelled"}
        elif transfer["status"] != "awaiting_confirmation":
            raise HTTPException(409, "chỉ lệnh mức 1 đang chờ mới huỷ được")
        else:
            conn.execute(
                "UPDATE bank.transfers SET funds_status = 'cancelled', status = 'cancelled' WHERE id = %s",
                (transfer_id,),
            )
            _drop_idempotency(conn, transfer_id)
            conn.commit()
            log_choice(transfer["decision_id"], "cancel", response_ms)
            return {"transfer_id": transfer_id, "status": "cancelled", "funds_status": "cancelled"}
    if abandoned:
        log_choice(transfer["decision_id"], "abandoned", response_ms)
    return {"transfer_id": transfer_id, "status": "expired", "funds_status": "cancelled"}


def _decision_payload(level: int | None, decided: dict) -> dict:
    unscored = bool(decided.get("unscored"))
    shown = None if unscored and level is None else level if level in {0, 1, 2, 3} else 0
    intervention = decided.get("intervention") or (
        "none" if shown is None else {0: "none", 1: "banner", 2: "three_button", 3: "security_workflow"}[shown]
    )
    card = decided.get("evidence_card") or {"signals": [], "reasons_vi": [], "baseline_quality": "none", "episode_id": ""}
    return {
        "level": shown,
        "actions": decided.get("actions") or [],
        "reasons": decided.get("reasons") or [],
        "signals_present": list(decided.get("signals_present") or []),
        "rules_fired": list(decided.get("rules_fired") or []),
        "evidence_card": card,
        "intervention": intervention,
        "groups_fired": list(decided.get("groups_fired") or []),
        "strengthened": bool(decided.get("strengthened")),
        "continue_requires_hangup": bool(decided.get("continue_requires_hangup")),
        "lock_minutes": int(decided.get("lock_minutes") or 0),
        "lock_until": decided.get("lock_until"),
        "headline": decided.get("headline") or "",
        "unscored": unscored,
    }


def _save_experiment_decision(conn, body: TransferIn, decided: dict, now: datetime) -> None:
    experiment = body.experiment
    if experiment is None:
        return
    _ensure_experiment_column(conn)
    stored = {
        "level": decided.get("level"),
        "rules_fired": list(decided.get("rules_fired") or []),
        "evidence_card": decided.get("evidence_card") or {},
        "experiment": _plain(experiment),
    }
    payload = json.dumps(hash_accounts(stored), ensure_ascii=False)
    found = conn.execute(
        """
        UPDATE bank.experiment_sessions
        SET decision = %s::jsonb
        WHERE participant_id = %s AND condition = %s AND session_index = %s
        RETURNING id
        """,
        (payload, experiment.participant_id, experiment.condition, experiment.session_index),
    ).fetchone()
    if found is not None:
        return
    call = _plain(body.call) or {"state": "unknown", "observability": "unavailable", "transport": "unknown"}
    features = _plain(body.behaviour_features) or {}
    conn.execute(
        """
        INSERT INTO bank.experiment_sessions
        (participant_id, condition, session_index, task_type, call, behaviour_features, raw_events, created_at, decision)
        VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, NULL, %s, %s::jsonb)
        """,
        (
            experiment.participant_id,
            experiment.condition,
            experiment.session_index,
            body.task_type or "new_typed",
            json.dumps(hash_accounts(call)),
            json.dumps(hash_accounts(features)),
            now,
            payload,
        ),
    )


@app.post("/experiment/sessions")
def store_experiment_session(body: ExperimentSessionIn) -> dict:
    now = CLOCK.now()
    raw = hash_accounts(body.raw_events) if body.raw_events is not None else None
    call = json.dumps(hash_accounts(body.call.model_dump()))
    features = json.dumps(hash_accounts(body.behaviour_features.model_dump(exclude_none=True)))
    with connect() as conn:
        conn.execute(SCHEMA)
        _ensure_experiment_column(conn)
        found = conn.execute(
            """
            SELECT id FROM bank.experiment_sessions
            WHERE participant_id = %s AND condition = %s AND session_index = %s
            """,
            (body.participant_id, body.condition, body.session_index),
        ).fetchone()
        if found is None:
            conn.execute(
                """
                INSERT INTO bank.experiment_sessions
                (participant_id, condition, session_index, task_type, call, behaviour_features, raw_events, created_at)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s)
                """,
                (
                    body.participant_id,
                    body.condition,
                    body.session_index,
                    body.task_type,
                    call,
                    features,
                    None if raw is None else json.dumps(raw),
                    now,
                ),
            )
        else:
            conn.execute(
                """
                UPDATE bank.experiment_sessions
                SET task_type = %s, call = %s::jsonb, behaviour_features = %s::jsonb, raw_events = %s::jsonb
                WHERE id = %s
                """,
                (body.task_type, call, features, None if raw is None else json.dumps(raw), found["id"]),
            )
        conn.commit()
    return {"stored": True}


@app.post("/transfer/{transfer_id}/hotline")
def verify_hotline(transfer_id: str) -> dict:
    """Tổng đài đã gọi lại đúng số và xác nhận lệnh. Demo cũng gọi đường này."""
    with connect() as conn:
        _ensure_intervention(conn)
        transfer = conn.execute("SELECT * FROM bank.transfers WHERE id = %s FOR UPDATE", (transfer_id,)).fetchone()
        if transfer is None:
            raise HTTPException(404, "không có lệnh")
        if _expire_hold(conn, transfer, CLOCK.now()):
            conn.commit()
            _note_expired([transfer["decision_id"]])
            raise HTTPException(409, expired_hold_detail())
        flags = _load_flags(transfer)
        flags["hotline_verified"] = True
        conn.execute(
            "UPDATE bank.transfers SET intervention = %s::jsonb WHERE id = %s",
            (json.dumps(flags, ensure_ascii=False), transfer_id),
        )
        conn.commit()
    log_choice(transfer["decision_id"], "hotline", 0)
    return {"transfer_id": transfer_id, "decision_id": transfer["decision_id"], "unlocked": True}


def _story_cancel(transfer_id: str, choice: str, message: str, *, guardian: bool = False) -> dict:
    """Huỷ và hoàn tiền. Không đụng pol:v24, nên episode đang mở vẫn mở."""
    now = CLOCK.now()
    with connect() as conn:
        _ensure_intervention(conn)
        transfer = conn.execute("SELECT * FROM bank.transfers WHERE id = %s FOR UPDATE", (transfer_id,)).fetchone()
        if transfer is None:
            raise HTTPException(404, "không có lệnh")
        if _expire_hold(conn, transfer, CLOCK.now()):
            conn.commit()
            _note_expired([transfer["decision_id"]])
            raise HTTPException(409, expired_hold_detail())
        if transfer["status"] in {"awaiting_confirmation", "expired"}:
            # Mức 1 chưa trừ tiền.
            conn.execute(
                "UPDATE bank.transfers SET funds_status = 'cancelled', status = 'cancelled' WHERE id = %s",
                (transfer_id,),
            )
            _close_guardian_requests(conn, transfer_id, "closed", "cancelled")
        elif transfer["status"] != "cancelled":
            if guardian and (_level_number(transfer["level"]) or 0) >= 3:
                raise HTTPException(409, LEVEL3_DETAIL)
            _settle(conn, transfer, "cancelled", "cancelled", now)
        conn.commit()
        decision_id = transfer["decision_id"]
    log_choice(decision_id, choice, 0)
    if decision_id:
        _engine_note("/respond", {"decision_id": decision_id, "cancel": True, "ts": now.isoformat()})
    return {"transfer_id": transfer_id, "status": "cancelled", "funds_status": "cancelled", "message": message}


@app.post("/transfer/{transfer_id}/hotline-fraud")
def confirm_fraud(transfer_id: str) -> dict:
    """Demo: tổng đài xác nhận đây là lừa đảo."""
    return _story_cancel(transfer_id, "hotline_fraud", FRAUD_CONFIRMED)


@app.post("/transfer/{transfer_id}/guardian-decline")
def decline_guardian(transfer_id: str) -> dict:
    """Demo: người giám hộ từ chối."""
    return _story_cancel(transfer_id, "guardian_decline", GUARDIAN_DECLINED, guardian=True)


GUARDIAN_SENT = "Đã gửi yêu cầu cho người giám hộ."


@app.post("/transfer/{transfer_id}/guardian-request")
def send_guardian_request(transfer_id: str) -> dict:
    """Nút của khách: gửi hoặc gửi lại yêu cầu cho người giám hộ. Không bao giờ nhả tiền."""
    with connect() as conn:
        transfer = conn.execute("SELECT * FROM bank.transfers WHERE id = %s FOR UPDATE", (transfer_id,)).fetchone()
        if transfer is None:
            raise HTTPException(404, "không có lệnh")
        if _expire_hold(conn, transfer, CLOCK.now()):
            conn.commit()
            _note_expired([transfer["decision_id"]])
            raise HTTPException(409, expired_hold_detail())
        if (_level_number(transfer["level"]) or 0) >= 3:
            raise HTTPException(409, LEVEL3_DETAIL)
        if transfer["funds_status"] != "held" or transfer["status"] not in LEVEL2_HELD:
            raise HTTPException(409, NOT_HELD_DETAIL)
        refusal = _guardian_refusal(conn, transfer["from_account"], CLOCK.now())
        if refusal:
            raise HTTPException(409, refusal)
        request_id = _open_guardian_request(conn, transfer)
        conn.commit()
    log_choice(transfer["decision_id"], "guardian_request", 0)
    return {"transfer_id": transfer_id, "request_id": request_id, "status": "sent", "message": GUARDIAN_SENT}


@app.post("/transfer/{transfer_id}/respond")
def respond(transfer_id: str, body: RespondIn) -> dict:
    """Khách chỉ được huỷ, báo đã cúp máy, hoặc tiếp tục khi luật cho phép. Mỗi lần đúng một việc."""
    now = CLOCK.now()
    if body.guardian_confirm:
        raise HTTPException(409, GUARDIAN_ONLY_DETAIL)
    if body.who_guides is not None:
        raise HTTPException(409, "Câu hỏi ai đang hướng dẫn không còn được dùng.")
    chosen = [name for name in ("cancel", "proceed", "hung_up") if getattr(body, name)]
    if len(chosen) != 1:
        raise HTTPException(400, "Gửi đúng một trong cancel, proceed hoặc hung_up.")
    action = chosen[0]
    rejected = None
    with connect() as conn:
        _ensure_intervention(conn)
        transfer = conn.execute("SELECT * FROM bank.transfers WHERE id = %s FOR UPDATE", (transfer_id,)).fetchone()
        if transfer is None:
            raise HTTPException(404, "không có lệnh")
        if _expire_hold(conn, transfer, CLOCK.now()):
            conn.commit()
            _note_expired([transfer["decision_id"]])
            raise HTTPException(409, expired_hold_detail())
        decision_id = transfer["decision_id"]
        if (_level_number(transfer["level"]) or 0) >= 3:
            raise HTTPException(409, LEVEL3_DETAIL)
        if action == "proceed":
            call_state = body.call.state if body.call is not None else None
            rejected = _release_block(transfer, now, call_state)
            if rejected is None:
                _settle(conn, transfer, "released", "released", now)
        elif action == "cancel":
            if transfer["funds_status"] != "held" or transfer["status"] not in LEVEL2_HELD:
                raise HTTPException(409, NOT_HELD_DETAIL)
            _settle(conn, transfer, "cancelled", "cancelled", now)
        else:
            conn.execute("UPDATE bank.transfers SET hung_up = true WHERE id = %s", (transfer_id,))
        conn.commit()
        updated = conn.execute("SELECT * FROM bank.transfers WHERE id = %s", (transfer_id,)).fetchone()
    if rejected is not None:
        log_choice(decision_id, rejection_choice(rejected) if rejected in {HANGUP_MESSAGE, LOCK_MESSAGE} else "proceed_rejected_state", 0)
        raise HTTPException(409, rejected)
    if action == "cancel":
        log_choice(decision_id, "cancel", 0)
        if decision_id:
            _engine_note("/respond", {"decision_id": decision_id, "cancel": True, "ts": now.isoformat()})
    elif action == "proceed":
        log_choice(decision_id, "proceed", 0)
    return {
        "transfer_id": transfer_id,
        "status": updated["status"],
        "level": _level_number(updated["level"]),
        "funds_status": updated["funds_status"],
        "gate": updated["gate"],
        "hold_until": updated["hold_until"].isoformat() if updated["hold_until"] else None,
        "countdown_until": updated["countdown_until"].isoformat() if updated["countdown_until"] else None,
    }


def _product(body: ProductIn, kind: str, tx_type: str) -> dict:
    """Một lệnh tất toán cho cùng tài khoản, loại và số tiền. Lần gọi sau trả về dòng đã có."""
    now = CLOCK.now()
    touch_session(body.account_id, body.device, now)
    fresh = False
    with connect() as conn:
        found = conn.execute(
            """
            SELECT tx_id FROM bank.entries
            WHERE account_id = %s AND tx_type = %s AND direction = 'in' AND amount = %s AND left(tx_id, 2) = 'P-'
            ORDER BY ts DESC
            LIMIT 1
            """,
            (body.account_id, tx_type, body.amount),
        ).fetchone()
        if found:
            product_id = found["tx_id"]
        else:
            fresh = True
            product_id = f"P-{uuid.uuid4().hex[:16]}"
            credit(conn, body.account_id, body.amount)
            entry(conn, body.account_id, product_id, now, "in", body.amount, tx_type, kind, "done")
            conn.execute(
                "INSERT INTO bank.products (id, account_id, amount, kind, ts, channel) VALUES (%s,%s,%s,%s,%s,'app')",
                (product_id, body.account_id, body.amount, kind, now),
            )
            conn.commit()
    if fresh:
        post_ledger(
            {
                "event_id": f"product:{product_id}",
                "type": "product",
                "ts": now.isoformat(),
                "account_hash": account_hash(body.account_id),
                "product_type": tx_type,
                "tx_type": tx_type,
                "amount": body.amount,
                "session_id": f"demo-{body.account_id}",
            }
        )
    return {"id": product_id, "status": "done"}


def _savings_book(conn, checking_id: str):
    """Sổ tiết kiệm đang mở của cùng khách. Không có sổ thì tất toán chỉ ghi có, như các bài test."""
    return conn.execute(
        """
        SELECT s.id, s.balance
        FROM bank.accounts s
        JOIN bank.accounts c ON c.customer_id = s.customer_id
        WHERE c.id = %s
          AND s.id <> c.id
          AND s.account_type = 'savings'
          AND s.status = 'open'
          AND s.balance > 0
        ORDER BY s.balance DESC
        LIMIT 1
        """,
        (checking_id,),
    ).fetchone()


@app.post("/savings/liquidate")
def liquidate(body: ProductIn) -> dict:
    """Tất toán một lần: trừ sổ, ghi có đúng một dòng vào tài khoản thanh toán, báo engine.

    Lần gọi sau cùng tài khoản, loại và số tiền trả về dòng đã có, không cộng thêm.
    """
    now = CLOCK.now()
    touch_session(body.account_id, body.device, now)
    fresh = False
    with connect() as conn:
        found = conn.execute(
            """
            SELECT tx_id FROM bank.entries
            WHERE account_id = %s AND tx_type = 'savings_liquidation' AND direction = 'in'
              AND amount = %s AND left(tx_id, 2) = 'P-'
            ORDER BY ts DESC
            LIMIT 1
            """,
            (body.account_id, body.amount),
        ).fetchone()
        if found:
            product_id = found["tx_id"]
        else:
            book = _savings_book(conn, body.account_id)
            if book is not None and int(book["balance"]) < body.amount:
                raise HTTPException(400, "không đủ số dư")
            fresh = True
            product_id = f"P-{uuid.uuid4().hex[:16]}"
            if book is not None:
                updated = conn.execute(
                    """
                    UPDATE bank.accounts
                    SET balance = balance - %s
                    WHERE id = %s AND status = 'open' AND balance >= %s
                    RETURNING balance
                    """,
                    (body.amount, book["id"], body.amount),
                ).fetchone()
                if updated is None:
                    raise HTTPException(400, "không đủ số dư")
                if int(updated["balance"]) == 0:
                    conn.execute("UPDATE bank.accounts SET status = 'closed' WHERE id = %s", (book["id"],))
                entry(conn, book["id"], product_id, now, "out", body.amount, "savings_liquidation", "savings_liquidation", "done")
            credit(conn, body.account_id, body.amount)
            entry(conn, body.account_id, product_id, now, "in", body.amount, "savings_liquidation", "savings_liquidation", "done")
            conn.execute(
                "INSERT INTO bank.products (id, account_id, amount, kind, ts, channel) VALUES (%s,%s,%s,'savings_liquidation',%s,'app')",
                (product_id, body.account_id, body.amount, now),
            )
            conn.commit()
    if fresh:
        post_ledger(
            {
                "event_id": f"product:{product_id}",
                "type": "product",
                "ts": now.isoformat(),
                "account_hash": account_hash(body.account_id),
                "product_type": "savings_liquidation",
                "tx_type": "savings_liquidation",
                "amount": body.amount,
                "session_id": f"demo-{body.account_id}",
            }
        )
    return {"id": product_id, "status": "done"}


@app.post("/loan")
def loan(body: ProductIn) -> dict:
    return _product(body, "quick_loan_disbursement", "quick_loan_disbursement")


@app.post("/card/cash-advance")
def cash_advance(body: ProductIn) -> dict:
    return _product(body, "credit_card_cash_advance", "credit_card_cash_advance")


@app.post("/limit")
def limit(body: LimitIn) -> dict:
    now = CLOCK.now()
    with connect() as conn:
        row = conn.execute("UPDATE bank.accounts SET limit_per_txn=%s, limit_per_day=%s WHERE id=%s RETURNING id", (body.limit_per_txn, body.limit_per_day, body.account_id)).fetchone()
        if row is None:
            raise HTTPException(404, "không có tài khoản")
        change_id = f"L-{uuid.uuid4().hex[:16]}"
        conn.execute(
            "INSERT INTO bank.products (id, account_id, amount, kind, ts, channel) VALUES (%s,%s,%s,'limit_raise',%s,'app')",
            (change_id, body.account_id, body.limit_per_txn, now),
        )
        conn.commit()
    post_ledger(
        {
            "event_id": f"account_change:{change_id}",
            "type": "account_change",
            "ts": now.isoformat(),
            "account_hash": account_hash(body.account_id),
            "change_type": "limit_raise",
        }
    )
    return {"id": change_id, "status": "done"}


def _ensure_guardian_consent(conn) -> None:
    conn.execute("ALTER TABLE bank.guardians ADD COLUMN IF NOT EXISTS consent boolean NOT NULL DEFAULT false")


def _guardian_consented(conn, account_id: str) -> bool:
    _ensure_guardian_consent(conn)
    row = conn.execute("SELECT consent FROM bank.guardians WHERE account_id = %s", (account_id,)).fetchone()
    return bool(row and row["consent"])


NO_GUARDIAN_DETAIL = "Chưa lưu sự đồng ý của người giám hộ."


def guardian_cooling_hours() -> float:
    try:
        hours = float(os.environ.get("GUARDIAN_COOLING_HOURS", "24"))
    except ValueError:
        return 24.0
    return max(hours, 0.0)


def cooling_detail(hours: float) -> str:
    shown = int(hours) if float(hours).is_integer() else hours
    return f"Người giám hộ mới được thêm hoặc vừa đổi, chưa thể xác nhận trong {shown} giờ đầu."


def _guardian_refusal(conn, account_id: str, now: datetime) -> str | None:
    """None khi người giám hộ được xác nhận. Người mới thêm hoặc vừa đổi phải chờ GUARDIAN_COOLING_HOURS."""
    _ensure_guardian_consent(conn)
    row = conn.execute("SELECT consent, registered_at FROM bank.guardians WHERE account_id = %s", (account_id,)).fetchone()
    if not row or not row["consent"]:
        return NO_GUARDIAN_DETAIL
    hours = guardian_cooling_hours()
    registered = row["registered_at"]
    if hours > 0 and registered is not None:
        if registered.tzinfo is None:
            registered = registered.replace(tzinfo=now.tzinfo or ICT)
        if now - registered < timedelta(hours=hours):
            return cooling_detail(hours)
    return None


@app.get("/config")
def bank_config() -> dict:
    from engine.policy.v24 import load_policy

    text = str((load_policy().get("interventions") or {}).get("hotline") or "1900 54 54 13")
    return {
        "purpose_amount_vnd": PURPOSE_AMOUNT_VND,
        "hotline": text,
        "hotline_tel": "".join(ch for ch in text if ch.isdigit()),
    }


@app.post("/decisions/{decision_id}/choice")
def record_choice(decision_id: str, body: ChoiceIn) -> dict:
    now = CLOCK.now()
    if body.response_ms < 0:
        raise HTTPException(400, "response_ms không hợp lệ")
    with connect() as conn:
        _ensure_intervention(conn)
        transfer = conn.execute("SELECT * FROM bank.transfers WHERE decision_id = %s FOR UPDATE", (decision_id,)).fetchone()
        if transfer is None:
            raise HTTPException(404, "không có quyết định")
        if _expire_hold(conn, transfer, CLOCK.now()):
            conn.commit()
            _note_expired([transfer["decision_id"]])
            raise HTTPException(409, expired_hold_detail())
        state = _mark_expired(conn, transfer, now)
        if state != "fresh":
            conn.commit()
    if state != "fresh":
        if state == "expired_now":
            log_choice(transfer["decision_id"], "abandoned", body.response_ms)
        raise HTTPException(409, EXPIRED_DETAIL)
    if transfer["status"] == "awaiting_confirmation":
        raise HTTPException(409, "lệnh mức 1 đang chờ xác nhận")
    if body.choice == "abandoned":
        log_choice(decision_id, body.choice, body.response_ms)
        return {
            "decision_id": decision_id,
            "choice": body.choice,
            "logged": True,
            "status": transfer["status"],
            "funds_status": transfer["funds_status"],
        }
    if (_level_number(transfer["level"]) or 0) >= 3:
        raise HTTPException(409, LEVEL3_DETAIL)
    if body.choice == "continue":
        call_state = body.call.state if body.call is not None else None
        reason = _release_block(transfer, now, call_state)
        if reason:
            log_choice(decision_id, rejection_choice(reason) if reason in {HANGUP_MESSAGE, LOCK_MESSAGE} else "proceed_rejected_state", body.response_ms)
            raise HTTPException(409, reason)
    elif transfer["funds_status"] != "held" or transfer["status"] not in LEVEL2_HELD:
        raise HTTPException(409, NOT_HELD_DETAIL)
    try:
        engine_post(f"/decisions/{decision_id}/choice", {"choice": body.choice, "response_ms": body.response_ms})
    except EngineUnavailable as exc:
        log.warning("choice not logged: %s", exc)
    except HTTPException as exc:
        if exc.status_code == 409:
            raise
        log.warning("choice not logged: %s", exc.detail)
    with connect() as conn:
        transfer = conn.execute("SELECT * FROM bank.transfers WHERE decision_id = %s FOR UPDATE", (decision_id,)).fetchone()
        if transfer is None:
            raise HTTPException(404, "không có quyết định")
        if body.choice == "cancel":
            funds, status = "cancelled", "cancelled"
            _settle(conn, transfer, funds, status, now)
        elif body.choice == "continue":
            if _release_block(transfer, now, body.call.state if body.call is not None else None):
                raise HTTPException(409, NOT_HELD_DETAIL)
            funds, status = "released", "released"
            _settle(conn, transfer, funds, status, now)
        else:
            funds, status = transfer["funds_status"], "pending_draft"
            conn.execute("UPDATE bank.transfers SET status = %s WHERE id = %s", (status, transfer["id"]))
            sync_entry(conn, transfer["id"], transfer["from_account"], funds, status)
        conn.commit()
    if body.choice == "cancel":
        _engine_note("/respond", {"decision_id": decision_id, "cancel": True, "ts": now.isoformat()})
    return {"decision_id": decision_id, "choice": body.choice, "logged": True, "status": status, "funds_status": funds}


@app.post("/guardian")
def guardian(body: GuardianIn) -> dict:
    if body.consent is not True:
        raise HTTPException(400, "cần sự đồng ý của khách")
    phone_hash = body.guardian_phone_hash or (account_hash(body.phone.strip()) if body.phone and body.phone.strip() else None)
    if not phone_hash:
        raise HTTPException(400, "thiếu số điện thoại")
    now = CLOCK.now()
    with connect() as conn:
        found = conn.execute("SELECT 1 FROM bank.accounts WHERE id = %s", (body.account_id,)).fetchone()
        if found is None:
            raise HTTPException(404, "không có tài khoản")
        _ensure_guardian_consent(conn)
        # Đổi số, đổi quan hệ hoặc vừa đồng ý thì tính lại từ đầu thời gian chờ.
        conn.execute(
            """
            INSERT INTO bank.guardians (account_id, guardian_phone_hash, relation, registered_at, consent)
            VALUES (%s,%s,%s,%s,true)
            ON CONFLICT (account_id) DO UPDATE
            SET guardian_phone_hash = EXCLUDED.guardian_phone_hash,
                relation = EXCLUDED.relation,
                consent = true,
                registered_at = CASE
                    WHEN bank.guardians.consent
                     AND bank.guardians.guardian_phone_hash IS NOT DISTINCT FROM EXCLUDED.guardian_phone_hash
                     AND bank.guardians.relation IS NOT DISTINCT FROM EXCLUDED.relation
                    THEN bank.guardians.registered_at
                    ELSE EXCLUDED.registered_at
                END
            """,
            (body.account_id, phone_hash, body.relation, now),
        )
        conn.execute("UPDATE bank.accounts SET has_guardian = true WHERE id = %s", (body.account_id,))
        conn.commit()
    return {"account_id": body.account_id, "status": "registered"}


@app.get("/guardian/requests")
def guardian_requests() -> dict:
    with connect() as conn:
        expired = _expire_holds(conn, CLOCK.now())
        if expired:
            conn.commit()
            _note_expired(expired)
        rows = conn.execute(
            """
            SELECT r.id, r.account_id, r.transfer_id, r.level, r.funds_status,
                   t.amount, t.to_account, a.holder_name AS sender_name
            FROM bank.guardian_requests r
            LEFT JOIN bank.transfers t ON t.id = r.transfer_id
            LEFT JOIN bank.accounts a ON a.id = r.account_id
            WHERE r.status = 'open'
            ORDER BY r.id
            """
        ).fetchall()
    return {
        "requests": [
            {
                "id": row["id"],
                "account_id": row["account_id"],
                "transfer_id": row["transfer_id"],
                "level": numeric_level(row["level"]),
                "funds_status": row["funds_status"],
                "amount": None if row["amount"] is None else int(row["amount"]),
                "to_account": row["to_account"],
                "sender_name": row["sender_name"],
            }
            for row in rows
        ]
    }


@app.post("/guardian/requests/{request_id}/confirm")
def confirm_guardian(request_id: str) -> dict:
    """Đường duy nhất để người giám hộ nhả tiền: yêu cầu còn mở, lệnh mức 2 còn giữ."""
    now = CLOCK.now()
    with connect() as conn:
        _ensure_intervention(conn)
        row = conn.execute("SELECT * FROM bank.guardian_requests WHERE id = %s FOR UPDATE", (request_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "không có yêu cầu")
        if row["status"] != "open":
            raise HTTPException(409, "Yêu cầu này không còn mở.")
        transfer = conn.execute("SELECT * FROM bank.transfers WHERE id = %s FOR UPDATE", (row["transfer_id"],)).fetchone()
        if transfer is None:
            raise HTTPException(404, "không có lệnh")
        if _expire_hold(conn, transfer, CLOCK.now()):
            conn.commit()
            _note_expired([transfer["decision_id"]])
            raise HTTPException(409, expired_hold_detail())
        reason = _release_block(transfer, now, None, guardian=True) or _guardian_refusal(conn, transfer["from_account"], now)
        if reason:
            refused = reason
        else:
            refused = None
            _settle(conn, transfer, "released", "released", now)
        conn.commit()
    if refused:
        log_choice(transfer["decision_id"], "guardian_refused", 0)
        raise HTTPException(409, refused)
    log_choice(transfer["decision_id"], "guardian_confirm", 0)
    if transfer["decision_id"]:
        _engine_note("/respond", {"decision_id": transfer["decision_id"], "guardian_confirm": True, "ts": now.isoformat()})
    return {"id": request_id, "transfer_id": transfer["id"], "status": "released", "funds_status": "released"}


class ReviewIn(BaseModel):
    decision: Literal["release", "cancel"]


@app.get("/review/transfers")
def review_transfers() -> dict:
    """Lệnh mức 3 đang giữ, chờ ngân hàng xem xét."""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT t.id, t.from_account, t.to_account, t.amount, t.created_at, t.reasons, a.holder_name AS payee_name
            FROM bank.transfers t LEFT JOIN bank.accounts a ON a.id = t.to_account
            WHERE t.level = '3' AND t.funds_status = 'held' AND t.status IN ('blocked_pending_hangup', 'held')
            ORDER BY t.created_at
            """
        ).fetchall()
    return {
        "transfers": [
            {
                "transfer_id": row["id"],
                "from_account": row["from_account"],
                "to_account": row["to_account"],
                "payee_name": row["payee_name"],
                "amount": int(row["amount"]),
                "created_at": row["created_at"].isoformat(),
                "reasons": row["reasons"] if isinstance(row["reasons"], list) else json.loads(row["reasons"] or "[]"),
            }
            for row in rows
        ]
    }


@app.post("/review/transfers/{transfer_id}")
def review_transfer(transfer_id: str, body: ReviewIn) -> dict:
    """Đường duy nhất quyết lệnh mức 3: nhả cho người nhận, hoặc huỷ và hoàn tiền."""
    now = CLOCK.now()
    with connect() as conn:
        transfer = conn.execute("SELECT * FROM bank.transfers WHERE id = %s FOR UPDATE", (transfer_id,)).fetchone()
        if transfer is None:
            raise HTTPException(404, "không có lệnh")
        if (_level_number(transfer["level"]) or 0) != 3:
            raise HTTPException(409, "Chỉ lệnh mức 3 đi qua xem xét của ngân hàng.")
        if transfer["funds_status"] != "held" or transfer["status"] not in {"blocked_pending_hangup", "held"}:
            raise HTTPException(409, NOT_HELD_DETAIL)
        funds = "released" if body.decision == "release" else "cancelled"
        _settle(conn, transfer, funds, funds, now)
        conn.commit()
    log_choice(transfer["decision_id"], f"review_{body.decision}", 0)
    if funds == "cancelled" and transfer["decision_id"]:
        _engine_note("/respond", {"decision_id": transfer["decision_id"], "cancel": True, "ts": now.isoformat()})
    return {"transfer_id": transfer_id, "status": funds, "funds_status": funds}


if __name__ == "__main__":
    import uvicorn

    require_key()
    uvicorn.run(app, host="0.0.0.0", port=8080)
