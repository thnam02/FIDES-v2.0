"""Nạp lại snapshot Redis cho demo, không cắt cửa sổ 7 ngày.

Lệnh cũ `snapshot_features.py --rebuild` trim mọi khoản cũ hơn 7 ngày. Thói quen
cần 90 ngày và 12 tháng, nên lệnh này nạp observed tới mốc --until rồi SAVE,
không trim. Cùng parquet và cùng mốc thì ra cùng một sổ.

Mặc định until=2026-09-21T10:00:00+07:00, đúng giờ demo buổi sáng. Không ghi đè
dump.rdb giữa chừng: tắt save của Redis trong lúc nạp, bật lại sau SAVE.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import redis

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.common.hashing import require_key
from scripts.replay import OBSERVED, build_until

DEFAULT_UNTIL = "2026-09-21T10:00:00+07:00"


def _client(url: str) -> redis.Redis:
    return redis.Redis.from_url(url, decode_responses=True, socket_timeout=None)


def rebuild(until: str, redis_url: str) -> None:
    require_key()
    client = _client(redis_url)
    saved = client.config_get("save").get("save", "")
    client.config_set("save", "")
    try:
        store = build_until(OBSERVED, until, redis_url)
        store.redis.close()
        client = _client(redis_url)
        started = time.perf_counter()
        client.save()
        marker = client.get("f:snapshot_until")
        print(
            f"saved until={marker} dbsize={client.dbsize()} save_s={time.perf_counter() - started:.1f}",
            flush=True,
        )
    finally:
        client.config_set("save", saved)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--until", default=DEFAULT_UNTIL)
    parser.add_argument("--redis", default=os.environ.get("REDIS_URL", "redis://localhost:6379/15"))
    args = parser.parse_args()
    rebuild(args.until, args.redis)


if __name__ == "__main__":
    main()
