"""Thói quen chuyển tiền của chính khách, trước lệnh này.

Mỗi đặc trưng so với khách đó và co về quần thể khi lịch sử còn ngắn.
Không có cuộc gọi, thao tác, mục đích, huy động tiền, và không có cờ
người nhận mới. new_payee là tín hiệu riêng.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

from engine.features.behaviour import CONSISTENCY, robust_z

log = logging.getLogger("engine.habit")
MODEL_VERSION = "habit-v2.5"
SEED = 42
PRIOR = 5.0
ART = Path(__file__).resolve().parents[1] / "artifacts" / "habit"
DAY_US = 86_400 * 1_000_000
ICT_SHIFT_S = 7 * 3600
EXTREME_MULTIPLE = 20.0
EXTREME_FLOOR = 10_000_000
QUALITY_MEDIUM = 5
QUALITY_HIGH = 20
WINDOW_MIN = 10
CLIP = 50.0

FEATURES = (
    "log_amount_vs_median",
    "amount_vs_window_max",
    "week_unseen_amount_vs_typical",
    "balance_ratio_z",
    "hour_rarity",
    "weekday_rarity",
    "count_24h_vs_typical",
    "other_unseen_24h_vs_typical",
)
GROUPS = {
    "log_amount_vs_median": "amount",
    "amount_vs_window_max": "amount",
    "week_unseen_amount_vs_typical": "amount",
    "balance_ratio_z": "balance",
    "hour_rarity": "timing",
    "weekday_rarity": "timing",
    "count_24h_vs_typical": "velocity",
    "other_unseen_24h_vs_typical": "velocity",
}
WEEK_FEATURE = "week_unseen_amount_vs_typical"
AMOUNT_TEXT = "Số tiền lớn gấp nhiều lần mức bạn thường chuyển."
WEEK_TEXT = "Tổng tiền chuyển cho người mới trong tuần này cao bất thường."
BALANCE_TEXT = "Bạn đang chuyển gần hết số dư."
TIMING_TEXT = "Bạn hiếm khi chuyển tiền vào giờ này."
VELOCITY_TEXT = "Hôm nay bạn chuyển nhiều lần hơn thường lệ."
_TEXT = {
    "amount": AMOUNT_TEXT,
    "balance": BALANCE_TEXT,
    "timing": TIMING_TEXT,
    "velocity": VELOCITY_TEXT,
}

_CACHED: HabitModel | None = None
_POP: Population | None = None


def reason_text(group: str | None, feature: str | None, *, extreme: bool = False) -> str:
    if extreme:
        return AMOUNT_TEXT
    if group == "amount" and feature == WEEK_FEATURE:
        return WEEK_TEXT
    return _TEXT.get(group or "", "")


def hour_weekday(ts_us: int) -> tuple[int, int]:
    seconds = int(ts_us) // 1_000_000 + ICT_SHIFT_S
    hour = (seconds // 3600) % 24
    weekday = ((seconds // 86400) + 3) % 7
    return int(hour), int(weekday)


def day_id(ts_us: int) -> int:
    return (int(ts_us) // 1_000_000 + ICT_SHIFT_S) // 86400


def quality_of(count: int) -> str:
    if count >= QUALITY_HIGH:
        return "high"
    if count >= QUALITY_MEDIUM:
        return "medium"
    return "low"


def shrink(count: int, personal: float, population: float, prior: float = PRIOR) -> float:
    if count <= 0 or personal != personal:
        return float(population)
    weight = count / (count + prior)
    return weight * float(personal) + (1.0 - weight) * float(population)


def _median(values: list[float]) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _mad(values: list[float], center: float) -> float:
    if not values or center != center:
        return 0.0
    return _median([abs(item - center) for item in values])


def _clip(value: float) -> float:
    if value != value or value in {float("inf"), float("-inf")}:
        return 0.0
    return max(-CLIP, min(CLIP, float(value)))


def _known_payee(payee: str) -> bool:
    return bool(payee) and payee != "-"


HOLD_PREFIX = "f:habithold:"
CLEAR_DAYS = 30
DISPUTED = "d"


def hold_field(ts_us: int, payee: str, amount: int) -> str:
    return f"{int(ts_us)}|{payee}|{int(amount)}"


def _pointer(client, decision_id: str) -> tuple[str, str] | None:
    packed = client.get(f"{HOLD_PREFIX}id:{decision_id}")
    if not packed or "\t" not in str(packed):
        return None
    sender, field = str(packed).split("\t", 1)
    if not sender or not field:
        return None
    return sender, field


def mark_hold(client, sender: str, ts_us: int, payee: str, amount: int, decision_id: str) -> None:
    """Mức >= 1 hoặc đang trong episode. Khách bấm tiếp không đưa lệnh này vào baseline."""
    if client is None or not sender or not decision_id:
        return
    field = hold_field(ts_us, payee, amount)
    key = f"{HOLD_PREFIX}{sender}"
    client.set(f"{HOLD_PREFIX}id:{decision_id}", f"{sender}\t{field}")
    if str(client.hget(key, field) or "") in {"1", DISPUTED}:
        return
    client.hset(key, field, "0")


def dispute_hold(client, decision_id: str) -> None:
    if client is None or not decision_id:
        return
    found = _pointer(client, decision_id)
    if found is None:
        return
    sender, field = found
    client.hset(f"{HOLD_PREFIX}{sender}", field, DISPUTED)


def dispute_from_event(client, event: dict) -> None:
    """Khiếu nại hoặc báo cáo lừa đảo gắn decision_id. Không đoán lệnh nếu thiếu mã."""
    if client is None or not isinstance(event, dict):
        return
    decision_id = str(event.get("decision_id") or "")
    if not decision_id:
        return
    if event.get("type") == "complaint" or event.get("fraud_report") is True:
        dispute_hold(client, decision_id)


def _episode_open(client, sender: str, now_us: int) -> bool:
    raw = client.get(f"pol:v24:{sender}")
    if not raw:
        return False
    try:
        doc = json.loads(raw)
        expires = datetime.fromisoformat(str(doc.get("expires_at") or ""))
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    if not doc.get("episode_id"):
        return False
    if expires.tzinfo is None:
        from engine.decide import ICT

        expires = expires.replace(tzinfo=ICT)
    now = datetime.fromtimestamp(int(now_us) / 1_000_000, expires.tzinfo)
    return now < expires


def verify_legitimate(client, decision_id: str, now_us: int) -> bool:
    """Ngân hàng xác minh sau khi episode đã đóng. Khách bấm tiếp không gọi hàm này."""
    if client is None or not decision_id:
        return False
    found = _pointer(client, decision_id)
    if found is None:
        return False
    sender, field = found
    if _episode_open(client, sender, now_us):
        return False
    client.hset(f"{HOLD_PREFIX}{sender}", field, "1")
    return True


def _hold_ts(field: str) -> int | None:
    try:
        return int(str(field).split("|", 1)[0])
    except ValueError:
        return None


def _blocked(holds: dict, now_us: int) -> set[str]:
    cutoff = int(now_us) - CLEAR_DAYS * DAY_US
    blocked = set()
    for field, value in (holds or {}).items():
        flag = str(value)
        if flag == "1":
            continue
        if flag == "0":
            stamp = _hold_ts(str(field))
            if stamp is not None and stamp <= cutoff:
                continue
        blocked.add(str(field))
    return blocked


@dataclass
class Transfer:
    ts_us: int
    payee: str
    amount: int
    balance: int
    in_baseline: bool = True


@dataclass
class Raw:
    n: int
    n90: int
    window: str
    n_base: int
    personal_median: float
    personal_max: float
    week_sum: float
    week_median: float
    ratio: float | None
    ratios: list[float]
    hour: int
    weekday: int
    hour_n: int
    weekday_n: int
    count_24h: int
    daily_rate: float
    unseen_24h: int
    unseen_rate: float
    max_12m: float


@dataclass
class Population:
    prior: float = PRIOR
    median_amount: float = 1.0
    max_amount_ref: float = 1.0
    typical_7d: float = 0.0
    balance_median: float = 0.0
    balance_mad: float = 1.0
    hour_p: list[float] = field(default_factory=lambda: [1.0 / 24.0] * 24)
    weekday_p: list[float] = field(default_factory=lambda: [1.0 / 7.0] * 7)
    typical_daily: float = 1.0
    typical_unseen_daily: float = 0.0
    feature_median: dict = field(default_factory=dict)
    feature_mad: dict = field(default_factory=dict)
    if_threshold: float = 0.0
    z_threshold: float = 0.0

    def as_dict(self) -> dict:
        return {
            "prior": self.prior,
            "median_amount": self.median_amount,
            "max_amount_ref": self.max_amount_ref,
            "typical_7d": self.typical_7d,
            "balance_median": self.balance_median,
            "balance_mad": self.balance_mad,
            "hour_p": list(self.hour_p),
            "weekday_p": list(self.weekday_p),
            "typical_daily": self.typical_daily,
            "typical_unseen_daily": self.typical_unseen_daily,
            "feature_median": dict(self.feature_median),
            "feature_mad": dict(self.feature_mad),
            "if_threshold": self.if_threshold,
            "z_threshold": self.z_threshold,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> Population:
        return cls(
            prior=float(raw.get("prior", PRIOR)),
            median_amount=float(raw["median_amount"]),
            max_amount_ref=float(raw["max_amount_ref"]),
            typical_7d=float(raw["typical_7d"]),
            balance_median=float(raw["balance_median"]),
            balance_mad=float(raw["balance_mad"]),
            hour_p=[float(item) for item in raw["hour_p"]],
            weekday_p=[float(item) for item in raw["weekday_p"]],
            typical_daily=float(raw["typical_daily"]),
            typical_unseen_daily=float(raw["typical_unseen_daily"]),
            feature_median={key: float(value) for key, value in raw["feature_median"].items()},
            feature_mad={key: float(value) for key, value in raw["feature_mad"].items()},
            if_threshold=float(raw["if_threshold"]),
            z_threshold=float(raw["z_threshold"]),
        )


class Ledger:
    """Sổ đi, đã xếp theo thời gian. snapshot không ghi lệnh đang chấm."""

    def __init__(self) -> None:
        self.ts: list[int] = []
        self.payee: list[str] = []
        self.amount: list[int] = []
        self.balance: list[int] = []
        self.in_base: list[bool] = []
        self.hour: list[int] = []
        self.weekday: list[int] = []
        self.seen: set[str] = set()
        self.new_ts: list[int] = []
        self.new_payee: list[str] = []
        self.new_amount: list[int] = []
        self.week_at: list[float] = []
        self.new_count = 0
        self.days: set[int] = set()

    def _week_sum(self, ts_us: int, payee: str, amount: int) -> float:
        start = bisect.bisect_left(self.new_ts, ts_us - 7 * DAY_US)
        total = float(sum(self.new_amount[start:]))
        if _known_payee(payee) and payee not in self.seen:
            total += float(amount)
        return total

    def add(self, item: Transfer) -> None:
        stamp = int(item.ts_us)
        payee = str(item.payee or "")
        amount = int(item.amount)
        week = self._week_sum(stamp, payee, amount)
        self.week_at.append(week)
        if _known_payee(payee) and payee not in self.seen:
            self.seen.add(payee)
            self.new_ts.append(stamp)
            self.new_payee.append(payee)
            self.new_amount.append(amount)
            self.new_count += 1
        hour, weekday = hour_weekday(stamp)
        self.ts.append(stamp)
        self.payee.append(payee)
        self.amount.append(amount)
        self.balance.append(int(item.balance))
        self.in_base.append(bool(item.in_baseline))
        self.hour.append(hour)
        self.weekday.append(weekday)
        self.days.add(day_id(stamp))

    def snapshot(self, ts_us: int, payee: str, amount: int, balance: int) -> Raw:
        stamp = int(ts_us)
        cut90 = stamp - 90 * DAY_US
        cut365 = stamp - 365 * DAY_US
        n90 = len(self.ts) - bisect.bisect_left(self.ts, cut90)
        window = "90d" if n90 >= WINDOW_MIN else "12m"
        start = cut90 if window == "90d" else cut365
        left = bisect.bisect_left(self.ts, start)
        base = [index for index in range(left, len(self.ts)) if self.in_base[index]]
        amounts = [float(self.amount[index]) for index in base]
        n = len(self.ts) - left
        n_base = len(base)
        ratios = [self.amount[index] / self.balance[index] for index in base if self.balance[index] > 0]
        hour, weekday = hour_weekday(stamp)
        hour_n = sum(1 for item in self.hour[left:] if item == hour)
        weekday_n = sum(1 for item in self.weekday[left:] if item == weekday)
        days = {day_id(item) for item in self.ts[left:]}
        daily = float(n) / float(len(days)) if days else float("nan")
        new_left = bisect.bisect_left(self.new_ts, start)
        unseen_rate = float(len(self.new_ts) - new_left) / float(len(days)) if days else float("nan")
        day_left = bisect.bisect_left(self.new_ts, stamp - DAY_US)
        unseen_24h = len(set(self.new_payee[day_left:]))
        max_left = bisect.bisect_left(self.ts, cut365)
        year = [self.amount[index] for index in range(max_left, len(self.ts)) if self.in_base[index]]
        max_12m = max(year) if year else 0
        ratio = float(amount) / float(balance) if balance and balance > 0 else None
        past_weeks = [self.week_at[index] for index in base]
        return Raw(
            n=n,
            n90=n90,
            window=window,
            n_base=n_base,
            personal_median=_median(amounts),
            personal_max=max(amounts) if amounts else float("nan"),
            week_sum=self._week_sum(stamp, str(payee or ""), int(amount)),
            week_median=_median([float(item) for item in past_weeks]),
            ratio=ratio,
            ratios=[float(item) for item in ratios],
            hour=hour,
            weekday=weekday,
            hour_n=hour_n,
            weekday_n=weekday_n,
            count_24h=(len(self.ts) - bisect.bisect_left(self.ts, stamp - DAY_US)) + 1,
            daily_rate=daily,
            unseen_24h=unseen_24h,
            unseen_rate=unseen_rate,
            max_12m=int(max_12m),
        )


def features_from(raw: Raw, amount: int, population: Population) -> dict[str, float]:
    prior = float(population.prior)
    base_n = raw.n_base
    median_amount = shrink(base_n, raw.personal_median, population.median_amount, prior)
    max_amount = shrink(base_n, raw.personal_max, population.max_amount_ref, prior)
    typical_week = shrink(base_n, raw.week_median, population.typical_7d, prior)
    hour_p = population.hour_p[raw.hour] if 0 <= raw.hour < len(population.hour_p) else 1.0 / 24.0
    weekday_p = population.weekday_p[raw.weekday] if 0 <= raw.weekday < len(population.weekday_p) else 1.0 / 7.0
    hour_freq = (raw.hour_n + prior * hour_p) / (raw.n + prior)
    weekday_freq = (raw.weekday_n + prior * weekday_p) / (raw.n + prior)
    daily = shrink(raw.n, raw.daily_rate, population.typical_daily, prior)
    unseen = shrink(raw.n, raw.unseen_rate, population.typical_unseen_daily, prior)
    if raw.ratio is None:
        balance_z = 0.0
    else:
        balance_z = robust_z(
            float(raw.ratio),
            raw.ratios,
            float(population.balance_median),
            float(population.balance_mad),
            prior,
            0.5,
            "up",
        )
    values = {
        "log_amount_vs_median": math.log(max(int(amount), 1) / max(median_amount, 1.0)),
        "amount_vs_window_max": float(amount) / max(max_amount, 1.0),
        "week_unseen_amount_vs_typical": math.log1p(max(raw.week_sum, 0.0)) - math.log1p(max(typical_week, 0.0)),
        "balance_ratio_z": balance_z,
        "hour_rarity": -math.log(max(hour_freq, 1e-12)),
        "weekday_rarity": -math.log(max(weekday_freq, 1e-12)),
        "count_24h_vs_typical": math.log1p(max(raw.count_24h, 0)) - math.log1p(max(daily, 0.0)),
        "other_unseen_24h_vs_typical": math.log1p(max(raw.unseen_24h, 0)) - math.log1p(max(unseen, 0.0)),
    }
    return {name: _clip(values[name]) for name in FEATURES}


def vector_of(features: dict[str, float]) -> np.ndarray:
    return np.asarray([float(features[name]) for name in FEATURES], dtype=np.float64)


def profile_score(features: dict[str, float], population: Population) -> tuple[float, str]:
    best_name = FEATURES[0]
    best = 0.0
    for name in FEATURES:
        center = float(population.feature_median.get(name, 0.0))
        scale = max(float(population.feature_mad.get(name, 1.0)), 1e-6)
        score = (float(features[name]) - center) / (CONSISTENCY * scale)
        if score > best:
            best = score
            best_name = name
    return best, best_name


def extreme_amount(amount: int, max_12m: int) -> bool:
    if max_12m <= 0:
        return False
    return int(amount) >= EXTREME_MULTIPLE * int(max_12m) and int(amount) >= EXTREME_FLOOR


@dataclass
class Result:
    rare: bool | None
    money_rare: bool | None
    quality: str
    top_group: str | None
    top_feature: str | None
    extreme: bool
    method: str
    n: int
    n90: int
    window: str
    score: float | None = None

    @classmethod
    def unknown(cls) -> Result:
        return cls(None, None, "none", None, None, False, "none", 0, 0, "")


def _finish(raw: Raw, features: dict[str, float], amount: int, population: Population, score: float, top: str | None, method: str) -> Result:
    quality = quality_of(raw.n)
    extreme = extreme_amount(amount, raw.max_12m)
    group = GROUPS.get(top or "", None)
    threshold = population.z_threshold if method == "robust_z" else population.if_threshold
    rare = top is not None and score > threshold
    money = bool(rare and group in {"amount", "balance"} and quality in {"medium", "high"})
    if extreme:
        money = True
        if not rare:
            group = "amount"
            top = "amount_vs_window_max"
    return Result(
        rare=rare,
        money_rare=money,
        quality=quality,
        top_group=group,
        top_feature=top,
        extreme=extreme,
        method=method,
        n=raw.n,
        n90=raw.n90,
        window=raw.window,
        score=float(score),
    )


def _c_factor(samples: int) -> float:
    """Độ dài đường đi trung bình của một cây isolation. Cùng công thức với scikit-learn."""
    if samples <= 1:
        return 0.0
    if samples == 2:
        return 1.0
    return 2.0 * (math.log(samples - 1.0) + float(np.euler_gamma)) - 2.0 * (samples - 1.0) / samples


class HabitModel:
    def __init__(self, model, explainer, population: Population, version: str):
        self.model = model
        self.explainer = explainer
        self.population = population
        self.version = version
        self._depth_denom = len(model.estimators_) * _c_factor(int(model._max_samples))

    def score_one(self, features: dict[str, float]) -> float:
        """Cùng điểm với -decision_function cho một lệnh. Không mở joblib cho mỗi dòng."""
        row = np.asarray(vector_of(features), dtype=np.float32).reshape(1, -1)
        forest = self.model
        depth = 0.0
        for tree, lengths, averages in zip(forest.estimators_, forest._decision_path_lengths, forest._average_path_length_per_tree, strict=True):
            leaf = int(tree.apply(row, check_input=False)[0])
            depth += float(lengths[leaf] + averages[leaf] - 1.0)
        raw = 2.0 ** (-depth / self._depth_denom)
        return float(raw + float(forest.offset_))

    @classmethod
    def load(cls, directory: Path = ART) -> HabitModel:
        import joblib
        import shap

        spec = json.loads((directory / "model.json").read_text(encoding="utf-8"))
        if spec.get("model_version") != MODEL_VERSION:
            raise RuntimeError(f"habit version lệch {spec.get('model_version')}")
        if list(spec.get("features") or []) != list(FEATURES):
            raise RuntimeError("danh sách đặc trưng habit lệch")
        blob = (directory / "model.joblib").read_bytes()
        digest = hashlib.sha256(blob).hexdigest()
        if digest != spec.get("sha256"):
            raise RuntimeError("sha256 habit lệch")
        model = joblib.load(directory / "model.joblib")
        if list(getattr(model, "feature_names_in_", FEATURES)) not in (list(FEATURES),):
            names = list(getattr(model, "feature_names_in_", []))
            if names and names != list(FEATURES):
                raise RuntimeError("cột của IsolationForest lệch")
        explainer = shap.TreeExplainer(model)
        return cls(model, explainer, Population.from_dict(spec["population"]), str(spec["model_version"]))

    def explain(self, features: dict[str, float]) -> np.ndarray:
        row = _named(vector_of(features).reshape(1, -1))
        values = self.explainer.shap_values(row, check_additivity=False)
        if hasattr(values, "values"):
            values = values.values
        contrib = -np.asarray(values, dtype=float).reshape(-1)
        if contrib.shape != (len(FEATURES),):
            raise RuntimeError("shap habit lệch số cột")
        return contrib

    def anomaly(self, features: dict[str, float]) -> tuple[float, np.ndarray]:
        row = _named(vector_of(features).reshape(1, -1))
        score = float(-self.model.decision_function(row)[0])
        return score, self.explain(features)

    def top_feature(self, features: dict[str, float], contrib: np.ndarray) -> str | None:
        """Đặc trưng phía cao đóng góp mạnh nhất vào điểm bất thường. Phía thấp không tính."""
        best_name = None
        best = 0.0
        for index, name in enumerate(FEATURES):
            center = float(self.population.feature_median.get(name, 0.0))
            if float(features[name]) < center:
                continue
            weight = float(contrib[index])
            if weight > best:
                best = weight
                best_name = name
        return best_name


def load_population(directory: Path = ART) -> Population | None:
    path = directory / "model.json"
    if not path.is_file():
        return None
    spec = json.loads(path.read_text(encoding="utf-8"))
    if spec.get("model_version") != MODEL_VERSION:
        raise RuntimeError(f"habit version lệch {spec.get('model_version')}")
    return Population.from_dict(spec["population"])


def cached_population() -> Population | None:
    global _POP
    if _POP is None:
        _POP = load_population()
    return _POP


def apply_policy_thresholds(population: Population) -> Population:
    """Ngưỡng trong bank_policy.yaml là giá trị chỉnh được. Artifact chỉ ghi xuất xứ."""
    from engine.policy.v24 import threshold

    population.if_threshold = float(threshold("habit_score_above"))
    population.z_threshold = float(threshold("habit_profile_above"))
    return population


def _named(rows: np.ndarray):
    import pandas as pd

    return pd.DataFrame(np.asarray(rows, dtype=np.float64), columns=list(FEATURES))


def cached_model() -> HabitModel:
    global _CACHED
    if _CACHED is None:
        _CACHED = HabitModel.load()
    return _CACHED


def assess(history: list[Transfer], ts_us: int, payee: str, amount: int, balance: int, population: Population, model: HabitModel | None = None) -> Result:
    ledger = Ledger()
    for item in sorted(history, key=lambda row: int(row.ts_us)):
        if int(item.ts_us) >= int(ts_us):
            continue
        if int(item.amount) <= 0:
            continue
        ledger.add(item)
    raw = ledger.snapshot(int(ts_us), str(payee or ""), int(amount), int(balance))
    features = features_from(raw, int(amount), population)
    if quality_of(raw.n) == "low" or model is None:
        score, top = profile_score(features, population)
        return _finish(raw, features, int(amount), population, score, top if score > 0 else None, "robust_z")
    # Không có đặc trưng phía cao thì habit_rare không thể đúng, nên không chấm rừng và không giải thích.
    if not _high_side(features, population):
        return _finish(raw, features, int(amount), population, 0.0, None, "isolation_forest")
    if hasattr(model, "score_one"):
        score = model.score_one(features)
    else:
        row = _named(vector_of(features).reshape(1, -1))
        score = float(-model.model.decision_function(row)[0])
    if score <= population.if_threshold:
        return _finish(raw, features, int(amount), population, score, None, "isolation_forest")
    contrib = model.explain(features)
    return _finish(raw, features, int(amount), population, score, model.top_feature(features, contrib), "isolation_forest")


def _high_side(features: dict[str, float], population: Population) -> bool:
    for name in FEATURES:
        center = float(population.feature_median.get(name, 0.0))
        if float(features[name]) >= center:
            return True
    return False


def inspect_row(history: list[Transfer], ts_us: int, payee: str, amount: int, balance: int, population: Population, model: HabitModel | None = None) -> dict:
    """Cùng cổng với assess: TreeSHAP chỉ chạy khi lệnh có thể là habit_rare."""
    result = assess(history, ts_us, payee, amount, balance, population, model)
    ledger = Ledger()
    for item in sorted(history, key=lambda row: int(row.ts_us)):
        if int(item.ts_us) >= int(ts_us) or int(item.amount) <= 0:
            continue
        ledger.add(item)
    raw = ledger.snapshot(int(ts_us), str(payee or ""), int(amount), int(balance))
    features = features_from(raw, int(amount), population)
    typical = shrink(raw.n_base, raw.week_median, population.typical_7d, population.prior)
    return {
        "features": features,
        "personal_max": raw.personal_max,
        "week_sum": raw.week_sum,
        "week_median": raw.week_median,
        "typical_week": typical,
        "n": raw.n,
        "n_base": raw.n_base,
        "score": result.score,
        "top_feature": result.top_feature,
        "top_group": result.top_group,
        "rare": result.rare,
        "money_rare": result.money_rare,
        "quality": result.quality,
    }


def _parse_member(member: str) -> Transfer | None:
    parts = str(member).split("|")
    if len(parts) < 8 or parts[5] != "1":
        return None
    try:
        return Transfer(int(parts[0]), parts[2], int(parts[3]), int(parts[4]))
    except ValueError:
        return None


def read_redis(client, sender_hash: str, ts_us: int) -> list[Transfer]:
    meta = client.hgetall(f"f:meta:{sender_hash}") or {}
    customer = str(meta.get("customer") or "")
    accounts = set(client.smembers(f"f:cacc:{customer}")) if customer else set()
    accounts.add(sender_hash)
    start = int(ts_us) - 366 * DAY_US
    pipe = client.pipeline(transaction=False)
    ordered = sorted(accounts)
    for account in ordered:
        pipe.zrangebyscore(f"f:out:{account}", start, f"({int(ts_us)}")
        pipe.hgetall(f"{HOLD_PREFIX}{account}")
    found = []
    fetched = pipe.execute()
    for index in range(0, len(fetched), 2):
        blocked = _blocked(fetched[index + 1], int(ts_us))
        for member in fetched[index] or []:
            item = _parse_member(str(member))
            if item is None or item.amount <= 0:
                continue
            item.in_baseline = hold_field(item.ts_us, item.payee, item.amount) not in blocked
            found.append(item)
    found.sort(key=lambda item: item.ts_us)
    return found


def assess_live(client, sender_hash: str, payee_hash: str, amount: int, balance: int, ts_us: int) -> Result:
    try:
        population = cached_population()
        if population is None:
            return Result.unknown()
        apply_policy_thresholds(population)
        history = read_redis(client, sender_hash, int(ts_us))
        raw_n = _window_count(history, int(ts_us))
        model = cached_model() if raw_n >= QUALITY_MEDIUM else None
        return assess(history, int(ts_us), payee_hash, int(amount), int(balance), population, model)
    except Exception:
        log.warning("habit_failed", exc_info=True)
        return Result.unknown()


def collect_raws(customers: list[str], transfers: list[Transfer], wanted: list[bool]) -> tuple[list[int], list[Raw], list[int], list[float]]:
    """Một lượt theo khách. Chỉ lệnh wanted được chấm, và được chấm trước khi ghi vào sổ."""
    indices: list[int] = []
    raws: list[Raw] = []
    amounts: list[int] = []
    rates: list[float] = []
    start = 0
    count = len(transfers)
    while start < count:
        who = customers[start]
        end = start + 1
        while end < count and customers[end] == who:
            end += 1
        ledger = Ledger()
        used = False
        for index in range(start, end):
            item = transfers[index]
            if wanted[index]:
                indices.append(index)
                raws.append(ledger.snapshot(item.ts_us, item.payee, item.amount, item.balance))
                amounts.append(int(item.amount))
                used = True
            if int(item.amount) > 0:
                ledger.add(item)
        if used and ledger.days:
            rates.append(ledger.new_count / float(len(ledger.days)))
        start = end
    return indices, raws, amounts, rates


def read_outgoing():
    """Mọi chuyển đi trong observed/, theo khách. Không đọc truth."""
    import pandas as pd

    from engine.features.stream import TRANSFER_TYPES, to_us

    root = Path(__file__).resolve().parents[2] / "fides-sim" / "out" / "observed"
    accounts = pd.read_parquet(root / "accounts.parquet", columns=["account_id", "customer_id"])
    accounts["account_id"] = accounts["account_id"].astype(str)
    customer = dict(zip(accounts["account_id"], accounts["customer_id"].astype("string").fillna("").astype(str)))
    frame = pd.read_parquet(
        root / "transactions.parquet",
        columns=["tx_id", "ts", "from_account", "to_account", "amount", "tx_type", "session_id", "from_balance_before"],
    )
    frame["tx_type"] = frame["tx_type"].astype(str)
    frame = frame.loc[frame["tx_type"].isin(TRANSFER_TYPES)].copy()
    frame["from_account"] = frame["from_account"].astype(str)
    frame["to_account"] = frame["to_account"].astype("string").fillna("").astype(str)
    frame["session_id"] = frame["session_id"].astype("string").fillna("").astype(str)
    frame["customer"] = frame["from_account"].map(lambda item: customer.get(item) or f"acct:{item}")
    frame["ts_us"] = to_us(frame["ts"])
    frame["amount"] = frame["amount"].fillna(0).astype(np.int64)
    frame["balance"] = frame["from_balance_before"].fillna(0).astype(np.int64)
    frame = frame.loc[frame["amount"] > 0].sort_values(["customer", "ts_us", "tx_id"], kind="mergesort")
    return frame.reset_index(drop=True)


def score_sessions(session_ids: set[str]) -> dict[str, Result]:
    """Chấm đúng lệnh chuyển lớn nhất của từng phiên, trước khi ghi lệnh đó vào sổ."""
    population = cached_population()
    if population is None:
        return {}
    apply_policy_thresholds(population)
    full = read_outgoing()
    chosen = full.loc[full["session_id"].isin(session_ids)]
    if chosen.empty:
        return {}
    main = chosen.sort_values(["amount", "ts_us"], kind="mergesort").groupby("session_id", sort=False).tail(1)
    wanted_ids = set(main["tx_id"].astype(str))
    customers = full["customer"].tolist()
    transfers = [
        Transfer(int(ts), str(payee), int(amount), int(balance))
        for ts, payee, amount, balance in zip(full["ts_us"], full["to_account"], full["amount"], full["balance"], strict=True)
    ]
    wanted = [str(item) in wanted_ids for item in full["tx_id"].astype(str)]
    indices, raws, amounts, _rates = collect_raws(customers, transfers, wanted)
    session_of = full["session_id"].tolist()
    packed = [(index, raw, amount, features_from(raw, amount, population)) for index, raw, amount in zip(indices, raws, amounts, strict=True)]
    forest_at = [pos for pos, (_index, raw, _amount, _features) in enumerate(packed) if quality_of(raw.n) != "low"]
    scores: dict[int, float] = {}
    model = cached_model() if forest_at else None
    if model is not None and forest_at:
        block = _named(np.vstack([vector_of(packed[pos][3]) for pos in forest_at]))
        decided = -model.model.decision_function(block)
        for pos, score in zip(forest_at, decided, strict=True):
            scores[pos] = float(score)
    found: dict[str, Result] = {}
    for pos, (index, raw, amount, features) in enumerate(packed):
        if quality_of(raw.n) == "low" or model is None:
            score, top = profile_score(features, population)
            result = _finish(raw, features, amount, population, score, top if score > 0 else None, "robust_z")
        else:
            score = scores[pos]
            top = None
            if score > population.if_threshold and _high_side(features, population):
                top = model.top_feature(features, model.explain(features))
            result = _finish(raw, features, amount, population, score, top, "isolation_forest")
        found[str(session_of[index])] = result
    return found


def _window_count(history: list[Transfer], ts_us: int) -> int:
    cut90 = int(ts_us) - 90 * DAY_US
    cut365 = int(ts_us) - 365 * DAY_US
    stamps = [int(item.ts_us) for item in history if int(item.ts_us) < int(ts_us)]
    n90 = sum(1 for stamp in stamps if stamp >= cut90)
    if n90 >= WINDOW_MIN:
        return n90
    return sum(1 for stamp in stamps if stamp >= cut365)
