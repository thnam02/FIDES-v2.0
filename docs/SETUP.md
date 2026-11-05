# Setting up the FIDES demo on a new Mac

This guide goes from a fresh clone to the five demo scenes in `docs/demo_manual.md`. Run every command from the repository root (`SEDIF/`) unless a step says otherwise. Each step ends with a check.

One thing cannot come from git: the simulated bank dataset in `fides-sim/out/` (194 MB). Copy it from the original Mac (step 6).

## 1. Requirements

Tested versions, November 2026:

| Tool | Tested | Minimum | Install |
| --- | --- | --- | --- |
| macOS | 27.0.1 | 15 | System Settings > General > Software Update |
| Xcode (iPhone or simulator build only) | 27.1 | 16.1 | App Store, then `sudo xcode-select -s /Applications/Xcode.app && sudo xcodebuild -license accept` |
| Homebrew | 7.0.10 | 4 | https://brew.sh |
| Python | 3.14.7 | 3.12 | `brew install python@3.14` |
| Node | 24.7.0 | 20.19 | `brew install node@24` |
| PostgreSQL | 16.14 | 16 | `brew install postgresql@16` |
| Redis | 8.8.0 | 7.2 | `brew install redis` |
| CocoaPods (iOS only) | 1.17.0 | 1.15 | `brew install cocoapods` |
| Expo CLI | 54.0.38 (local, `npx expo`) | from `bank-app/package.json` | installed by `npm ci`, no global install |

EAS is not used. Docker is optional (see `DB_MODE=docker` in Troubleshooting).

Hardware: 16 GB of RAM (Redis holds about 2.8 GB) and about 10 GB of free disk (Postgres 4 GB with the event history, `dump.rdb` 1.7 GB, `node_modules`, Pods and the iOS build).

```sh
xcode-select --install 2>/dev/null || true
brew install python@3.14 node@24 postgresql@16 redis cocoapods
brew link --overwrite node@24
brew link --force postgresql@16
```

Check:

```sh
python3.14 --version && node --version && psql --version && redis-server --version && pod --version
```

## 2. Clone

```sh
git clone --branch nam/fides https://github.com/thnam02/SEDIF.git
cd SEDIF
```

GitHub may print that the repository moved to `thnam02/FIDES-v2.0`. Both URLs work.

## 3. Secrets

The demo scripts read `.env` in the repository root. It is git-ignored. Never commit it.

```sh
cp .env.example .env
sed -i '' "s|^FIDES_HMAC_KEY=.*|FIDES_HMAC_KEY=$(openssl rand -hex 32)|" .env
sed -i '' "s|^FIDES_API_KEY=.*|FIDES_API_KEY=$(openssl rand -hex 32)|" .env
sed -i '' "s|YOUR_MAC_USER|$(whoami)|" .env
```

- `FIDES_HMAC_KEY` hashes every account id. All hashes in Postgres `events` and in the Redis snapshot are built with it. If you change it later, redo steps 7 and 8.
- `FIDES_API_KEY` is shared by bank-core and the engine.
- The original Mac's `.env` holds the built-in defaults (`fides-demo-hmac`, `fides-demo-key`), because its Postgres and Redis data were built with them. Do not change them there; `setup_check.sh` only warns that they are short. A new Mac builds its own data in steps 7 and 8 and should use its own random keys.

Optional: `BANK_API_KEY`. When it is set, every POST to bank-core needs the header `X-Bank-Key`, so other devices on the stage Wi-Fi cannot move money. Put the same value in `bank-app/.env` as `EXPO_PUBLIC_BANK_API_KEY`. That value is bundled into the app, so it does not hide anything from whoever holds the app. Leave both empty to switch it off.

```sh
key=$(openssl rand -hex 32)
sed -i '' "s|^BANK_API_KEY=.*|BANK_API_KEY=$key|" .env
```

Two more settings in `.env`: `GUARDIAN_COOLING_HOURS` (default 24) is how long a newly added or changed guardian must wait before approving, and `LEVEL2_HOLD_HOURS` (default 24) is when an unanswered level-2 hold is cancelled and refunded.

The app has its own file for the bank URL. Set this Mac's Wi-Fi address:

```sh
cp bank-app/.env.example bank-app/.env
sed -i '' "s|YOUR_MAC_LAN_IP|$(ipconfig getifaddr en0)|" bank-app/.env
grep -q '^BANK_API_KEY=.' .env && sed -i '' "s|^EXPO_PUBLIC_BANK_API_KEY=.*|EXPO_PUBLIC_BANK_API_KEY=$(sed -n 's/^BANK_API_KEY=//p' .env)|" bank-app/.env
```

## 4. Python environment

One virtualenv serves the engine, bank-core and the scripts. The scripts expect it at `fides-sim/.venv`.

```sh
python3.14 -m venv fides-sim/.venv
. fides-sim/.venv/bin/activate
python -m pip install --upgrade pip
pip install -r engine/requirements.txt -r bank-core/requirements.txt -r fides/requirements.txt
```

Every terminal you use for the setup or the demo starts with these two lines, from the repository root. The first makes `python3` the venv (`demo_reset.sh` calls `python3`). The second loads `.env` for the Python scripts; the shell scripts load it themselves.

```sh
. fides-sim/.venv/bin/activate
set -a; . ./.env; set +a
```

Do not install `fides-sim/requirements.txt` here. It pins pandas below 3 for the simulator only.

## 5. Node dependencies

`bank-app` depends on `fides-sdk` through `file:../fides-sdk`, so install the SDK first. Each folder has an `.npmrc` with `legacy-peer-deps=true`, because the lockfiles were resolved without auto-installed peer dependencies; without it npm 11 reports that the lockfile is out of sync.

```sh
(cd fides-sdk && npm ci)
(cd bank-app && npm ci)
(cd bank-app/ios && pod install)    # iPhone or simulator only
```

About 10 seconds for npm and 20 seconds for Pods with a warm cache.

## 6. Demo data (copy from the original Mac)

`fides-sim/out/` is git-ignored: 32 parquet files, 194 MB (`observed/` 164 MB, `truth/` 30 MB). bank-core, the Redis snapshot and the event loader all read it. The demo personas (Hoàng `A0051289`, Lê `A0031239`, Huỳnh `A0072556` with savings book `A0077690`, Trương `A0002119`) exist only in this exact copy.

On the original Mac:

```sh
cd ~/Desktop/FIDES/SEDIF
tar -czf ~/Desktop/fides-sim-out.tgz -C fides-sim out
```

Move `fides-sim-out.tgz` with AirDrop or a USB drive. On the new Mac, in the repository root:

```sh
tar -xzf ~/Downloads/fides-sim-out.tgz -C fides-sim
(cd fides-sim/out && shasum -a 256 -c --quiet ../../docs/fides-sim-out.sha256) && echo "data ok"
```

Do not regenerate it with `fides-sim/sim/step*.py`. Tested on 5 November 2026: under pandas 3 step 3 stops with "Mọi giao dịch bị loại"; under pandas 2.3 all seven steps run (about 6 minutes) but 30 of the 32 tables differ from the demo copy (for example 121 579 accounts instead of 126 463), so the demo personas and amounts do not match.

Everything else is in git and needs no copying:

| What | Where | Size |
| --- | --- | --- |
| Fraud model v2.1 | `engine/artifacts/model-v2.1/advanced_ctx_payee/` | 5.5 MB |
| Habit model | `engine/artifacts/habit/model.joblib`, `model.json` | 0.9 MB |
| Behaviour references | `engine/artifacts/behaviour_ref/*.json` | 2.1 MB |
| Training features | `fides/out/*.parquet`, `fides/out/model-v2.0/` | 23 MB |
| Personas | `docs/personas.json` | small |

## 7. Postgres

Start Postgres and create the database. There is no migration tool: the engine creates `events`, `decisions` and `responses` when it starts, and bank-core creates the `bank` schema on its first load.

```sh
brew services start postgresql@16
createdb fides_w1
psql "$DATABASE_URL" -c 'select 1'
```

Optional, not needed for the five scenes: the event history used by the dashboard and evaluation (3.6 million rows, about 6 minutes). The last lines compare every event type with its source count and must show no mismatch.

```sh
python scripts/load_sim_events.py --until 2026-09-20T00:00:00+07:00
```

## 8. Redis and the feature snapshot

Start Redis yourself, not with `brew services`. `demo_reset.sh` stops Redis and starts it again from `dump.rdb`; a launchd-managed Redis restarts on its own and fights it.

```sh
brew services stop redis 2>/dev/null || true
redis-server /opt/homebrew/etc/redis.conf --daemonize yes
redis-cli ping
```

Build the snapshot: every simulated event before 21/09 10:00 goes into Redis db 15, then `SAVE` writes `dump.rdb` (1.7 GB on disk, about 2.8 GB of RAM). About 3 minutes. It ends with `saved until=2026-09-21T10:00:00+07:00 dbsize=4101895`.

```sh
python scripts/rebuild_feature_snapshot.py
redis-cli -n 15 get f:snapshot_until     # 2026-09-21T10:00:00+07:00
```

The behaviour baseline for Trương is seeded by `demo_reset.sh` in step 9.

## 9. First start

The first start loads the bank ledger from the parquet files (`BANK_RESEED=1`). Later starts do not need it.

```sh
BANK_RESEED=1 sh scripts/demo_up.sh
sh scripts/demo_reset.sh
```

`demo_up.sh` prints `ready` after both health checks and one warm-up decision (about 50 seconds the first time, 10 seconds later). `demo_reset.sh` takes about 4 minutes, most of it Redis reloading `dump.rdb`, and also prints `ready`.

macOS asks once whether Python may accept incoming connections. Click Allow, or the iPhone cannot reach bank-core.

## 10. Verify

```sh
sh scripts/setup_check.sh
python scripts/verify_demo_scenes.py
sh scripts/demo_reset.sh
```

`setup_check.sh` prints PASS, WARN or FAIL for each requirement, with the fix. `WARN events history not loaded` is fine if you skipped the optional step in 7.

`verify_demo_scenes.py` reads `BANK_PORT` from `.env`, runs the five scenes by API and must end with `all scenes match`:

| Scene | Expected |
| --- | --- |
| 1 Hoàng, saved payee, 500.000 đ, no call | level 0, sent |
| 2 Lê, shop QR, 60.000 đ, call | level 1 sheet, no reason line open |
| 3 Huỳnh, 120 triệu before liquidation | refused, "không đủ số dư" |
| 3 Huỳnh, after liquidation, call, "Mua hàng" | level 2, group A, "gần hết số dư" and "Số tiền lớn gấp nhiều lần" |
| 4 Huỳnh, 40 triệu, "Cơ quan nhà nước" | level 2 strengthened, groups A + C, headline "Cơ quan nhà nước không bao giờ yêu cầu chuyển tiền để xác minh."; proceed after hang-up rejected; hotline fraud refunds 40 triệu |
| 5 Trương, guided switch, 500.000 đ, call | level 2, group B, dictation line and call line |

The script changes the ledger, so run `demo_reset.sh` again before a live demo.

## 11. Run the demo

```sh
sh scripts/demo_up.sh        # engine 8091 and bank 8092, detached, logs in logs/
sh scripts/demo_reset.sh     # once, right before the demo
caffeinate -d                # in a separate terminal; Ctrl+C after the demo
sh scripts/demo_down.sh      # after the demo
```

Then follow `docs/demo_manual.md`.

## 12. iPhone

The app is a development build (`expo-dev-client`) that loads its JavaScript from Metro on this Mac.

1. Signing. Open `bank-app/ios/SaoBank.xcworkspace` in Xcode, select the SaoBank target, Signing & Capabilities. Sign in with an Apple ID (Xcode > Settings > Accounts). The project is set to team `Q5FR94THY5` and bundle id `com.hainamtran.saobank`. With a different Apple ID, pick your team and change the bundle id to something unique (for example `com.yourname.saobank`). A free Apple ID works; the build expires after 7 days.
2. Pairing. Connect the iPhone by cable, unlock it, tap Trust. In Xcode open Window > Devices and Simulators and wait until the phone shows as paired. On the phone enable Settings > Privacy & Security > Developer Mode and restart it.
3. Build and open:

```sh
cd bank-app
npm run ios:device                                 # same Apple ID as the original Mac
BUNDLE_ID=com.yourname.saobank npm run ios:device  # if you changed the bundle id
```

`scripts/ios-device.sh` starts Metro on port 8089 (log in `/tmp/bvc-metro.log`), builds with `xcodebuild`, installs with `devicectl` and opens the app at `http://<this Mac's IP>:8089`. On first launch iOS asks to trust the developer: Settings > General > VPN & Device Management.

Network:

| Port | Service | Who connects |
| --- | --- | --- |
| 8089 | Metro (JavaScript bundle) | iPhone |
| 8092 | bank-core | iPhone (`EXPO_PUBLIC_BANK_URL` in `bank-app/.env`) |
| 8091 | engine | bank-core only, on `127.0.0.1` |

The iPhone and the Mac must be on the same Wi-Fi, without client isolation (hotel and guest networks often block it; a phone hotspot works). After changing `bank-app/.env` or the Wi-Fi, run `npm run ios:device` again so Metro restarts with the new address.

## 13. Simulator instead of an iPhone

```sh
sed -i '' "s|^EXPO_PUBLIC_BANK_URL=.*|EXPO_PUBLIC_BANK_URL=http://127.0.0.1:8092|" bank-app/.env
cd bank-app && npx expo run:ios --port 8089
```

This builds the dev client (about 5 minutes the first time), installs it on the booted simulator, starts Metro on 8089 and opens the app. The simulator shares the Mac's network, so `127.0.0.1` works and no Apple signing is needed.

What works: every screen, all five scenes, the level-1 sheet, the level-2 and level-3 screens, and the demo menu.

What does not:
- No real call detection. Use the call simulator: tap the "BVC BANK" title seven times, then "Số lạ gọi đến". "Demo: kết thúc cuộc gọi" in the demo menu ends it.
- No real screen capture or AirPlay signal. Use "Demo: màn hình đang bị ghi" in the demo menu.
- The shop QR is filled by the button, as on the iPhone. There is no camera.

## 14. Troubleshooting

**Postgres not reachable.** `brew services restart postgresql@16`, then `psql "$DATABASE_URL" -c 'select 1'`. If another Postgres holds port 5432 (`lsof -nP -iTCP:5432 -sTCP:LISTEN`), stop it.

**`DB_MODE=docker` uses the wrong database.** Compose's Postgres is an empty `fides` database without `fides_w1`. If Homebrew Postgres already accepts the `fides` login on 5432, docker mode connects there without starting Docker. Use the default `DB_MODE=host` for the demo.

**`redis-cli ... setsockopt(TCP_NODELAY): Invalid argument`.** A macOS quirk while Redis is still listening. The scripts retry it. If you see it by hand, run the command again.

**Redis was restarted and the scenes changed.** A Redis restart reloads `dump.rdb` and drops the Trương baseline that `demo_reset.sh` seeds. Run `sh scripts/demo_reset.sh`.

**Redis autosave.** The default `save` rule writes the live state back to `dump.rdb`, so after many demo runs the snapshot holds demo transfers. Rebuild it with `python scripts/rebuild_feature_snapshot.py` before an important demo, or add `save ""` to `/opt/homebrew/etc/redis.conf` after building it.

**Engine cold start, unscored transfers.** The first decision after a start loads the models. `demo_up.sh` and `demo_reset.sh` both send one warm-up decision. If the app shows "Không kiểm tra được giao dịch lúc này", check `curl http://127.0.0.1:8091/health` and `logs/engine.log`, then run `sh scripts/demo_up.sh`.

**Every transfer is level 2 with `R_CAPTURE`.** iOS reports AirPlay, screen recording and mirroring as screen capture. Turn them off in Control Center.

**The iPhone cannot reach the Mac.** Same Wi-Fi, no client isolation. `bank-app/.env` must match `ipconfig getifaddr en0`. macOS firewall: System Settings > Network > Firewall, allow Python and node. Test from the Mac: `curl http://$(ipconfig getifaddr en0):8092/health`.

**Port already in use.** `sh scripts/setup_check.sh` shows which program holds 8089, 8091 or 8092. `demo_up.sh` stops whatever listens on 8091 and 8092 before it starts.

## What this guide was tested with

On 5 November 2026 a fresh clone of `nam/fides` was set up on the original Mac by following steps 2 to 11, with its own database, its own Redis instance, its own ports and new random keys: `setup_check.sh` passed and `verify_demo_scenes.py` printed `all scenes match`. The iOS app compiled for the simulator from that clone (`BUILD SUCCEEDED`, about 5 minutes).

Not covered by that run: Apple signing with a different Apple ID, pairing a new iPhone, the macOS firewall prompt, `DB_MODE=docker`, and a Mac without the Homebrew tools already installed.
