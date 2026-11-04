"""IsolationForest thói quen, chỉ giao dịch hợp lệ trong cửa sổ train. Seed 42."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "fides"), str(REPO)]

from engine.features.habit import (  # noqa: E402
    ART,
    CONSISTENCY,
    FEATURES,
    GROUPS,
    MODEL_VERSION,
    SEED,
    HabitModel,
    Population,
    Transfer,
    collect_raws,
    features_from,
    read_outgoing,
)
from eval.split import build_split  # noqa: E402

POLICY = REPO / "engine" / "policy" / "bank_policy.yaml"


def _rates(frame: pd.DataFrame, wanted: np.ndarray) -> float:
    from engine.features.habit import day_id

    used = frame.loc[wanted, "customer"].unique()
    part = frame.loc[frame["customer"].isin(used)].copy()
    part["day"] = [day_id(int(item)) for item in part["ts_us"]]
    grouped = part.groupby("customer", sort=False)
    daily = grouped.size() / grouped["day"].nunique()
    return float(daily.median()) if len(daily) else 1.0


def _probs(values: list[int], buckets: int) -> list[float]:
    counts = np.bincount(np.asarray(values, dtype=int), minlength=buckets).astype(float)
    total = float(counts.sum())
    if total <= 0:
        return [1.0 / buckets] * buckets
    probs = np.maximum(counts / total, 1e-6)
    probs = probs / probs.sum()
    return [float(item) for item in probs]


def _put(name: str, value: float) -> None:
    text = POLICY.read_text(encoding="utf-8")
    updated, count = re.subn(
        rf"(  {name}:\n    value: )[^\n]+",
        rf"\g<1>{value:.16g}",
        text,
        count=1,
    )
    if count != 1:
        raise RuntimeError(f"không thấy ngưỡng {name}")
    POLICY.write_text(updated, encoding="utf-8")


def main() -> None:
    parts = build_split()
    legit = set(parts["train"].loc[~parts["train"]["is_fraud"].astype(bool), "session_id"].astype(str))
    frame = read_outgoing()
    wanted = frame["session_id"].isin(legit).to_numpy()
    print(f"outgoing {len(frame)} legit train {int(wanted.sum())}", flush=True)
    customers = frame["customer"].tolist()
    transfers = [
        Transfer(int(ts), str(payee), int(amount), int(balance))
        for ts, payee, amount, balance in zip(frame["ts_us"], frame["to_account"], frame["amount"], frame["balance"], strict=True)
    ]
    indices, raws, amounts, unseen_rates = collect_raws(customers, transfers, wanted.tolist())
    ratios = [raw.ratio for raw in raws if raw.ratio is not None]
    ratio_median = float(np.median(ratios)) if ratios else 0.0
    ratio_mad = float(np.median([abs(item - ratio_median) for item in ratios])) if ratios else 1.0
    if ratio_mad <= 0:
        ratio_mad = 1e-3
    hours = [raw.hour for raw in raws]
    weekdays = [raw.weekday for raw in raws]
    maxes = frame.groupby("customer", sort=False)["amount"].max()
    trained_customers = set(frame.loc[wanted, "customer"])
    max_ref = float(maxes.loc[maxes.index.isin(trained_customers)].median())
    population = Population(
        median_amount=float(np.median(amounts)),
        max_amount_ref=max(max_ref, 1.0),
        typical_7d=float(np.median([raw.week_sum for raw in raws])),
        balance_median=ratio_median,
        balance_mad=ratio_mad,
        hour_p=_probs(hours, 24),
        weekday_p=_probs(weekdays, 7),
        typical_daily=max(_rates(frame, wanted), 1e-3),
        typical_unseen_daily=float(np.median(unseen_rates)) if unseen_rates else 0.0,
    )
    matrix = pd.DataFrame([features_from(raw, amount, population) for raw, amount in zip(raws, amounts, strict=True)], columns=list(FEATURES))
    population.feature_median = {name: float(matrix[name].median()) for name in FEATURES}
    population.feature_mad = {}
    for name in FEATURES:
        center = population.feature_median[name]
        mad = float((matrix[name] - center).abs().median())
        population.feature_mad[name] = mad if mad > 1e-6 else 1e-3
    scale = np.asarray([population.feature_mad[name] for name in FEATURES], dtype=float)
    center = np.asarray([population.feature_median[name] for name in FEATURES], dtype=float)
    profile = np.maximum((matrix.to_numpy(dtype=float) - center) / (CONSISTENCY * scale), 0.0).max(axis=1)
    population.z_threshold = float(np.quantile(profile, 0.98))
    model = IsolationForest(
        n_estimators=100,
        max_samples=min(256, len(matrix)),
        random_state=SEED,
        contamination="auto",
        n_jobs=1,
    )
    model.fit(matrix)
    ART.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, ART / "model.joblib")
    import shap

    explainer = shap.TreeExplainer(model)
    holder = HabitModel(model, explainer, population, MODEL_VERSION)
    scores = -model.decision_function(matrix)
    population.if_threshold = float(np.quantile(scores, 0.98))
    holder.population = population
    probe = int(matrix["amount_vs_window_max"].idxmax())
    probe_features = matrix.iloc[probe].to_dict()
    probe_score, probe_contrib = holder.anomaly(probe_features)
    probe_top = holder.top_feature(probe_features, probe_contrib)
    print(
        f"threshold if {population.if_threshold:.6g} z {population.z_threshold:.6g} "
        f"probe score {probe_score:.6g} top {probe_top} group {None if probe_top is None else GROUPS[probe_top]}",
        flush=True,
    )
    if probe_score > population.if_threshold and (probe_top is None or GROUPS[probe_top] != "amount"):
        raise RuntimeError(f"TreeSHAP không chỉ nhóm amount cho lệnh lệch tiền nhất ({probe_top})")
    blob = (ART / "model.joblib").read_bytes()
    spec = {
        "model_version": MODEL_VERSION,
        "seed": SEED,
        "features": list(FEATURES),
        "groups": GROUPS,
        "n_estimators": 100,
        "max_samples": min(256, len(matrix)),
        "trained_on": "legit transactions in the train window, is_fraud false, before day 50",
        "n_rows": int(len(matrix)),
        "sha256": hashlib.sha256(blob).hexdigest(),
        "population": population.as_dict(),
    }
    (ART / "model.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _put("habit_score_above", population.if_threshold)
    _put("habit_profile_above", population.z_threshold)
    above = int((scores > population.if_threshold).sum())
    print(f"saved {ART} rows {len(matrix)} above if threshold {above}", flush=True)


if __name__ == "__main__":
    main()
