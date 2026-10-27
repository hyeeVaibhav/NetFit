"""insights.py - plain-English findings generated from metrics.json.

Every sentence is built from the saved evaluation numbers, so the text can never disagree with the charts and nothing
is hard-coded. If the numbers change (for example after re-running the notebook), the wording updates by itself.
"""
from __future__ import annotations

BASE_MODELS = ("logistic_regression", "logistic_regression_balanced", "ann", "random_forest")


def _pct(v: float) -> str:
    return f"{v * 100:.2f}%"


def _rank(values: dict, key: str, higher_is_better: bool = True) -> int:
    order = sorted(values, key=lambda k: values[k], reverse=higher_is_better)
    return order.index(key) + 1


def build_insights(metrics: dict) -> list[dict]:
    models = metrics.get("models", {})
    keys = [k for k in BASE_MODELS if k in models]
    if not keys:
        return []
    name = {k: models[k]["name"] for k in keys}
    m = {k: models[k]["metrics"] for k in keys}
    out: list[dict] = []

    # 1. class imbalance
    ds = metrics.get("dataset", {})
    counts = ds.get("test_label_counts") or ds.get("label_counts")
    if counts and (counts.get("benign", 0) + counts.get("attack", 0)):
        total = counts["benign"] + counts["attack"]
        atk, ben = counts["attack"] / total, counts["benign"] / total
        out.append({"id": "imbalance", "tone": "info", "title": "Attacks are rare",
                    "text": f"Only {_pct(atk)} of the test flows are attacks. A model that always answers 'Normal' would "
                            f"already reach {_pct(ben)} accuracy, so accuracy alone cannot judge an intrusion detector."})

    # 2. the accuracy trap
    trap = max(keys, key=lambda k: m[k]["accuracy"] - m[k]["recall"])
    if m[trap]["accuracy"] - m[trap]["recall"] > 0.3:
        t = m[trap]
        out.append({"id": "trap", "tone": "warn", "title": "The accuracy trap",
                    "text": f"{name[trap]} reaches {_pct(t['accuracy'])} accuracy but detects only {_pct(t['recall'])} of the "
                            f"attacks ({t['fn']:,} missed). High accuracy hid a detector that rarely detects."})

    # 3. recall leader
    rec = {k: m[k]["recall"] for k in keys}
    top = max(rec, key=rec.get)
    t = m[top]
    out.append({"id": "recall_leader", "tone": "good", "title": "Highest attack detection",
                "text": f"{name[top]} has the highest recall: {_pct(t['recall'])}. It missed {t['fn']:,} of "
                        f"{t['tp'] + t['fn']:,} attacks, and raised {t['fp']:,} false alarms."})

    # 4. who wins the other columns
    leaders = {
        "accuracy": max(keys, key=lambda k: m[k]["accuracy"]),
        "precision": max(keys, key=lambda k: m[k]["precision"]),
        "F1 score": max(keys, key=lambda k: m[k]["f1"]),
        "fewest false alarms": min(keys, key=lambda k: m[k]["fp"]),
    }
    by_model: dict[str, list[str]] = {}
    for metric, k in leaders.items():
        by_model.setdefault(k, []).append(metric)
    parts = [f"{name[k]} leads on {', '.join(v)}" for k, v in by_model.items()]
    out.append({"id": "other_leaders", "tone": "info", "title": "Who wins the other columns",
                "text": "; ".join(parts) + "."})

    # 5. where the ANN stands (honest)
    if "ann" in m:
        n = len(keys)
        r_rec = _rank({k: m[k]["recall"] for k in keys}, "ann")
        r_f1 = _rank({k: m[k]["f1"] for k in keys}, "ann")
        r_pre = _rank({k: m[k]["precision"] for k in keys}, "ann")
        out.append({"id": "ann_rank", "tone": "info", "title": "Where the ANN stands",
                    "text": f"Among {n} models the ANN ranks #{r_rec} on recall, #{r_f1} on F1 and #{r_pre} on precision."})
        not_best = [mt for mt, k in leaders.items() if k != "ann" and mt != "fewest false alarms"]
        if not_best:
            out.append({"id": "honest", "tone": "warn", "title": "The honest trade-off",
                        "text": "The ANN is not the best on every metric. Its case is high detection plus a probability "
                                "output whose threshold can be tuned, not winning every column. "
                                f"It trails the leaders on: {', '.join(not_best)}."})

    # 6. threshold trade-off from the saved tuned-threshold evaluation
    if "ann" in m and "ann_tuned" in models:
        a, b = m["ann"], models["ann_tuned"]["metrics"]
        out.append({"id": "threshold", "tone": "info", "title": "What the ANN threshold does",
                    "text": f"Moving the ANN threshold from {a['threshold']:.2f} to {b['threshold']:.2f} changes recall from "
                            f"{_pct(a['recall'])} to {_pct(b['recall'])} (missed attacks {a['fn']:,} to {b['fn']:,}) and false "
                            f"alarms from {a['fp']:,} to {b['fp']:,}. Sensitivity is a dial, not a fixed property."})
    return out
