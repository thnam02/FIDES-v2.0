"""Replay the simulated test set through the v2.5 policy. simulation only.

The packaged score and the habit source are computed once. Each later line
changes one policy input and replays the rules in time order, including episodes.

Behaviour timings are not in the simulated ledger. Sessions on a call draw
behaviour_rare and behaviour_guided from the synthetic rates at 10 prior
sessions (scripts/behaviour_eval.py, seed 42). Halving that effect halves
those probabilities and keeps the same random draws, so the smaller set is a
subset of the base set.

Inflow events are passthrough_in and incoming own_transfer in the 72 hours
before the session. The current transfer is the only outflow counted toward
the 70% pass-through. Product liquidations stay on the funding flag.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "fides"), str(REPO), str(REPO / "scripts")]

from engine.policy.v24 import STRING_LEVEL, MemoryState, evaluate
from sim_policy_v24 import _facts, _identities, _scores

from eval.model_v21 import prepare
from eval.policy_ablation import money_parts
from eval.decision import with_response

# Tỷ lệ ở 10 phiên nền, behaviour_eval, phân phối tổng hợp seed 42.
FRAUD_GUIDED = 0.385
FRAUD_RARE = 0.235
LEGIT_GUIDED = 0.030
LEGIT_RARE = 0.642
BEHAVIOUR_P = 0.01
BEHAVIOUR_SESSIONS = 10
PAYEE_COLUMNS = ("payee_account_age_days", "distinct_senders_7d", "passthrough_24h")


def _prepare():
    frames, bundle = prepare()
    print("simulation only: scoring packaged model", flush=True)
    scores = _scores(frames["test"])
    population = bundle["population"]
    population = population.loc[population["session_id"].astype(str).isin(bundle["test_ids"])].copy()
    population["session_id"] = population["session_id"].astype(str)
    population = population.drop_duplicates("session_id")
    meta = frames["test"][["session_id", "start_ts", "in_call", "call_ended_in_session", "acct_input", "merchant_verified"]].copy()
    meta["session_id"] = meta["session_id"].astype(str)
    work = population.merge(meta, on="session_id", how="left")
    work = work.merge(_identities(set(work["session_id"])), on="session_id", how="left")
    work["payee"] = work["payee"].fillna(False).astype(bool)
    work["funding"] = work["funding"].fillna(False).astype(bool)
    work["simo_listed"] = pd.to_numeric(work["simo_listed"], errors="coerce").fillna(0).ge(1)
    work["segment"] = work["segment"].astype("string").fillna("thường")
    work["amount"] = pd.to_numeric(work["amount"], errors="coerce").fillna(0)
    work["payee_transfers_before_listing"] = pd.to_numeric(work["payee_transfers_before_listing"], errors="coerce").fillna(0)
    work["payee_first_days_before_listing"] = pd.to_numeric(work["payee_first_days_before_listing"], errors="coerce").fillna(0)
    work["account_id"] = work["account_id"].astype("string").fillna(work["session_id"])
    work = work.sort_values(["start_ts", "session_id"], kind="mergesort").reset_index(drop=True)
    return work, scores, bundle


def _inflows(work: pd.DataFrame) -> list[list]:
    path = REPO / "fides-sim" / "out" / "observed" / "transactions.parquet"
    txs = pd.read_parquet(path, columns=["ts", "to_account", "amount", "tx_type"])
    txs["tx_type"] = txs["tx_type"].astype(str)
    txs = txs.loc[txs["tx_type"].isin(["passthrough_in", "own_transfer"])].copy()
    txs["to_account"] = txs["to_account"].astype(str)
    txs["ts"] = pd.to_datetime(txs["ts"], utc=True)
    txs["amount"] = pd.to_numeric(txs["amount"], errors="coerce").fillna(0).astype(np.int64)
    sessions = work[["session_id", "account_id", "start_ts"]].copy()
    sessions["account_id"] = sessions["account_id"].astype(str)
    sessions["start_ts"] = pd.to_datetime(sessions["start_ts"], utc=True)
    merged = txs.merge(sessions, left_on="to_account", right_on="account_id", how="inner")
    start = merged["start_ts"]
    keep = (merged["ts"] <= start) & (merged["ts"] > start - pd.Timedelta(hours=72))
    merged = merged.loc[keep]
    found: dict[str, list] = {str(item): [] for item in work["session_id"]}
    for row in merged.itertuples(index=False):
        kind = "p2p_inflow" if row.tx_type == "passthrough_in" else "own_transfer_in"
        found[str(row.session_id)].append(
            {
                "type": kind,
                "at": row.ts.isoformat(),
                "channel": "app",
                "amount": int(row.amount),
            }
        )
    return [found[str(item)] for item in work["session_id"]]


def _behaviour_columns(work: pd.DataFrame, scale: float, guided_draw: np.ndarray, rare_draw: np.ndarray) -> pd.DataFrame:
    on_call = work["in_call"].fillna(0).to_numpy(dtype=float) >= 1
    ended = work["call_ended_in_session"].fillna(0).to_numpy(dtype=float) >= 1
    called = on_call | ended
    fraud = work["is_fraud"].astype(bool).to_numpy()
    guided_p = np.where(called & fraud, FRAUD_GUIDED * scale, np.where(called & ~fraud, LEGIT_GUIDED * scale, 0.0))
    rare_p = np.where(called & fraud, FRAUD_RARE * scale, np.where(called & ~fraud, LEGIT_RARE * scale, 0.0))
    guided = guided_draw < guided_p
    rare = rare_draw < rare_p
    out = work.copy()
    guided_value = np.full(len(out), np.nan)
    rare_value = np.full(len(out), np.nan)
    sessions = np.full(len(out), np.nan)
    group = np.array([None] * len(out), dtype=object)
    top = np.array([None] * len(out), dtype=object)
    guided_value[guided] = BEHAVIOUR_P
    rare_value[rare] = BEHAVIOUR_P
    touched = guided | rare
    sessions[touched] = BEHAVIOUR_SESSIONS
    group[guided] = "dictation"
    top[guided] = "dictation"
    top[rare & ~guided] = "rhythm"
    out["behaviour_guided_p"] = guided_value
    out["behaviour_p_rarity"] = rare_value
    out["same_task_sessions"] = sessions
    out["behaviour_guided_group"] = group
    out["behaviour_top_group"] = top
    return out


def _replay(work: pd.DataFrame, scores: dict[str, float], label: str) -> dict[str, float]:
    state = MemoryState()
    levels = []
    strengthened = []
    total = len(work)
    for index, row in work.iterrows():
        outcome = evaluate(_facts(row, scores[str(row["session_id"])]), state)
        levels.append(STRING_LEVEL[outcome.level])
        strengthened.append(bool(outcome.strengthened))
        if index and index % 20000 == 0:
            print(f"simulation only: {label} {index}/{total}", flush=True)
    level = np.asarray(levels)
    strong = np.asarray(strengthened)
    fraud = work["is_fraud"].astype(bool).to_numpy()
    ge1 = np.isin(level, ["banner", "medium", "high"])
    ge2 = np.isin(level, ["medium", "high"])
    return {
        "legit_ge1": float(ge1[~fraud].mean()) if (~fraud).any() else float("nan"),
        "legit_ge2": float(ge2[~fraud].mean()) if (~fraud).any() else float("nan"),
        "fraud_ge2": float(ge2[fraud].mean()) if fraud.any() else float("nan"),
        "strong_legit": float(strong[~fraud].mean()) if (~fraud).any() else float("nan"),
        "strong_fraud": float(strong[fraud].mean()) if fraud.any() else float("nan"),
        "levels": level,
        "fraud": fraud,
    }


def _line(name: str, rates: dict[str, float]) -> None:
    print(
        f"{name:<42} {100 * rates['legit_ge1']:8.2f}% {100 * rates['legit_ge2']:8.2f}% "
        f"{100 * rates['fraud_ge2']:8.2f}% {100 * rates['strong_legit']:8.2f}% {100 * rates['strong_fraud']:8.2f}%",
        flush=True,
    )


def _mask_payees(work: pd.DataFrame, share: float, draw: np.ndarray) -> pd.DataFrame:
    masked = work.copy()
    drop = draw < share
    for column in PAYEE_COLUMNS:
        if column in masked.columns:
            masked.loc[drop, column] = np.nan
    return masked


def main() -> None:
    print("simulation only: v2.5", flush=True)
    work, scores, bundle = _prepare()
    print("simulation only: inflow events", flush=True)
    work["extra_funds"] = _inflows(work)
    from engine.features.habit import score_sessions

    print("simulation only: scoring habit", flush=True)
    habit = score_sessions(set(work["session_id"].astype(str)))

    def _picked(item, name):
        return None if item is None else getattr(item, name)

    picked = work["session_id"].map(lambda item: habit.get(str(item)))
    work["habit_rare"] = picked.map(lambda item: _picked(item, "rare"))
    work["habit_money_rare"] = picked.map(lambda item: _picked(item, "money_rare"))
    work["habit_top_group"] = picked.map(lambda item: _picked(item, "top_group"))
    work["habit_top_feature"] = picked.map(lambda item: _picked(item, "top_feature"))
    work["habit_quality"] = picked.map(lambda item: _picked(item, "quality"))
    work["habit_extreme"] = picked.map(lambda item: bool(item.extreme) if item is not None else False)
    rng = np.random.default_rng(42)
    guided_draw = rng.random(len(work))
    rare_draw = rng.random(len(work))
    payee_draw = rng.random(len(work))
    call_draw = rng.random(len(work))
    base = _behaviour_columns(work, 1.0, guided_draw, rare_draw)
    print(
        "behaviour assumption: on-call fraud "
        f"guided {FRAUD_GUIDED:.3f} rare {FRAUD_RARE:.3f}; "
        f"on-call legit guided {LEGIT_GUIDED:.3f} rare {LEGIT_RARE:.3f}; "
        "10 prior sessions; p=0.01 when drawn",
        flush=True,
    )
    rates = _replay(base, scores, "base")
    answered = with_response(base.assign(level=rates["levels"]), bundle["hang_of"], bundle["alone_of"], bundle["response"])
    saved, damage, rate, _saved_row, _ = money_parts(answered)
    print(f"n {len(work)}  tiền tránh được {saved:,.0f} VND ({100 * rate:.1f}% của {damage:,.0f})", flush=True)
    print(
        f"{'assumption':<42} {'legit≥1':>9} {'legit≥2':>9} {'fraud≥2':>9} {'strong legit':>12} {'strong fraud':>12}",
        flush=True,
    )
    _line("v2.5 base", rates)
    _line("70% interbank, payee features unknown", _replay(_mask_payees(base, 0.70, payee_draw), scores, "interbank70"))
    _line("85% interbank, payee features unknown", _replay(_mask_payees(base, 0.85, payee_draw), scores, "interbank85"))
    halved = _behaviour_columns(work, 0.5, guided_draw, rare_draw)
    _line("behaviour effect halved", _replay(halved, scores, "behaviour-half"))
    quiet = base.copy()
    fraud = quiet["is_fraud"].astype(bool).to_numpy()
    drop_call = fraud & (call_draw < 0.30)
    quiet.loc[drop_call, "in_call"] = 0
    quiet.loc[drop_call, "call_ended_in_session"] = 0
    quiet = _behaviour_columns(quiet, 1.0, guided_draw, rare_draw)
    _line("30% of scam sessions with no call", _replay(quiet, scores, "no-call"))
    no_habit = base.copy()
    for column in ("habit_rare", "habit_money_rare", "habit_top_group", "habit_top_feature", "habit_quality"):
        no_habit[column] = None
    no_habit["habit_extreme"] = False
    _line("habit source off", _replay(no_habit, scores, "no-habit"))
    no_inflow = base.copy()
    no_inflow["extra_funds"] = [[] for _ in range(len(no_inflow))]
    _line("inflow signals off", _replay(no_inflow, scores, "no-inflow"))


if __name__ == "__main__":
    main()
