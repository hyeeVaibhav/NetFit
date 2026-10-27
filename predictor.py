"""predictor.py - the single, reliable prediction interface of the NIDS app.

* Loads the scaler and every trained model ONCE (at start-up).
* Validates an uploaded CSV and turns it into the exact 10 features, in the exact order, the models were trained on.
* Predicts with any loaded model and builds a result table plus a run summary.

Nothing in this file invents results: probabilities come from the trained models, and every metric is computed
from the uploaded data (only if it contains a valid 0/1 `Label` column) or read from the exported metrics.json.
"""
from __future__ import annotations

import io
import json
import logging
import threading
import time
import warnings
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

import artifacts_util
import config

log = logging.getLogger("nids.predictor")


class ValidationError(Exception):
    """Raised for any problem with the uploaded data. `message` is safe to show to the user."""

    def __init__(self, message: str, details: list[str] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or []


# --------------------------------------------------------------------------------------
# artifact discovery
# --------------------------------------------------------------------------------------
def locate_artifact_root(base) -> Path | None:
    """Kept for compatibility: the folder holding metrics.json / models/ (searches up to 3 levels down)."""
    return artifacts_util.find_root(base)


# --------------------------------------------------------------------------------------
# label / metric helpers (also used for the live "Model Battle")
# --------------------------------------------------------------------------------------
def detect_labels(df: pd.DataFrame):
    """Return the 0/1 ground-truth vector if the table has a clean `Label` column, otherwise None."""
    if "Label" not in df.columns:
        return None
    y = pd.to_numeric(df["Label"], errors="coerce")
    if y.isna().any() or not set(np.unique(y)).issubset({0, 1}):
        return None
    return y.astype(int).to_numpy()


def confusion_metrics(y_true: np.ndarray, pred: np.ndarray) -> dict:
    y_true, pred = np.asarray(y_true).astype(int), np.asarray(pred).astype(int)
    tp = int(((pred == 1) & (y_true == 1)).sum())
    fp = int(((pred == 1) & (y_true == 0)).sum())
    fn = int(((pred == 0) & (y_true == 1)).sum())
    tn = int(((pred == 0) & (y_true == 0)).sum())

    def div(a, b):
        return float(a / b) if b else 0.0

    precision, recall = div(tp, tp + fp), div(tp, tp + fn)
    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "accuracy": div(tp + tn, tp + tn + fp + fn),
        "precision": precision, "recall": recall,
        "f1": div(2 * precision * recall, precision + recall),
        "fpr": div(fp, fp + tn), "fnr": div(fn, fn + tp),
    }


def summarize(result: pd.DataFrame, threshold: float) -> dict:
    """Run summary stored in SQLite and shown on the Results page."""
    n = len(result)
    pred = result["Prediction"].to_numpy().astype(int)
    p = result["P_attack"].to_numpy().astype(float)
    bins = np.linspace(0, 1, 21)
    s = {
        "n_rows": n, "n_attack": int(pred.sum()), "n_normal": int(n - pred.sum()),
        "attack_rate": float(pred.mean()) if n else 0.0,
        "threshold": float(threshold), "mean_probability": float(p.mean()) if n else 0.0,
        "histogram": {
            "bins": bins.tolist(),
            "normal": np.histogram(p[pred == 0], bins=bins)[0].tolist(),
            "attack": np.histogram(p[pred == 1], bins=bins)[0].tolist(),
        },
        "risk_counts": {k: int(v) for k, v in result["Risk"].value_counts().items() if k != "-"},
    }
    flagged = result[pred == 1]
    for col, key in (("L4_DST_PORT", "top_ports"), ("PROTOCOL", "top_protocols")):
        if col in result.columns and len(flagged):
            vc = flagged[col].value_counts().head(8)
            s[key] = [{"value": int(k), "count": int(v)} for k, v in vc.items()]
        else:
            s[key] = []

    y = detect_labels(result)
    s["has_labels"] = y is not None
    if y is not None:
        s["labels"] = confusion_metrics(y, pred)
        if "Attack" in result.columns:
            rows = []
            for at in sorted(set(result["Attack"].astype(str)) - {"Benign"}):
                mask = (result["Attack"].astype(str) == at).to_numpy()
                rows.append({"attack_type": at, "count": int(mask.sum()), "detected": int(pred[mask].sum()),
                             "recall": float(pred[mask].mean())})
            s["by_attack_type"] = rows
    return s


# --------------------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------------------
def read_csv_bytes(raw: bytes) -> pd.DataFrame:
    """Parse an uploaded CSV. Tolerates what Excel on Windows produces: UTF-8 BOM, CRLF, Windows-1252 text, ';' separators."""
    if not raw or not raw.strip():
        raise ValidationError("The uploaded file is empty.")
    df = None
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            df = pd.read_csv(io.BytesIO(raw), low_memory=False, encoding=encoding)
            # a ';'-separated file parses as ONE wide column name: retry with the right separator
            if df.shape[1] == 1 and ";" in str(df.columns[0]):
                df = pd.read_csv(io.BytesIO(raw), low_memory=False, encoding=encoding, sep=";")
            break
        except pd.errors.EmptyDataError:
            raise ValidationError("The uploaded file is empty.")
        except UnicodeDecodeError:
            continue
        except pd.errors.ParserError as e:
            raise ValidationError("The file could not be parsed as a CSV.", [str(e)[:200]])
    if df is None:
        raise ValidationError("The file is not a readable text CSV (it could not be decoded).")
    if df.shape[0] == 0:
        raise ValidationError("The CSV has a header but no data rows.")
    return df


class Predictor:
    """Loads every artifact once. A model is only reported as loaded after it has made a real test prediction."""

    def __init__(self, artifact_dir):
        self.requested_dir = Path(artifact_dir)
        self.root: Path | None = None
        self.auto_extracted: str | None = None
        self.metrics: dict = {}
        self.curves: dict = {}
        self.scaler = None
        self.models: dict = {}
        self.errors: dict = {}
        self.warnings: list[str] = []
        self.features = list(config.DEFAULT_FEATURES)
        self._lock = threading.Lock()
        self.loaded_at = time.time()
        self._load()

    # ---------------- loading ----------------
    def _read_json(self, name):
        path = self.root / name if self.root else None
        if not path or not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:  # corrupt file
            self.errors[name] = f"could not read {name}: {e}"
            return {}

    def _remember_warnings(self, caught):
        for w in caught:
            msg = f"{w.category.__name__}: {str(w.message)[:300]}"
            if msg not in self.warnings and ("version" in msg.lower() or "Inconsistent" in msg):
                self.warnings.append(msg)

    def _load_file(self, path: Path):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            if path.suffix == ".keras":
                import tensorflow as tf  # imported lazily: slow, and optional for the other models
                model = tf.keras.models.load_model(path, compile=False)
            else:
                model = joblib.load(path)
        self._remember_warnings(caught)
        return model

    def _load(self):
        self.root, self.auto_extracted = artifacts_util.prepare(self.requested_dir, extra_zip_dirs=(config.BASE_DIR,))
        if self.root is None:
            self.errors["artifacts"] = (f"No artifacts found in '{self.requested_dir}'. Put the exported nids_export folder "
                                        "or nids_export.zip there (see the checklist below).")
            return
        self.metrics = self._read_json("metrics.json")
        self.curves = self._read_json("curves.json")

        scaler_path = self.root / config.SCALER_FILE
        try:
            self.scaler = self._load_file(scaler_path) if scaler_path.is_file() else None
            if self.scaler is None:
                self.errors["scaler"] = f"file not found: {config.SCALER_FILE}"
        except Exception as e:
            self.scaler = None
            self.errors["scaler"] = f"{type(e).__name__}: {str(e)[:300]}"

        raw_names = getattr(self.scaler, "feature_names_in_", None)          # a NumPy array: never use it with `or`
        names = [str(n) for n in raw_names] if raw_names is not None else []
        from_metrics = self.metrics.get("dataset", {}).get("features")
        self.features = list(from_metrics or names or config.DEFAULT_FEATURES)
        if self.scaler is not None and names and names != self.features:
            self.errors["scaler"] = f"scaler was fitted on {names} but the app expects {self.features}"
            self.scaler = None

        for key, (name, rel, needs_scaler) in config.MODEL_FILES.items():
            path = self.root / rel
            if not path.is_file():
                self.errors[key] = f"file not found: {rel}"
                continue
            if needs_scaler and self.scaler is None:
                self.errors[key] = "needs standard_scaler.pkl, which is missing or could not be loaded"
                continue
            try:
                model = self._load_file(path)
                self._self_test(key, model)                       # a model counts as loaded only if it can really predict
                self.models[key] = model
                log.info("loaded and self-tested model %s", key)
            except Exception as e:
                self.errors[key] = f"{type(e).__name__}: {str(e)[:300]}"
                log.error("could not load %s: %s", key, e)

    def _proba_with(self, model, key: str, X: pd.DataFrame) -> np.ndarray:
        """The one place where a model turns features into P(attack)."""
        needs_scaler = config.MODEL_FILES[key][2]
        # Scaled models were trained on plain NumPy arrays; the Random Forest was trained on a named DataFrame.
        data = self.scaler.transform(X) if needs_scaler else X
        if key == "ann":
            p = model.predict(np.asarray(data, dtype="float32"), batch_size=4096, verbose=0).ravel()
        else:
            p = model.predict_proba(data)[:, 1]
        return np.clip(np.asarray(p, dtype=float), 0.0, 1.0)

    def _self_test(self, key: str, model):
        probe = pd.DataFrame([[0.0] * len(self.features), [1.0] * len(self.features)], columns=self.features)
        p = self._proba_with(model, key, probe)
        if p.shape != (2,) or not np.isfinite(p).all():
            raise RuntimeError(f"self-test gave an invalid output: {p!r}")

    # ---------------- information for the UI ----------------
    def display_name(self, key):
        entry = self.metrics.get("models", {}).get(key)
        return (entry or {}).get("name") or config.MODEL_FILES.get(key, (key,))[0]

    def catalog(self):
        out = []
        for key, (name, _, _) in config.MODEL_FILES.items():
            saved = self.metrics.get("models", {}).get(key, {}).get("metrics")
            out.append({"key": key, "name": self.display_name(key), "loaded": key in self.models,
                        "error": self.errors.get(key), "default_threshold": config.DEFAULT_THRESHOLD,
                        "saved_metrics": saved})
        return out

    def tuned_ann_threshold(self):
        return float(self.metrics.get("meta", {}).get("tuned_ann_threshold", 0.7))

    def status(self):
        inv = artifacts_util.inventory(self.root)
        return {
            "artifact_dir": str(self.requested_dir),
            "artifact_root": str(self.root) if self.root else None,
            "artifacts_found": self.root is not None,
            "auto_extracted": self.auto_extracted,
            "metrics_loaded": bool(self.metrics), "curves_loaded": bool(self.curves),
            "scaler_loaded": self.scaler is not None,
            "models": {k: (k in self.models) for k in config.MODEL_FILES},
            "errors": self.errors,
            "warnings": self.warnings,
            "inventory": inv,
            "missing_models": [r["path"] for r in inv if r["group"] == "model" and not r["present"]],
            "missing_evaluation": [r["path"] for r in inv if r["group"] == "evaluation" and not r["present"]],
            "missing_optional": [r["path"] for r in inv if r["group"] == "optional" and not r["present"]],
            "ready": bool(self.models),
            "sample_available": self.sample_path() is not None,
            "template_available": self.template_path() is not None,
            "features": self.features,
        }

    def sample_path(self):
        """sample_flows.csv from the export (or a nids_demo_sample.csv placed in the artifacts or project folder)."""
        dirs = [d for d in (self.root, self.requested_dir, config.BASE_DIR) if d]
        for name in ("sample_flows.csv", "nids_demo_sample.csv"):
            for d in dirs:
                p = Path(d) / name
                if p.is_file() and p.stat().st_size > 0:
                    return p
        return None

    def template_path(self):
        p = self.root / "sample_template.csv" if self.root else None
        return p if p and p.exists() else None

    # ---------------- validation ----------------
    def validate(self, df: pd.DataFrame):
        """Return (clean_frame, X). `clean_frame` keeps extra columns (IPs, Label, Attack); X is the model input."""
        if df is None or df.shape[0] == 0:
            raise ValidationError("The CSV has no data rows.")
        if df.shape[0] > config.MAX_ROWS:
            raise ValidationError(f"The file has {df.shape[0]:,} rows; the limit is {config.MAX_ROWS:,}.")

        df = df.copy()
        df.columns = [str(c).strip() for c in df.columns]
        lower = {c.lower(): c for c in df.columns}
        rename = {lower[f.lower()]: f for f in self.features if f.lower() in lower and lower[f.lower()] != f}
        for opt in ("Label", "Attack"):                       # optional columns, tolerate other capitalisation
            if opt.lower() in lower and lower[opt.lower()] != opt and opt not in df.columns:
                rename[lower[opt.lower()]] = opt
        df = df.rename(columns=rename)

        missing = [f for f in self.features if f not in df.columns]
        if missing:
            raise ValidationError(
                f"{len(missing)} required column(s) are missing: {', '.join(missing)}.",
                [f"Required columns (in any order): {', '.join(self.features)}",
                 f"Columns found in your file: {', '.join(map(str, df.columns[:25]))}"])

        X = df[self.features].apply(pd.to_numeric, errors="coerce")
        bad = X.isna()
        if bad.any().any():
            cols = [c for c in self.features if bad[c].any()]
            first = [int(i) + 2 for i in np.flatnonzero(bad.any(axis=1))[:5]]   # +2: header line + 1-based rows
            raise ValidationError(
                f"{int(bad.any(axis=1).sum()):,} row(s) contain missing or non-numeric values in: {', '.join(cols)}.",
                [f"First problem rows (line numbers in the CSV): {', '.join(map(str, first))}"])
        if not np.isfinite(X.to_numpy(dtype=float)).all():
            raise ValidationError("The feature columns contain infinite values.")
        return df, X.astype("float64")

    # ---------------- prediction ----------------
    def predict_proba(self, key: str, X: pd.DataFrame) -> np.ndarray:
        if key not in self.models:
            reason = self.errors.get(key, "model is not loaded")
            raise ValidationError(f"Model '{key}' is not available: {reason}")
        with self._lock:
            return self._proba_with(self.models[key], key, X)

    def predict(self, df_raw: pd.DataFrame, key: str, threshold: float | None = None):
        """Full pipeline for one model. Returns (result_table, summary)."""
        thr = config.DEFAULT_THRESHOLD if threshold is None else float(threshold)
        if not (0.0 < thr < 1.0):
            raise ValidationError("The threshold must be between 0 and 1 (exclusive).")
        df, X = self.validate(df_raw)
        p = self.predict_proba(key, X)
        result = self.build_result(df, p, thr)
        return result, summarize(result, thr)

    @staticmethod
    def build_result(df: pd.DataFrame, p: np.ndarray, thr: float) -> pd.DataFrame:
        pred = (p >= thr).astype(int)
        out = df.copy()
        out.insert(0, "row_id", np.arange(1, len(out) + 1))
        out["P_attack"] = np.round(p, 6)
        out["Prediction"] = pred
        out["Verdict"] = np.where(pred == 1, "Attack", "Normal")
        out["Confidence"] = np.round(np.where(pred == 1, p, 1 - p), 6)
        out["Risk"] = np.select([pred == 0, p >= 0.9, p >= 0.7], ["-", "High", "Medium"], default="Low")
        return out

    def battle(self, df_raw: pd.DataFrame, thresholds: dict | None = None):
        """Run every loaded model on the same data. Metrics are computed only if the data has a valid Label column."""
        df, X = self.validate(df_raw)
        y = detect_labels(df)
        results = []
        for key in config.MODEL_FILES:
            if key not in self.models:
                continue
            thr = float((thresholds or {}).get(key, config.DEFAULT_THRESHOLD))
            t0 = time.perf_counter()
            p = self.predict_proba(key, X)
            ms = (time.perf_counter() - t0) * 1000
            pred = (p >= thr).astype(int)
            row = {"key": key, "name": self.display_name(key), "threshold": thr, "flagged": int(pred.sum()),
                   "flag_rate": float(pred.mean()), "ms": round(ms, 1)}
            if y is not None:
                row["metrics"] = confusion_metrics(y, pred)
            results.append(row)
        return {"n_rows": int(len(df)), "has_labels": y is not None,
                "true_attacks": int(y.sum()) if y is not None else None, "models": results}
