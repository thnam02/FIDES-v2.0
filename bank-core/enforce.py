"""Chặn Tiếp tục trên máy chủ. App không được tin."""

from __future__ import annotations

from datetime import datetime, timedelta

HANGUP_MESSAGE = "Hãy cúp máy trước khi tiếp tục."
LOCK_MESSAGE = "Chưa hết thời gian giữ để xác minh."
UNSCORED_HEADLINE = "Không kiểm tra được giao dịch lúc này. Hãy chắc chắn bạn biết người nhận trước khi chuyển."
FRAUD_CONFIRMED = "Tổng đài đã xác nhận đây là lừa đảo. Giao dịch đã được huỷ."
GUARDIAN_DECLINED = "Người giám hộ đã từ chối giao dịch này. Hãy gọi lại cho người thân của bạn."
OFF_CALL = {"none", "ended_in_session"}


def unscored_decision(established: bool) -> dict:
    """/decide không trả lời. Không bao giờ là mức 0. Người nhận đã biết thì đi tiếp, người mới thì tờ mức 1."""
    if established:
        return {
            "level": None,
            "unscored": True,
            "funds_status": "released",
            "hold_until": None,
            "countdown_until": None,
            "actions": [],
            "reasons": [],
            "signals_present": [],
            "rules_fired": [],
            "headline": "",
            "intervention": "none",
        }
    return {
        "level": 1,
        "unscored": True,
        "funds_status": "held",
        "hold_until": None,
        "countdown_until": None,
        "actions": [],
        "reasons": [{"code": "engine_unavailable", "text": UNSCORED_HEADLINE}],
        "signals_present": ["new_payee"],
        "rules_fired": [],
        "headline": UNSCORED_HEADLINE,
        "intervention": "reminder",
    }


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
        "signals_present": list(decided.get("signals_present") or []),
        "rules_fired": list(decided.get("rules_fired") or []),
        "intervention": decided.get("intervention"),
        "evidence_card": decided.get("evidence_card") or {},
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
