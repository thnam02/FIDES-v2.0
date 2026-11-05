#!/bin/sh
# Bật engine (8091) và bank-core (8092) tách khỏi terminal đang mở, ghi log vào logs/.
# Dừng tiến trình đang nghe hai cổng đó trước. Đợi health, chấm thử một lệnh, rồi in ready.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
PY=${PYTHON:-$ROOT/fides-sim/.venv/bin/python}
ENGINE_PORT=${ENGINE_PORT:-8091}
BANK_PORT=${BANK_PORT:-8092}
ENGINE=http://127.0.0.1:$ENGINE_PORT
BANK=http://127.0.0.1:$BANK_PORT
# DB_MODE=host: Postgres Homebrew giữ fides_w1, Redis chạy bằng redis-server trên máy.
# DB_MODE=docker: postgres và redis của docker-compose.yml. Postgres đó là cơ sở fides trống, không có fides_w1.
DB_MODE=${DB_MODE:-host}
if [ "$DB_MODE" = "docker" ]; then
  DATABASE_URL=${DATABASE_URL:-postgresql://fides:fides@localhost:5432/fides}
else
  DATABASE_URL=${DATABASE_URL:-postgresql://hainamtran@localhost:5432/fides_w1}
fi
REDIS_URL=${REDIS_URL:-redis://localhost:6379/15}
REDIS_HOST=${REDIS_HOST:-127.0.0.1}
REDIS_PORT=${REDIS_PORT:-6379}
FIDES_HMAC_KEY=${FIDES_HMAC_KEY:-fides-demo-hmac}
FIDES_API_KEY=${FIDES_API_KEY:-fides-demo-key}
LOGS=${LOG_DIR:-$ROOT/logs}
export DATABASE_URL REDIS_URL FIDES_HMAC_KEY FIDES_API_KEY
mkdir -p "$LOGS"

fail() {
  echo "LỖI: $1" >&2
  shift
  for line in "$@"; do
    echo "  $line" >&2
  done
  exit 1
}

if [ ! -x "$PY" ]; then
  fail "không có python: $PY" "Tạo lại môi trường: python3 -m venv fides-sim/.venv && fides-sim/.venv/bin/pip install -r engine/requirements.txt"
fi

pg_ok() {
  psql "$DATABASE_URL" -tAc 'select 1' >/dev/null 2>&1
}
redis_ok() {
  redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" PING 2>/dev/null | grep -q PONG
}
# Redis trả LOADING trong lúc nạp snapshot lớn, nên đợi tối đa 5 phút.
wait_for() {
  name=$1
  check=$2
  limit=$3
  n=0
  until "$check"; do
    n=$((n + 1))
    if [ "$n" -gt "$limit" ]; then
      return 1
    fi
    sleep 0.5
  done
  echo "$name ok"
}

case "$DB_MODE" in
  docker)
    if ! pg_ok || ! redis_ok; then
      docker info >/dev/null 2>&1 || fail "docker không chạy, không bật được postgres và redis." "Mở Docker Desktop rồi chạy lại: DB_MODE=docker sh scripts/demo_up.sh"
      (cd "$ROOT" && docker compose up -d postgres redis) || fail "docker compose up -d postgres redis thất bại."
    fi
    wait_for postgres pg_ok 120 || fail "postgres không trả lời: $DATABASE_URL" "Xem: docker compose logs postgres"
    wait_for redis redis_ok 600 || fail "redis không trả lời: $REDIS_HOST:$REDIS_PORT" "Xem: docker compose logs redis"
    ;;
  host)
    pg_ok || fail "postgres không trả lời: $DATABASE_URL" \
      "Demo dùng Postgres Homebrew có cơ sở fides_w1. Postgres của docker compose không có fides_w1." \
      "Bật lại: brew services restart postgresql@16" \
      "Kiểm tra: psql \"$DATABASE_URL\" -c 'select 1'"
    echo "postgres ok"
    if ! redis_ok; then
      "${REDIS_SERVER:-redis-server}" "${REDIS_CONF:-/opt/homebrew/etc/redis.conf}" --port "$REDIS_PORT" --daemonize yes >/dev/null 2>&1 \
        || fail "không bật được redis-server trên cổng $REDIS_PORT." "Thử tay: redis-server ${REDIS_CONF:-/opt/homebrew/etc/redis.conf} --daemonize yes"
    fi
    wait_for redis redis_ok 600 || fail "redis không trả lời: $REDIS_HOST:$REDIS_PORT" "Xem log trong ${REDIS_CONF:-/opt/homebrew/etc/redis.conf} (logfile)."
    ;;
  *)
    fail "DB_MODE phải là host hoặc docker, gặp: $DB_MODE"
    ;;
esac

stop_port() {
  pids=$(lsof -nP -t -iTCP:"$1" -sTCP:LISTEN 2>/dev/null || true)
  [ -z "$pids" ] && return 0
  kill $pids 2>/dev/null || true
  n=0
  while lsof -nP -t -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; do
    n=$((n + 1))
    if [ "$n" -gt 40 ]; then
      kill -9 $pids 2>/dev/null || true
    fi
    if [ "$n" -gt 60 ]; then
      echo "cổng $1 vẫn bận" >&2
      exit 1
    fi
    sleep 0.25
  done
}

# setsid tách khỏi nhóm tiến trình của terminal, nên đóng editor không kéo theo server.
detach() {
  log=$1
  dir=$2
  shift 2
  (cd "$dir" && nohup "$PY" -c 'import os, sys; os.setsid(); os.execvp(sys.argv[1], sys.argv[1:])' "$@" >"$log" 2>&1 </dev/null &)
}

# Python của Homebrew chạy lại chính nó trong tiến trình con. Pid lấy từ tiến trình đang nghe cổng.
wait_health() {
  name=$1
  url=$2
  log=$3
  port=$4
  n=0
  until [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 "$url/health" || true)" = "200" ]; do
    n=$((n + 1))
    if [ "$n" -gt 240 ]; then
      echo "$name không lên sau 120 giây. Xem $log" >&2
      tail -n 20 "$log" >&2 || true
      exit 1
    fi
    sleep 0.5
  done
  lsof -nP -t -iTCP:"$port" -sTCP:LISTEN >"$LOGS/$name.pid"
  echo "$name 200 $url pid $(cat "$LOGS/$name.pid")"
}

stop_port "$BANK_PORT"
stop_port "$ENGINE_PORT"

PYTHONPATH="$ROOT" ENGINE_HOST=127.0.0.1 ENGINE_PORT="$ENGINE_PORT" DEMO_REPLAY=0 \
  detach "$LOGS/engine.log" "$ROOT" "$PY" -m engine.app
wait_health engine "$ENGINE" "$LOGS/engine.log" "$ENGINE_PORT"

PYTHONPATH="$ROOT:$ROOT/bank-core" ENGINE_URL="$ENGINE" DEMO_REPLAY=0 BANK_RESEED=0 \
  detach "$LOGS/bank.log" "$ROOT/bank-core" "$PY" -m uvicorn app:app --host 0.0.0.0 --port "$BANK_PORT" --log-level warning
wait_health bank "$BANK" "$LOGS/bank.log" "$BANK_PORT"

ENGINE="$ENGINE" API_KEY="$FIDES_API_KEY" python3 "$ROOT/scripts/warmup_decide.py" "warmup-demo-up-$(date +%s)"
echo "logs $LOGS"
echo "dừng: sh scripts/demo_down.sh"
if ! pgrep -x caffeinate >/dev/null 2>&1; then
  echo "NHẮC: mở một terminal khác và chạy  caffeinate -d  để Mac không ngủ trong lúc demo. Ctrl+C sau demo."
fi
echo ready
