"""Baseline new_typed cho Trương (cảnh 5), Huỳnh (cảnh 4) và Vũ (cảnh 3). Các khoá beh khác bị xoá, không flush."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO)]

from engine.common.hashing import account_hash, reset_key_cache

TASKS = ("saved_payee", "new_typed", "new_pasted", "qr")
KEPT_NEW_TYPED = ("A0002119", "A0072556", "A9900001")


def key_for(user: str, task: str) -> str:
    return f"beh:v24:{user}:{task}"


def quality_name(sessions: int) -> str:
    count = int(sessions)
    if count >= 8:
        return "high"
    if count >= 3:
        return "medium"
    if count > 0:
        return "low"
    return "none"

# Mọi tài khoản của năm khách demo. Chỉ ba tài khoản thanh toán được giữ baseline new_typed.
DEMO_ACCOUNTS = (
    "A0000623",
    "A0050272",
    "A0072556",
    "A0077690",
    "A0002119",
    "A0002845",
    "A0051289",
    "A0072782",
    "A0078375",
    "A0097589",
    "A0031239",
    "A9900001",
    "A9900002",
)

ICT = ZoneInfo("Asia/Ho_Chi_Minh")
ORDINARY = {
    "median_gap_ms": 831.0210845522126,
    "p90_gap_ms": 2279.7838136013606,
    "pause_to_action_ratio": 0.18471028781378585,
    "review_dwell_ms": 1473.5414940881667,
    "background_total_ms": 1814.7674765589447,
    "payee_mean_burst_len": 10.0,
    "payee_inter_burst_gap_median_ms": 1519.8558207524068,
    "payee_burst_count": 1.0,
    "burst_count": 2.0,
    "edit_count": 1.0,
    "backtrack_count": 0.0,
    "screen_revisit_count": 1.0,
    "background_count": 1.0,
    "session_duration_ms": 41829.83031086509,
}


def redis_cmd() -> list[str]:
    """Cùng Redis với demo_reset. Không có REDIS_HOST thì vào compose qua docker."""
    host = os.environ.get("REDIS_HOST", "").strip()
    if not host:
        return ["docker", "exec", "-i", "sedif-redis-1", "redis-cli", "-n", "15"]
    port = os.environ.get("REDIS_PORT", "6379")
    url = os.environ.get("REDIS_URL", "")
    db = url.rstrip("/").rsplit("/", 1)[-1] if "/" in url else "15"
    if not db.isdigit():
        db = "15"
    return ["redis-cli", "-h", host, "-p", port, "-n", db]


def redis(*args: str) -> str:
    done = subprocess.run([*redis_cmd(), *args], check=True, capture_output=True, text=True)
    return done.stdout


def seed() -> None:
    os.environ.setdefault("FIDES_HMAC_KEY", "fides-demo-hmac")
    reset_key_cache()
    start = datetime(2026, 9, 1, tzinfo=ICT)
    records = []
    for index in range(10):
        stamp = start + timedelta(days=index)
        ts = int(stamp.timestamp() * 1_000_000)
        records.append({"ts": ts, "eligible_at": ts, "features": dict(ORDINARY)})
    payload = json.dumps({"records": records}, ensure_ascii=False)
    for account in DEMO_ACCOUNTS:
        user = account_hash(account)
        for task in TASKS:
            key = key_for(user, task)
            if account in KEPT_NEW_TYPED and task == "new_typed":
                redis("SET", key, payload)
                print("kept", key, "sessions", len(records))
                continue
            redis("DEL", key)
    print("baseline", " ".join(KEPT_NEW_TYPED))


def check() -> None:
    """Ba tài khoản thanh toán cần baseline new_typed đủ medium, trước ngày demo."""
    os.environ.setdefault("FIDES_HMAC_KEY", "fides-demo-hmac")
    reset_key_cache()
    cut = int(datetime(2026, 9, 21, tzinfo=ICT).timestamp() * 1_000_000)
    for account in KEPT_NEW_TYPED:
        raw = redis("--raw", "GET", key_for(account_hash(account), "new_typed"))
        if not raw.strip():
            raise SystemExit(f"thiếu baseline new_typed của {account}")
        records = json.loads(raw).get("records") or []
        prior = [
            row
            for row in records
            if int(row.get("ts") or 0) < cut and int(row.get("eligible_at") or 0) <= cut
        ]
        quality = quality_name(len(prior))
        if len(prior) < 3 or quality not in {"medium", "high"}:
            raise SystemExit(f"{account} new_typed: {len(prior)} phiên, chất lượng {quality}")
        print(f"baseline {account} new_typed {len(prior)} {quality}")
    for account in DEMO_ACCOUNTS:
        for task in TASKS:
            if account in KEPT_NEW_TYPED and task == "new_typed":
                continue
            extra = redis("--raw", "GET", key_for(account_hash(account), task)).strip()
            if extra:
                raise SystemExit(f"baseline thừa {account} {task}")


def main() -> None:
    if "--check" in sys.argv:
        check()
        return
    seed()


if __name__ == "__main__":
    main()
