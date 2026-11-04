"""Tiền vào bất thường trên sổ của chính khách. Ngưỡng đọc từ bank_policy.yaml."""

from __future__ import annotations

import statistics
import unicodedata
from datetime import datetime, timedelta

P2P_TYPES = {"transfer", "passthrough_in"}
CASH_TYPES = {"cash_deposit", "cash_in"}
OWN_TYPES = {"own_transfer", "own_transfer_in"}
LENDER_TYPES = {"lender_disbursement", "external_loan"}
SALARY_TYPES = {"salary_in"}


def fold(text: str | None) -> str:
    raw = unicodedata.normalize("NFD", str(text or "").upper())
    return "".join(ch for ch in raw if unicodedata.category(ch) != "Mn")


def _hours(policy: dict) -> float:
    return float(policy["thresholds"]["funds_fresh_hours"]["value"])


def _value(policy: dict, name: str) -> float:
    return float(policy["thresholds"][name]["value"])


def _stamp(value) -> datetime:
    if isinstance(value, datetime):
        stamp = value
    else:
        stamp = datetime.fromisoformat(str(value))
    if stamp.tzinfo is None:
        raise ValueError("mốc sổ thiếu múi giờ")
    return stamp


def _marked(name: str, markers: list[str]) -> bool:
    folded = fold(name)
    return any(marker in folded for marker in markers)


def is_recurring(row: dict, earlier: list[dict], policy: dict) -> bool:
    """Lương hoặc lương hưu: cùng người gửi, cách khoảng một tháng, số tiền gần nhau."""
    if str(row.get("tx_type") or "") in SALARY_TYPES:
        return True
    sender = str(row.get("counterparty_id") or "")
    if not sender:
        return False
    within = _value(policy, "recurring_amount_within")
    month = _value(policy, "recurring_month_days")
    slack = _value(policy, "recurring_gap_slack_days")
    amount = int(row["amount"])
    at = _stamp(row["ts"])
    for prior in earlier:
        if str(prior.get("counterparty_id") or "") != sender:
            continue
        if str(prior.get("direction") or "in") != "in":
            continue
        days = (at - _stamp(prior["ts"])).total_seconds() / 86400
        if days <= 0:
            continue
        monthly = any(abs(days - month * k) <= slack for k in (1, 2, 3))
        if not monthly:
            continue
        base = int(prior["amount"])
        if base <= 0:
            continue
        if abs(amount - base) / base <= within:
            return True
    return False


def _median(values: list[int]) -> int:
    if not values:
        return 0
    return int(statistics.median(values))


def _typical_window(rows: list[dict], start: datetime, policy: dict) -> int:
    """Trung vị các khoảng 72 giờ trong inflow_history_days ngày trước cửa sổ hiện tại. Khoảng trống tính là 0."""
    horizon = start - timedelta(days=_value(policy, "inflow_history_days"))
    window = timedelta(hours=_hours(policy))
    buckets: dict[int, int] = {}
    span = -1
    for row in rows:
        at = _stamp(row["ts"])
        if at >= start or at < horizon:
            continue
        index = int((start - at).total_seconds() // window.total_seconds())
        buckets[index] = buckets.get(index, 0) + int(row["amount"])
        span = max(span, index)
    if span < 0:
        return 0
    return _median([buckets.get(index, 0) for index in range(span + 1)])


def _event(kind: str, amount: int, at: datetime, channel: str) -> dict:
    text = channel if channel in {"app", "branch"} else "app"
    if kind == "cash_deposit":
        text = "branch"
    return {"type": kind, "amount": int(amount), "at": at.isoformat(), "channel": text}


def classify_inflows(rows: list[dict], now: datetime, policy: dict) -> list[dict]:
    """Một dòng sổ là dict có ts, amount, direction, tx_type, counterparty_id, counterparty_name, counterparty_customer, customer_id, channel."""
    window_start = now - timedelta(hours=_hours(policy))
    incoming = [row for row in rows if str(row.get("direction") or "") == "in" and int(row.get("amount") or 0) > 0]
    incoming.sort(key=lambda row: _stamp(row["ts"]))
    product = set(policy.get("funds_types") or {}) - set(policy.get("inflow_kinds") or [])
    events: list[dict] = []

    def usable(row: dict) -> bool:
        kind = str(row.get("tx_type") or "")
        if kind in product:
            return False
        return _stamp(row["ts"]) <= now

    fresh = [row for row in incoming if usable(row) and _stamp(row["ts"]) >= window_start]
    history = [row for row in incoming if usable(row) and _stamp(row["ts"]) < window_start]
    p2p_fresh = []
    for row in fresh:
        if is_recurring(row, [item for item in incoming if _stamp(item["ts"]) < _stamp(row["ts"])], policy):
            continue
        kind = str(row.get("tx_type") or "")
        name = str(row.get("counterparty_name") or "")
        same_customer = row.get("counterparty_customer") and row.get("counterparty_customer") == row.get("customer_id")
        if kind in CASH_TYPES:
            prior_cash = [int(item["amount"]) for item in history if str(item.get("tx_type") or "") in CASH_TYPES]
            typical = _median(prior_cash)
            amount = int(row["amount"])
            if amount >= _value(policy, "inflow_multiple") * typical and amount >= _value(policy, "inflow_min_vnd"):
                events.append(_event("cash_deposit", amount, _stamp(row["ts"]), str(row.get("channel") or "branch")))
            continue
        if kind in OWN_TYPES and not same_customer:
            events.append(_event("own_transfer_in", int(row["amount"]), _stamp(row["ts"]), str(row.get("channel") or "app")))
            continue
        lender = kind in LENDER_TYPES or _marked(name, list(policy.get("lender_markers") or []))
        if lender and kind not in product:
            events.append(_event("lender_inflow", int(row["amount"]), _stamp(row["ts"]), str(row.get("channel") or "app")))
            continue
        if kind in P2P_TYPES:
            p2p_fresh.append(row)

    if p2p_fresh:
        total = sum(int(row["amount"]) for row in p2p_fresh)
        senders = {str(row.get("counterparty_id") or "") for row in p2p_fresh}
        known = {str(row.get("counterparty_id") or "") for row in history if str(row.get("tx_type") or "") in P2P_TYPES}
        new_sender = any(sender not in known for sender in senders)
        p2p_history = [
            row
            for row in history
            if str(row.get("tx_type") or "") in P2P_TYPES
            and not is_recurring(row, [item for item in history if _stamp(item["ts"]) < _stamp(row["ts"])], policy)
        ]
        typical = _typical_window(p2p_history, window_start, policy)
        broad = len(senders) >= 2 or new_sender
        if broad and total >= _value(policy, "inflow_multiple") * typical and total >= _value(policy, "inflow_min_vnd"):
            latest = max(_stamp(row["ts"]) for row in p2p_fresh)
            events.append(_event("p2p_inflow", total, latest, "app"))
    events.sort(key=lambda item: item["at"])
    return events


def recent_outflows(rows: list[dict], now: datetime, policy: dict) -> list[dict]:
    start = now - timedelta(hours=_hours(policy))
    found = []
    for row in rows:
        if str(row.get("direction") or "") != "out":
            continue
        at = _stamp(row["ts"])
        if start <= at <= now:
            found.append({"amount": int(row["amount"]), "at": at.isoformat()})
    return found
