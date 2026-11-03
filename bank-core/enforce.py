"""Chặn Tiếp tục trên máy chủ. App không được tin."""

from __future__ import annotations

from datetime import datetime, timedelta

HANGUP_MESSAGE = "Hãy cúp máy trước khi tiếp tục."
LOCK_MESSAGE = "Chưa hết thời gian giữ để xác minh."
OFF_CALL = {"none", "ended_in_session"}


def flags_from_decision(decided: dict, now: datetime) -> dict:
    minutes = int(decided.get("lock_minutes") or 0)
    strengthened = bool(decided.get("strengthened"))
    lock_until = decided.get("lock_until")
    if strengthened and not lock_until:
        minutes = minutes or 30
        lock_until = (now + timedelta(minutes=minutes)).isoformat()
    return {
        "groups_fired": list(decided.get("groups_fired") or []),
        "strengthened": strengthened,
        "continue_requires_hangup": bool(decided.get("continue_requires_hangup")),
        "lock_minutes": minutes,
        "lock_until": lock_until,
        "headline": str(decided.get("headline") or ""),
        "hotline_verified": False,
    }


def _stamp(value, now: datetime) -> datetime | None:
    if value is None or value == "":
        return None
    stamp = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if stamp.tzinfo is None and now.tzinfo is not None:
        stamp = stamp.replace(tzinfo=now.tzinfo)
    return stamp


def block_proceed(flags: dict, now: datetime, call_state: str | None, hotline_verified: bool) -> str | None:
    """None khi được nhả. Cúp máy chặn trước khoá. Tổng đài chỉ mở khoá, không bỏ luật cúp máy."""
    if flags.get("continue_requires_hangup") and call_state not in OFF_CALL:
        return HANGUP_MESSAGE
    if flags.get("strengthened") and not hotline_verified:
        lock_until = _stamp(flags.get("lock_until"), now)
        if lock_until is None or now < lock_until:
            return LOCK_MESSAGE
    return None


def rejection_choice(reason: str) -> str:
    if reason == HANGUP_MESSAGE:
        return "proceed_rejected_call"
    return "proceed_rejected_lock"
