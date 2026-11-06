#!/bin/sh
# Dừng engine và bank-core mà scripts/demo_up.sh đã bật, theo pid trong logs/.
# Không đụng Postgres và Redis trên máy. DB_MODE=docker thì dừng thêm postgres và redis của compose.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
. "$ROOT/scripts/load_env.sh"
load_env "$ROOT/.env"
LOGS=${LOG_DIR:-$ROOT/logs}
DB_MODE=${DB_MODE:-host}

stop() {
  name=$1
  pidfile="$LOGS/$name.pid"
  if [ ! -f "$pidfile" ]; then
    echo "$name: không có $pidfile, bỏ qua"
    return 0
  fi
  pid=$(cat "$pidfile")
  # Pid có thể đã được tái dùng. Chỉ dừng nếu đúng là server của demo.
  command=$(ps -o command= -p "$pid" 2>/dev/null || true)
  case "$command" in
    *engine.app*|*uvicorn*app:app*) ;;
    *)
      echo "$name: pid $pid không còn chạy server demo, bỏ qua"
      rm -f "$pidfile"
      return 0
      ;;
  esac
  kill "$pid" 2>/dev/null || true
  n=0
  while kill -0 "$pid" 2>/dev/null; do
    n=$((n + 1))
    if [ "$n" -eq 40 ]; then
      kill -9 "$pid" 2>/dev/null || true
    fi
    if [ "$n" -gt 60 ]; then
      echo "$name: pid $pid không dừng" >&2
      exit 1
    fi
    sleep 0.25
  done
  rm -f "$pidfile"
  echo "$name: đã dừng pid $pid"
}

stop bank
stop engine
if [ "$DB_MODE" = "docker" ]; then
  (cd "$ROOT" && docker compose stop postgres redis)
fi
echo stopped
