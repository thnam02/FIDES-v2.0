"""Một lệnh /decide để engine đã chấm một lần, để lệnh demo đầu không rơi vào hạn 300 ms."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]

from engine.common.hashing import account_hash, reset_key_cache


def main() -> None:
    decision_id = sys.argv[1] if len(sys.argv) > 1 else "warmup-demo-reset"
    reset_key_cache()
    body = {
        "decision_id": decision_id,
        "profile": "advanced",
        "sender_hash": account_hash("A0031239"),
        "payee_hash": account_hash("warmup-payee"),
        "amount": 1,
        "ts": "2026-09-21T10:00:00+07:00",
        "session_id": decision_id,
        "device": {"state": "none"},
        "add_method": "typed",
        "task_type": "saved_payee",
    }
    request = urllib.request.Request(
        os.environ["ENGINE"].rstrip("/") + "/decide",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "X-API-Key": os.environ["API_KEY"]},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            status = response.status
            payload = response.read().decode()
    except urllib.error.HTTPError as exc:
        sys.stderr.write(exc.read().decode()[:500] + "\n")
        sys.exit(1)
    if status != 200:
        sys.stderr.write(f"warmup decide {status} {payload[:500]}\n")
        sys.exit(1)
    print("warmup decide ok")


if __name__ == "__main__":
    main()
