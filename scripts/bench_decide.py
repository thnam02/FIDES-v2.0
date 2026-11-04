"""1,000 sequential HTTP /decide calls on a throwaway sender namespace.

Senders and sessions are prefixed bench_. The run deletes those Redis keys
and the audit rows it inserted. It does not read or write replay accounts.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.request
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "fides"), str(REPO)]
os.environ.setdefault("FIDES_HMAC_KEY", "fides-demo-hmac")
os.environ.setdefault("FIDES_API_KEY", "fides-demo-key")
os.environ.setdefault("DATABASE_URL", "postgresql://hainamtran@localhost:5432/fides_w1")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

import redis

import engine.app as appmod
from engine.app import Handler
from engine.features.online import OnlineStore
from engine.model import Scorer

ICT = ZoneInfo("Asia/Ho_Chi_Minh")
N = 1000
PREFIX = "bench_"


def _hash_ok(value) -> bool:
    if isinstance(value, str) and value.startswith(PREFIX):
        return True
    return isinstance(value, str) and len(value) == appmod.HASH_LEN and all(ch in "0123456789abcdef" for ch in value)


def _cleanup(client: redis.Redis) -> int:
    removed = 0
    for pattern in ("pol:v24:bench_*", "beh:v24:bench_*", "f:sess:bench_*", "f:*bench_*"):
        cursor = 0
        while True:
            cursor, keys = client.scan(cursor, match=pattern, count=500)
            if keys:
                removed += int(client.delete(*keys))
            if cursor == 0:
                break
    return removed


def _drop_audit() -> None:
    from engine.audit import audit_conn

    with audit_conn() as conn:
        conn.execute("ALTER TABLE decisions DISABLE TRIGGER USER")
        try:
            conn.execute("DELETE FROM decisions WHERE decision_id LIKE 'bench-%'")
            conn.commit()
        finally:
            conn.execute("ALTER TABLE decisions ENABLE TRIGGER USER")
            conn.commit()


_ORDINARY_AMOUNTS = (156_000, 200_000, 274_000, 300_000, 354_000, 500_000, 220_000, 410_000, 180_000, 994_000)


def _seed_history(client, when: datetime) -> None:
    """20 lệnh đi với số tiền và giờ khác nhau. 950 lệnh đo nằm trong mức đó, 50 lệnh vượt xa mức lớn nhất."""
    pipe = client.pipeline(transaction=False)
    clock = when.replace(minute=0, second=0, microsecond=0)
    for index in range(N):
        sender = f"bench_{index:04d}"
        for step in range(20):
            hour = clock.hour if step % 2 == 0 else (9 + step % 4) % 24
            stamp = (clock - timedelta(days=40 - step)).replace(hour=hour)
            ts = int(stamp.timestamp() * 1_000_000)
            payee = "bench_known" if step % 3 else f"bench_new_{step}"
            amount = _ORDINARY_AMOUNTS[step % len(_ORDINARY_AMOUNTS)]
            member = f"{ts}|{step}|{payee}|{amount}|{20_000_000}|1|bench_old|transfer"
            pipe.zadd(f"f:out:{sender}", {member: ts})
    pipe.execute()


def main() -> None:
    appmod._hash_ok = _hash_ok
    client = redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    # Đừng để lần ghi bench đè dump.rdb của snapshot demo.
    saved = client.config_get("save").get("save", "")
    client.config_set("save", "")
    _cleanup(client)
    _drop_audit()
    now = datetime.now(ICT)
    when = now.isoformat(timespec="microseconds")
    history = os.environ.get("BENCH_HISTORY") == "1"
    if history:
        _seed_history(client, now)
    jobs = []
    for index in range(N):
        rare = history and index >= N - 50
        jobs.append(
            {
                "decision_id": f"bench-{index}",
                "profile": "advanced",
                "sender_hash": f"bench_{index:04d}",
                "payee_hash": f"bench_payee_{index:04d}" if rare else "bench_known",
                "amount": 20_000_000 if rare else (300_000 if history else 1_000_000),
                "ts": when,
                "session_id": f"bench_sess_{index:04d}",
                "device": {},
                "_rare": rare,
            }
        )
        if history:
            jobs[-1]["add_method"] = "typed"
            jobs[-1]["balance"] = 50_000_000
            jobs[-1]["task_type"] = "new_typed"
        if os.environ.get("BENCH_BEHAVIOUR") == "1":
            jobs[-1]["task_type"] = "saved_payee"
            jobs[-1]["behaviour_features"] = {
                "median_gap_ms": 800,
                "p90_gap_ms": 2200,
                "burst_count": 2,
                "pause_to_action_ratio": 0.18,
                "review_dwell_ms": 1400,
                "edit_count": 1,
                "backtrack_count": 0,
                "screen_revisit_count": 1,
                "background_count": 0,
                "background_total_ms": 350,
                "session_duration_ms": 40000,
            }
    appmod.STORE = OnlineStore(flush=False)
    appmod.MODEL = Scorer.load()
    if history:
        from engine.features.habit import FEATURES, cached_model

        cached_model().explain({name: 1.0 for name in FEATURES})
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    times = []
    cohorts = []
    bad = 0
    seen = {"ordinary": False, "rare": False}
    try:
        for body in jobs:
            rare = bool(body.pop("_rare", False))
            data = json.dumps(body).encode()
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/decide",
                data=data,
                headers={"Content-Type": "application/json", "X-API-Key": os.environ["FIDES_API_KEY"]},
            )
            started = time.perf_counter()
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = json.loads(response.read().decode())
                status = response.status
            elapsed = time.perf_counter() - started
            if status != 200 or payload.get("level") not in (0, 1, 2, 3):
                bad += 1
            label = "rare" if rare else "ordinary"
            if history and not seen[label]:
                seen[label] = True
                print(
                    f"history {label}",
                    payload.get("level"),
                    payload.get("rules_fired"),
                    [item for item in payload.get("signals_present") or [] if str(item).startswith("habit")],
                    flush=True,
                )
            times.append(elapsed)
            cohorts.append(label)
    finally:
        server.shutdown()
        removed = _cleanup(client)
        _drop_audit()
        client.config_set("save", saved)
        print(f"bench keys removed {removed}", flush=True)
    print(f"http n {len(times)} bad {bad}", flush=True)
    _report("overall", times)
    if history:
        _report("ordinary", [elapsed for elapsed, label in zip(times, cohorts, strict=True) if label == "ordinary"])
        _report("rare", [elapsed for elapsed, label in zip(times, cohorts, strict=True) if label == "rare"])


def _report(name: str, times: list[float]) -> None:
    arr = np.asarray(times) * 1000
    print(
        f"{name} n {len(times)} "
        f"p50 {np.percentile(arr, 50):.3f}ms "
        f"p95 {np.percentile(arr, 95):.3f}ms "
        f"p99 {np.percentile(arr, 99):.3f}ms",
        flush=True,
    )


if __name__ == "__main__":
    main()
