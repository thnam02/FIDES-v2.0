#!/bin/sh
# Doctor for docs/SETUP.md. One line per check: PASS, WARN or FAIL, with the fix after "fix:".
# Reads .env like the demo scripts. Never prints key values. Exit 1 when any check fails.
set -u
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
if [ -f "$ROOT/.env" ]; then
  set -a
  . "$ROOT/.env"
  set +a
fi
PY=${PYTHON:-$ROOT/fides-sim/.venv/bin/python}
DATABASE_URL=${DATABASE_URL:-postgresql://$(whoami)@localhost:5432/fides_w1}
REDIS_URL=${REDIS_URL:-redis://localhost:6379/15}
REDIS_HOST=${REDIS_HOST:-127.0.0.1}
REDIS_PORT=${REDIS_PORT:-6379}
REDIS_DB=${REDIS_URL##*/}
ENGINE_PORT=${ENGINE_PORT:-8091}
BANK_PORT=${BANK_PORT:-8092}
METRO_PORT=${EXPO_PORT:-8089}
LOGS=${LOG_DIR:-$ROOT/logs}
WITH_IOS=${WITH_IOS:-1}
fails=0
warns=0

pass() { printf 'PASS  %s\n' "$1"; }
warn() { printf 'WARN  %s\n      fix: %s\n' "$1" "$2"; warns=$((warns + 1)); }
fail() { printf 'FAIL  %s\n      fix: %s\n' "$1" "$2"; fails=$((fails + 1)); }

# version_ge 3.14.2 3.11 -> true
version_ge() {
  awk -v a="$1" -v b="$2" 'BEGIN {
    n = split(a, x, "."); m = split(b, y, ".")
    for (i = 1; i <= (n > m ? n : m); i++) {
      p = (x[i] == "" ? 0 : x[i]) + 0; q = (y[i] == "" ? 0 : y[i]) + 0
      if (p > q) exit 0
      if (p < q) exit 1
    }
    exit 0
  }'
}

need_version() {
  name=$1
  got=$2
  min=$3
  fix=$4
  if [ -z "$got" ]; then
    fail "$name not found (need >= $min)" "$fix"
  elif version_ge "$got" "$min"; then
    pass "$name $got (>= $min)"
  else
    fail "$name $got is older than $min" "$fix"
  fi
}

echo "== Tools"
need_version macOS "$(sw_vers -productVersion 2>/dev/null)" 15.0 "Update macOS in System Settings > General > Software Update."
if [ "$WITH_IOS" = "1" ]; then
  need_version Xcode "$(xcodebuild -version 2>/dev/null | awk 'NR == 1 {print $2}')" 16.1 "Install Xcode from the App Store, then: sudo xcode-select -s /Applications/Xcode.app && sudo xcodebuild -license accept"
  need_version CocoaPods "$(pod --version 2>/dev/null)" 1.15 "brew install cocoapods"
fi
need_version Homebrew "$(brew --version 2>/dev/null | awk 'NR == 1 {print $2}')" 4.0 'Install from https://brew.sh'
need_version Node "$(node --version 2>/dev/null | tr -d v)" 20.19 "brew install node@24 && brew link --overwrite node@24"
need_version psql "$(psql --version 2>/dev/null | awk '{print $3}')" 16.0 "brew install postgresql@16 && brew link --force postgresql@16"
need_version redis-server "$(redis-server --version 2>/dev/null | sed -n 's/.*v=\([0-9.]*\).*/\1/p')" 7.2 "brew install redis"
need_version curl "$(curl --version 2>/dev/null | awk 'NR == 1 {print $2}')" 7.0 "brew install curl"
if [ -x "$PY" ]; then
  need_version "Python (venv)" "$("$PY" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')" 3.12 "brew install python@3.14 && rm -rf fides-sim/.venv && python3.14 -m venv fides-sim/.venv"
  missing=$("$PY" - 2>&1 <<'PY'
import importlib.util
names = ["pandas", "numpy", "pyarrow", "yaml", "lightgbm", "sklearn", "shap", "joblib", "psycopg", "redis", "fastapi", "uvicorn", "httpx"]
print(" ".join(name for name in names if importlib.util.find_spec(name) is None))
PY
) || missing="(python check failed: $missing)"
  if [ -z "$missing" ]; then
    pass "Python packages for engine, bank-core and scripts"
  else
    fail "Python packages missing: $missing" "fides-sim/.venv/bin/pip install -r engine/requirements.txt -r bank-core/requirements.txt -r fides/requirements.txt -r fides-sim/requirements.txt"
  fi
  if command -v python3 >/dev/null 2>&1 && [ "$(command -v python3)" = "$ROOT/fides-sim/.venv/bin/python3" ]; then
    pass "python3 on PATH is the project venv"
  else
    warn "python3 on PATH is $(command -v python3 2>/dev/null || echo missing), not the project venv" ". fides-sim/.venv/bin/activate   (demo_reset.sh calls python3)"
  fi
else
  fail "Python venv missing at $PY" "python3.14 -m venv fides-sim/.venv && fides-sim/.venv/bin/pip install -r engine/requirements.txt -r bank-core/requirements.txt -r fides/requirements.txt -r fides-sim/requirements.txt"
fi
if [ -d "$ROOT/fides-sdk/node_modules" ]; then pass "fides-sdk node_modules"; else fail "fides-sdk node_modules missing" "(cd fides-sdk && npm ci)"; fi
if [ -d "$ROOT/bank-app/node_modules" ]; then pass "bank-app node_modules"; else fail "bank-app node_modules missing" "(cd bank-app && npm ci)"; fi
if [ "$WITH_IOS" = "1" ]; then
  if [ -d "$ROOT/bank-app/ios/Pods" ]; then pass "bank-app iOS Pods"; else fail "bank-app/ios/Pods missing" "(cd bank-app/ios && pod install)"; fi
fi

echo "== Secrets"
if [ -f "$ROOT/.env" ]; then
  pass ".env present"
else
  fail ".env missing" "cp .env.example .env, then fill in the keys (see docs/SETUP.md, Secrets)"
fi
for key in FIDES_HMAC_KEY FIDES_API_KEY; do
  value=$(eval "printf '%s' \"\${$key:-}\"")
  if [ -z "$value" ]; then
    fail "$key is empty" "Add $key=\$(openssl rand -hex 32) to .env"
  elif [ "${#value}" -lt 16 ]; then
    warn "$key is set but short (${#value} characters)" "Use openssl rand -hex 32"
  else
    pass "$key is set (${#value} characters, value not shown)"
  fi
done
if git -C "$ROOT" ls-files --error-unmatch .env >/dev/null 2>&1; then
  fail ".env is tracked by git" "git rm --cached .env && commit; rotate both keys"
fi
APP_ENV="$ROOT/bank-app/.env"
LAN_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)
if [ -f "$APP_ENV" ]; then
  url=$(sed -n 's/^EXPO_PUBLIC_BANK_URL=//p' "$APP_ENV" | tail -n 1)
  if [ -z "$url" ]; then
    fail "bank-app/.env has no EXPO_PUBLIC_BANK_URL" "echo EXPO_PUBLIC_BANK_URL=http://$LAN_IP:$BANK_PORT >> bank-app/.env"
  elif [ -n "$LAN_IP" ] && [ "$url" != "http://$LAN_IP:$BANK_PORT" ]; then
    warn "bank-app/.env points at $url, this Mac is http://$LAN_IP:$BANK_PORT" "Set EXPO_PUBLIC_BANK_URL=http://$LAN_IP:$BANK_PORT in bank-app/.env and restart Metro (simulator only: http://127.0.0.1:$BANK_PORT also works)"
  else
    pass "bank-app/.env EXPO_PUBLIC_BANK_URL=$url"
  fi
else
  fail "bank-app/.env missing" "cp bank-app/.env.example bank-app/.env and set EXPO_PUBLIC_BANK_URL=http://$LAN_IP:$BANK_PORT"
fi

echo "== Data and model files"
for file in \
  fides-sim/out/observed/accounts.parquet fides-sim/out/observed/customers.parquet fides-sim/out/observed/transactions.parquet \
  fides-sim/out/observed/payees.parquet fides-sim/out/observed/sessions.parquet fides-sim/out/observed/session_events.parquet \
  fides-sim/out/observed/device_signals.parquet fides-sim/out/observed/account_device.parquet fides-sim/out/observed/account_changes.parquet \
  fides-sim/out/observed/simo_list.parquet fides-sim/out/observed/guardians.parquet \
  docs/personas.json \
  engine/artifacts/model-v2.1/advanced_ctx_payee/policy.json \
  engine/artifacts/habit/model.joblib engine/artifacts/habit/model.json \
  engine/artifacts/behaviour_ref/new_typed.json engine/artifacts/behaviour_ref/saved_payee.json \
  engine/artifacts/behaviour_ref/new_pasted.json engine/artifacts/behaviour_ref/qr.json; do
  if [ -s "$ROOT/$file" ]; then
    pass "$file"
  else
    case "$file" in
      fides-sim/out/*) fail "$file missing" "Copy fides-sim/out/ from the original Mac (docs/SETUP.md, Demo data)" ;;
      *) fail "$file missing" "git checkout nam/fides -- $file" ;;
    esac
  fi
done

if [ -d "$ROOT/fides-sim/out" ]; then
  if (cd "$ROOT/fides-sim/out" && shasum -a 256 -c --quiet "$ROOT/docs/fides-sim-out.sha256" >/dev/null 2>&1); then
    pass "fides-sim/out matches docs/fides-sim-out.sha256 (the demo dataset)"
  else
    fail "fides-sim/out differs from docs/fides-sim-out.sha256" "Copy fides-sim/out/ from the original Mac again. Regenerating with fides-sim does not reproduce it."
  fi
fi

echo "== Postgres"
if psql "$DATABASE_URL" -tAc 'select 1' >/dev/null 2>&1; then
  pass "Postgres reachable at $DATABASE_URL"
  server=$(psql "$DATABASE_URL" -tAc 'show server_version' 2>/dev/null | awk '{print $1}')
  need_version "Postgres server" "$server" 16.0 "brew services stop postgresql@14 2>/dev/null; brew services start postgresql@16"
  accounts=$(psql "$DATABASE_URL" -tAc "select count(*) from bank.accounts" 2>/dev/null || true)
  if [ -n "$accounts" ] && [ "$accounts" -gt 100000 ]; then
    pass "bank ledger loaded ($accounts accounts)"
  else
    fail "bank ledger not loaded (bank.accounts: ${accounts:-missing})" "BANK_RESEED=1 sh scripts/demo_up.sh   (first start creates the bank schema and loads it)"
  fi
  personas=$(psql "$DATABASE_URL" -tAc "select count(*) from bank.accounts where id in ('A0051289','A0031239','A0072556','A0077690','A0002119')" 2>/dev/null || true)
  if [ "${personas:-0}" = "5" ]; then
    pass "demo personas present (Hoàng, Lê, Huỳnh + savings book, Trương)"
  else
    fail "demo personas missing (${personas:-0}/5)" "The parquet files are not the seed-42 dataset. Copy fides-sim/out/ from the original Mac, then BANK_RESEED=1 sh scripts/demo_up.sh"
  fi
  for table in decisions responses events; do
    if psql "$DATABASE_URL" -tAc "select 1 from $table limit 1" >/dev/null 2>&1; then
      pass "engine table $table exists"
    else
      fail "engine table $table missing" "sh scripts/demo_up.sh   (the engine creates it on start)"
    fi
  done
  events=$(psql "$DATABASE_URL" -tAc "select count(*) from events" 2>/dev/null || echo 0)
  if [ "${events:-0}" -gt 1000000 ]; then
    pass "events history loaded ($events rows)"
  else
    warn "events history not loaded (${events:-0} rows). The 5 scenes do not need it" "python scripts/load_sim_events.py --until 2026-09-20T00:00:00+07:00"
  fi
else
  fail "Postgres not reachable at $DATABASE_URL" "brew services start postgresql@16 && createdb ${DATABASE_URL##*/}"
fi

echo "== Redis"
if redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" PING 2>/dev/null | grep -q PONG; then
  pass "Redis up at $REDIS_HOST:$REDIS_PORT"
  size=$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" -n "$REDIS_DB" DBSIZE 2>/dev/null | tr -cd '0-9')
  until_mark=$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" -n "$REDIS_DB" GET f:snapshot_until 2>/dev/null)
  if [ "${size:-0}" -ge 1000000 ] && [ "$until_mark" = "2026-09-21T10:00:00+07:00" ]; then
    pass "feature snapshot in db $REDIS_DB ($size keys, until $until_mark)"
  else
    fail "feature snapshot missing in db $REDIS_DB (${size:-0} keys, until '${until_mark}')" "python scripts/rebuild_feature_snapshot.py   (about 15 minutes), then sh scripts/demo_reset.sh"
  fi
  dir=$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" CONFIG GET dir 2>/dev/null | tail -n 1)
  file=$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" CONFIG GET dbfilename 2>/dev/null | tail -n 1)
  if [ -s "$dir/$file" ]; then
    pass "snapshot file $dir/$file ($(du -h "$dir/$file" | awk '{print $1}'))"
  else
    fail "no RDB file at $dir/$file. demo_reset.sh reloads Redis from it" "python scripts/rebuild_feature_snapshot.py"
  fi
else
  fail "Redis not reachable at $REDIS_HOST:$REDIS_PORT" "redis-server ${REDIS_CONF:-/opt/homebrew/etc/redis.conf} --daemonize yes   (not brew services, see docs/SETUP.md)"
fi

echo "== Ports"
port_owner() {
  pid=$(lsof -nP -t -iTCP:"$1" -sTCP:LISTEN 2>/dev/null | head -n 1)
  [ -z "$pid" ] && return 1
  ps -o command= -p "$pid" 2>/dev/null
}
for spec in "engine:$ENGINE_PORT:engine.app" "bank:$BANK_PORT:uvicorn" "metro:$METRO_PORT:expo"; do
  name=${spec%%:*}
  rest=${spec#*:}
  port=${rest%%:*}
  marker=${rest#*:}
  owner=$(port_owner "$port" || true)
  if [ -z "$owner" ]; then
    pass "port $port free ($name)"
  else
    case "$owner" in
      *"$marker"*) pass "port $port owned by the demo $name" ;;
      *) fail "port $port is used by another program: $(printf '%s' "$owner" | cut -c1-80)" "Stop it (lsof -nP -iTCP:$port -sTCP:LISTEN) or set ${name}-port in .env" ;;
    esac
  fi
done
for name in engine bank; do
  port=$([ "$name" = engine ] && echo "$ENGINE_PORT" || echo "$BANK_PORT")
  if [ -n "$(port_owner "$port" || true)" ]; then
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "http://127.0.0.1:$port/health" || true)
    if [ "$code" = "200" ]; then pass "$name health 200 on $port"; else fail "$name health $code on $port" "sh scripts/demo_up.sh, then see $LOGS/$name.log"; fi
  fi
done

echo
if [ "$fails" -eq 0 ]; then
  echo "setup_check: all checks passed ($warns warnings)"
else
  echo "setup_check: $fails failed, $warns warnings"
fi
[ "$fails" -eq 0 ]
