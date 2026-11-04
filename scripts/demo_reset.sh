#!/bin/sh
# Dừng đồng hồ, xoá dữ liệu demo sau 20/9, nạp lại RDB và persona, đưa đồng hồ về 09:00.
set -eu
BANK=${BANK_URL:-http://127.0.0.1:8092}
ENGINE=${ENGINE_URL:-http://127.0.0.1:8091}
DATABASE_URL=${DATABASE_URL:-postgresql://hainamtran@localhost:5432/fides_w1}
REDIS_URL=${REDIS_URL:-redis://localhost:6379/15}
REDIS_PORT=${REDIS_PORT:-6379}
REDIS_HOST=${REDIS_HOST:-127.0.0.1}
REDIS_MODE=${REDIS_MODE:-host}
API_KEY=${FIDES_API_KEY:-fides-demo-key}
FIDES_HMAC_KEY=${FIDES_HMAC_KEY:-fides-demo-hmac}
export DATABASE_URL REDIS_URL REDIS_PORT REDIS_HOST FIDES_HMAC_KEY ENGINE API_KEY
DB=${REDIS_URL##*/}

curl -sf -X POST "$BANK/clock/pause" >/dev/null

psql "$DATABASE_URL" -v ON_ERROR_STOP=1 <<'SQL'
ALTER TABLE decisions DISABLE TRIGGER USER;
ALTER TABLE responses DISABLE TRIGGER USER;
DELETE FROM responses
WHERE ts >= TIMESTAMPTZ '2026-09-20T00:00:00+07:00'
   OR decision_id IN (SELECT decision_id FROM decisions WHERE ts >= TIMESTAMPTZ '2026-09-20T00:00:00+07:00');
DELETE FROM decisions WHERE ts >= TIMESTAMPTZ '2026-09-20T00:00:00+07:00';
ALTER TABLE decisions ENABLE TRIGGER USER;
ALTER TABLE responses ENABLE TRIGGER USER;
ALTER TABLE events DISABLE TRIGGER USER;
DELETE FROM events WHERE ts >= TIMESTAMPTZ '2026-09-20T00:00:00+07:00';
ALTER TABLE events ENABLE TRIGGER USER;
CREATE TABLE IF NOT EXISTS bank.experiment_sessions (
    id bigserial PRIMARY KEY,
    participant_id text NOT NULL,
    condition text NOT NULL,
    session_index integer NOT NULL,
    task_type text NOT NULL,
    call jsonb NOT NULL,
    behaviour_features jsonb NOT NULL,
    raw_events jsonb,
    created_at timestamptz NOT NULL,
    decision jsonb
);
ALTER TABLE bank.experiment_sessions ADD COLUMN IF NOT EXISTS decision jsonb;
TRUNCATE bank.entries, bank.transfers, bank.products, bank.guardian_requests,
         bank.guardians, bank.beneficiaries, bank.accounts, bank.idempotency, bank.call_notices,
         bank.experiment_sessions;
SQL

# DEBUG RELOAD bị tắt. Tắt Redis không ghi đè file, rồi bật lại để nạp đúng RDB.
# REDIS_MODE=docker chỉ khởi động lại service redis của compose, không đụng Redis trên máy.
if [ "$REDIS_MODE" = "docker" ]; then
  docker compose restart redis >/dev/null
else
  redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" SHUTDOWN NOSAVE >/dev/null 2>&1 || true
  REDIS_SERVER=${REDIS_SERVER:-redis-server}
  REDIS_CONF=${REDIS_CONF:-/opt/homebrew/etc/redis.conf}
  "$REDIS_SERVER" "$REDIS_CONF" --daemonize yes
fi
i=0
while true; do
  out=$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" -n "$DB" DBSIZE 2>&1 || true)
  case "$out" in
    *ERR*|*LOADING*|*loading*)
      i=$((i + 1))
      if [ "$i" -gt 600 ]; then
        echo "redis không lên: $out" >&2
        exit 1
      fi
      sleep 0.5
      ;;
    *)
      case "$out" in
        ''|*[!0-9]*)
          i=$((i + 1))
          if [ "$i" -gt 600 ]; then
            echo "redis không lên: $out" >&2
            exit 1
          fi
          sleep 0.5
          ;;
        *)
          if [ "$out" -lt 1000000 ]; then
            i=$((i + 1))
            if [ "$i" -gt 600 ]; then
              echo "redis chưa nạp đủ snapshot: $out" >&2
              exit 1
            fi
            sleep 0.5
          else
            break
          fi
          ;;
      esac
      ;;
  esac
done
# Chỉ xoá kho episode và baseline thao tác. SCAN + DEL, không FLUSHDB.
# BEGIN purge_prefix
# redis-cli trên macOS đôi khi trả setsockopt(TCP_NODELAY): Invalid argument dù Redis đang nghe.
redis_cmd() {
  tries=0
  note=""
  while true; do
    if note=$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" "$@" 2>&1); then
      printf '%s\n' "$note"
      return 0
    fi
    case "$note" in
      *TCP_NODELAY*|*Connection\ refused*|*LOADING*|*loading*)
        ;;
      *)
        echo "redis-cli lỗi: $note" >&2
        return 1
        ;;
    esac
    tries=$((tries + 1))
    if [ "$tries" -ge 40 ]; then
      echo "redis-cli lỗi: $note" >&2
      return 1
    fi
    sleep 0.25
  done
}
purge_prefix() {
  pattern=$1
  label=$2
  removed=0
  cursor=0
  while true; do
    out=$(redis_cmd -n "$DB" --raw SCAN "$cursor" MATCH "$pattern" COUNT 500)
    cursor=$(printf '%s\n' "$out" | head -n 1)
    keys=$(printf '%s\n' "$out" | tail -n +2)
    if [ -n "$keys" ]; then
      n=$(printf '%s\n' "$keys" | wc -l | tr -d ' ')
      # xargs không gọi được hàm shell. Gom khoá rồi xoá qua redis_cmd để lỗi TCP_NODELAY được thử lại.
      set --
      for key in $keys; do
        set -- "$@" "$key"
        if [ "$#" -ge 100 ]; then
          redis_cmd -n "$DB" DEL "$@" >/dev/null
          set --
        fi
      done
      if [ "$#" -gt 0 ]; then
        redis_cmd -n "$DB" DEL "$@" >/dev/null
      fi
      removed=$((removed + n))
    fi
    if [ "$cursor" = "0" ]; then
      break
    fi
  done
  echo "$label removed $removed"
}
# END purge_prefix
purge_prefix 'pol:v24:*' 'pol:v24'
purge_prefix 'beh:v24:*' 'beh:v24'
RESET_ID=$(python3 -c 'import uuid; print(uuid.uuid4())')
engine_body=$(curl -sS -X POST "$ENGINE/demo/reset" -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" -d "{\"reset_id\":\"$RESET_ID\"}" -w '\n%{http_code}')
engine_code=${engine_body##*$'\n'}
if [ "$engine_code" != "200" ]; then
  echo "engine reset $engine_code" >&2
  echo "$engine_body" >&2
  exit 22
fi
bank_body=$(curl -sS -X POST "$BANK/demo/reset" -H "Content-Type: application/json" -d "{\"reset_id\":\"$RESET_ID\"}" -w '\n%{http_code}')
bank_code=${bank_body##*$'\n'}
if [ "$bank_code" != "200" ]; then
  echo "bank reset $bank_code" >&2
  echo "$bank_body" >&2
  exit 22
fi
# Lệnh treo và yêu cầu giám hộ của bốn khách demo. Không đụng sổ lịch sử đã xong.
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 <<'SQL'
DELETE FROM bank.guardian_requests
WHERE account_id IN (
    'A0000623', 'A0050272', 'A0072556', 'A0077690',
    'A0002119',
    'A0002845', 'A0051289', 'A0072782', 'A0078375', 'A0097589',
    'A0031239'
);
DELETE FROM bank.idempotency
WHERE transfer_id IN (
    SELECT id FROM bank.transfers
    WHERE from_account IN (
        'A0000623', 'A0050272', 'A0072556', 'A0077690',
        'A0002119',
        'A0002845', 'A0051289', 'A0072782', 'A0078375', 'A0097589',
        'A0031239'
    )
      AND status IN ('pending_draft', 'needs_verification', 'held', 'blocked_pending_hangup', 'awaiting_confirmation', 'expired')
);
DELETE FROM bank.transfers
WHERE from_account IN (
    'A0000623', 'A0050272', 'A0072556', 'A0077690',
    'A0002119',
    'A0002845', 'A0051289', 'A0072782', 'A0078375', 'A0097589',
    'A0031239'
)
  AND status IN ('pending_draft', 'needs_verification', 'held', 'blocked_pending_hangup', 'awaiting_confirmation', 'expired');
SQL
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
FIDES_ROOT="$ROOT" python3 - <<'PY'
import json
import os
import subprocess
import sys

root = os.environ["FIDES_ROOT"]
with open(os.path.join(root, "docs", "personas.json"), encoding="utf-8") as handle:
    payload = json.load(handle)
ids = [account_id for person in payload["personas"] for account_id in person["account_ids"]]
quoted = ",".join("'" + item.replace("'", "") + "'" for item in ids)
sql = f"""
SELECT a.id,
       a.balance,
       a.opening_balance,
       COALESCE(SUM(CASE WHEN e.direction = 'in' THEN e.amount WHEN e.direction = 'out' THEN -e.amount ELSE 0 END), 0) AS net
FROM bank.accounts a
LEFT JOIN bank.entries e ON e.account_id = a.id
WHERE a.id IN ({quoted})
GROUP BY a.id, a.balance, a.opening_balance
ORDER BY a.id;
"""
done = subprocess.run(
    ["psql", os.environ["DATABASE_URL"], "-v", "ON_ERROR_STOP=1", "-t", "-A", "-F", "|", "-c", sql],
    check=False,
    capture_output=True,
    text=True,
)
if done.returncode != 0:
    sys.stderr.write(done.stderr or done.stdout)
    sys.exit(1)
seen = {}
for line in done.stdout.splitlines():
    if not line.strip():
        continue
    account_id, balance, opening, net = line.split("|")
    seen[account_id] = (int(balance), int(opening), int(net))
bad = []
missing = [item for item in ids if item not in seen]
if missing:
    bad.append("thiếu tài khoản: " + ", ".join(missing))
for account_id, (balance, opening, net) in sorted(seen.items()):
    if balance != opening + net:
        bad.append(f"{account_id}: số dư {balance} khác đầu kỳ {opening} + sổ {net}")
    if opening < 0:
        bad.append(f"{account_id}: đầu kỳ {opening} < 0")
if "A0072556" in seen:
    balance, opening, net = seen["A0072556"]
    if not 2_000_000 <= opening <= 4_000_000:
        bad.append(f"A0072556: đầu kỳ {opening} không nằm trong 2–4 triệu")
    if balance >= 120_000_000:
        bad.append(f"A0072556: số dư {balance} đã đủ 120 triệu trước khi tất toán")
entry_sql = f"""
SELECT account_id, direction, amount
FROM bank.entries
WHERE account_id IN ({quoted})
ORDER BY account_id, ts, id;
"""
entries = subprocess.run(
    ["psql", os.environ["DATABASE_URL"], "-v", "ON_ERROR_STOP=1", "-t", "-A", "-F", "|", "-c", entry_sql],
    check=False,
    capture_output=True,
    text=True,
)
if entries.returncode != 0:
    sys.stderr.write(entries.stderr or entries.stdout)
    sys.exit(1)
running = {account_id: opening for account_id, (_balance, opening, _net) in seen.items()}
for line in entries.stdout.splitlines():
    if not line.strip():
        continue
    account_id, direction, amount_text = line.split("|")
    amount = int(amount_text)
    running[account_id] = running[account_id] + (amount if direction == "in" else -amount)
    if running[account_id] < 0:
        bad.append(f"{account_id}: số dư chạy {running[account_id]} < 0")
book_sql = """
SELECT id, status, account_type, balance
FROM bank.accounts
WHERE id = 'A0077690';
"""
book = subprocess.run(
    ["psql", os.environ["DATABASE_URL"], "-v", "ON_ERROR_STOP=1", "-t", "-A", "-F", "|", "-c", book_sql],
    check=False,
    capture_output=True,
    text=True,
)
if book.returncode != 0:
    sys.stderr.write(book.stderr or book.stdout)
    sys.exit(1)
line = next((item for item in book.stdout.splitlines() if item.strip()), "")
parts = line.split("|") if line else []
if len(parts) != 4 or parts[1] != "open" or parts[2] != "savings" or int(parts[3]) != 150_000_000:
    bad.append(f"A0077690: cần sổ tiết kiệm mở 150000000, gặp {line or 'không có'}")
funds_sql = """
SELECT COUNT(*) FROM (
    SELECT id FROM bank.products
    WHERE account_id IN ('A0072556', 'A0077690') AND kind = 'savings_liquidation'
    UNION ALL
    SELECT tx_id FROM bank.entries
    WHERE account_id IN ('A0072556', 'A0077690') AND tx_type = 'savings_liquidation'
) events;
"""
funds = subprocess.run(
    ["psql", os.environ["DATABASE_URL"], "-v", "ON_ERROR_STOP=1", "-t", "-A", "-c", funds_sql],
    check=False,
    capture_output=True,
    text=True,
)
if funds.returncode != 0:
    sys.stderr.write(funds.stderr or funds.stdout)
    sys.exit(1)
if funds.stdout.strip() != "0":
    bad.append(f"đã có tất toán trước khi vào cảnh: {funds.stdout.strip()}")
if bad:
    sys.stderr.write("sổ không khớp số dư đầu kỳ:\n" + "\n".join(bad) + "\n")
    sys.exit(1)
PY
# Sổ Redis không giữ số dư hiện tại. product_savings_7d là zset. Xoá mọi tất toán
# của A0072556 trong cửa sổ demo để khớp Postgres vừa nạp (chưa tất toán).
FIDES_ROOT="$ROOT" python3 - <<'PY'
import os
import subprocess
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path[:0] = [os.environ["FIDES_ROOT"]]
from engine.common.hashing import account_hash, reset_key_cache

reset_key_cache()
account = account_hash("A0072556")
key = f"f:prod:savings_liquidation:{account}"
ict = ZoneInfo("Asia/Ho_Chi_Minh")
start = int(datetime(2026, 9, 14, tzinfo=ict).timestamp() * 1_000_000)
end = int(datetime(2026, 9, 23, tzinfo=ict).timestamp() * 1_000_000)
base = [
    "redis-cli",
    "-h",
    os.environ.get("REDIS_HOST", "127.0.0.1"),
    "-p",
    os.environ.get("REDIS_PORT", "6379"),
    "-n",
    os.environ["REDIS_URL"].rstrip("/").rsplit("/", 1)[-1],
]

def redis_call(args: list[str]) -> subprocess.CompletedProcess[str]:
    last = ""
    for _ in range(40):
        done = subprocess.run([*base, *args], check=False, capture_output=True, text=True)
        if done.returncode == 0:
            return done
        last = done.stderr or done.stdout
        if "TCP_NODELAY" not in last and "Connection refused" not in last and "LOADING" not in last:
            break
        time.sleep(0.25)
    sys.stderr.write(last)
    sys.exit(1)

removed = redis_call(["ZREMRANGEBYSCORE", key, str(start), str(end)])
left = redis_call(["ZCOUNT", key, str(start), str(end)])
if left.stdout.strip() != "0":
    sys.stderr.write(f"product_savings_7d của A0072556 còn {left.stdout.strip()}\n")
    sys.exit(1)
print(f"product_savings_7d A0072556 {left.stdout.strip()}")
PY
# Purge ở trên xoá mọi beh:v24. Chỉ Trương, task new_typed, được gieo lại cho cảnh C.
python3 "$ROOT/scripts/seed_demo_baseline.py"
python3 "$ROOT/scripts/seed_demo_baseline.py" --check
# Engine phải sống và đã chấm một lần, để lệnh demo đầu không rơi vào hạn 300 ms.
i=0
while true; do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 "$ENGINE/health" || true)
  if [ "$code" = "200" ]; then
    break
  fi
  i=$((i + 1))
  if [ "$i" -gt 60 ]; then
    echo "engine health $code" >&2
    exit 1
  fi
  sleep 0.5
done
ENGINE="$ENGINE" API_KEY="$API_KEY" FIDES_ROOT="$ROOT" python3 - <<'PY'
import json
import os
import sys
import urllib.error
import urllib.request

sys.path[:0] = [os.environ["FIDES_ROOT"]]
from engine.common.hashing import account_hash, reset_key_cache

reset_key_cache()
body = {
    "decision_id": "warmup-demo-reset",
    "profile": "advanced",
    "sender_hash": account_hash("A0031239"),
    "payee_hash": account_hash("warmup-payee"),
    "amount": 1,
    "ts": "2026-09-21T10:00:00+07:00",
    "session_id": "warmup-demo-reset",
    "device": {"state": "none"},
    "add_method": "typed",
    "task_type": "saved_payee",
}
data = json.dumps(body).encode()
request = urllib.request.Request(
    os.environ["ENGINE"].rstrip("/") + "/decide",
    data=data,
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
PY
echo ready
