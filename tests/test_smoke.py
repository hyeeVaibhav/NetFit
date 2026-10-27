"""End-to-end tests for the NIDS app (backend + API + pages).

Run from the nids_app folder:
    python -m unittest tests.test_smoke -v

The tests use the real exported artifacts in ./artifacts (or NIDS_ARTIFACT_DIR) and a temporary database, so your
history is never touched.
"""
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from app import create_app  # noqa: E402

ART = os.environ.get("NIDS_ARTIFACT_DIR", str(config.ARTIFACT_DIR))


class NidsAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.app = create_app(artifact_dir=ART, data_dir=cls._tmp.name)
        cls.client = cls.app.test_client()
        cls.pred = cls.app.extensions["nids"]["predictor"]
        cls.features = cls.pred.features
        cls.sample = pd.read_csv(cls.pred.sample_path())

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    # ----------------------------------------------------------- helpers
    def post_csv(self, df_or_text, name="test.csv", **form):
        text = df_or_text if isinstance(df_or_text, (str, bytes)) else df_or_text.to_csv(index=False)
        data = text.encode() if isinstance(text, str) else text
        payload = {"file": (io.BytesIO(data), name), **form}
        return self.client.post("/api/predict", data=payload, content_type="multipart/form-data")

    # ----------------------------------------------------------- health and info
    def test_health_all_models_loaded(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200, r.get_json())
        j = r.get_json()
        self.assertEqual(j["status"], "ok")
        self.assertTrue(all(j["models"].values()), j["errors"])
        self.assertTrue(j["metrics_loaded"] and j["curves_loaded"] and j["sample_available"])

    def test_info_endpoints(self):
        self.assertEqual(self.client.get("/api/metrics").status_code, 200)
        self.assertEqual(self.client.get("/api/curves").status_code, 200)
        self.assertGreater(len(self.client.get("/api/insights").get_json()["insights"]), 3)
        models = self.client.get("/api/models").get_json()["models"]
        self.assertEqual({m["key"] for m in models}, set(config.MODEL_FILES))

    def test_sample_and_template_downloads(self):
        self.assertEqual(self.client.get("/api/sample").status_code, 200)
        t = self.client.get("/api/template")
        self.assertEqual(t.status_code, 200)
        self.assertEqual(t.data.decode().splitlines()[0].split(","), self.features)

    # ----------------------------------------------------------- predictions
    def test_predict_sample_every_model(self):
        for key in config.MODEL_FILES:
            r = self.client.post("/api/predict", data={"model": key, "sample": "1", "threshold": "0.5"})
            self.assertEqual(r.status_code, 200, (key, r.get_json()))
            j = r.get_json()
            s = j["summary"]
            self.assertEqual(s["n_rows"], len(self.sample))
            self.assertEqual(s["n_attack"] + s["n_normal"], s["n_rows"])
            self.assertTrue(s["has_labels"])
            lab = s["labels"]
            self.assertEqual(lab["tp"] + lab["fp"] + lab["fn"] + lab["tn"], s["n_rows"])
            self.assertEqual(lab["tp"] + lab["fp"], s["n_attack"])

    def test_predictions_match_direct_model_call(self):
        """Training-serving consistency: the app must give the same probabilities as calling the models by hand."""
        import tensorflow as tf
        root = self.pred.root
        X = self.sample[self.features]
        scaler = joblib.load(root / "models" / "standard_scaler.pkl")
        Xs = scaler.transform(X)
        expect = {
            "ann": tf.keras.models.load_model(root / "models" / "ann_model.keras", compile=False)
                       .predict(Xs.astype("float32"), verbose=0).ravel(),
            "random_forest": joblib.load(root / "models" / "nids_random_forest.pkl").predict_proba(X)[:, 1],
            "logistic_regression": joblib.load(root / "models" / "logistic_regression.pkl").predict_proba(Xs)[:, 1],
            "logistic_regression_balanced":
                joblib.load(root / "models" / "balanced_logistic_regression.pkl").predict_proba(Xs)[:, 1],
        }
        for key, direct in expect.items():
            r = self.client.post("/api/predict", data={"model": key, "sample": "1"})
            rid = r.get_json()["run_id"]
            got = pd.read_csv(io.BytesIO(self.client.get(f"/api/runs/{rid}/download").data))["P_attack"].to_numpy()
            self.assertTrue(np.allclose(got, direct, atol=1e-5), f"{key}: max diff {np.abs(got - direct).max()}")

    def test_column_order_case_and_extras_do_not_matter(self):
        base = self.sample[self.features].head(200)
        a = self.post_csv(base).get_json()
        shuffled = base[list(reversed(self.features))].copy()
        shuffled.columns = [(" " + c.lower() + " ") for c in shuffled.columns]   # lowercase + stray spaces
        shuffled["extra_note"] = "x"
        b = self.post_csv(shuffled).get_json()
        self.assertTrue(a["ok"] and b["ok"], b)
        ra = pd.read_csv(io.BytesIO(self.client.get(f"/api/runs/{a['run_id']}/download").data))["P_attack"]
        rb = pd.read_csv(io.BytesIO(self.client.get(f"/api/runs/{b['run_id']}/download").data))["P_attack"]
        self.assertTrue(np.allclose(ra, rb, atol=1e-6))
        self.assertFalse(b["summary"]["has_labels"])            # no Label column -> no invented metrics
        self.assertNotIn("labels", b["summary"])

    def test_threshold_changes_flag_count_monotonically(self):
        counts = []
        for thr in ("0.1", "0.5", "0.9"):
            r = self.client.post("/api/predict", data={"model": "ann", "sample": "1", "threshold": thr})
            counts.append(r.get_json()["summary"]["n_attack"])
        self.assertGreaterEqual(counts[0], counts[1])
        self.assertGreaterEqual(counts[1], counts[2])

    # ----------------------------------------------------------- invalid input
    def test_invalid_uploads(self):
        feats = self.features
        good = self.sample[feats].head(5)
        cases = {
            "no file": (self.client.post("/api/predict", data={"model": "ann"}), "No file"),
            "wrong extension": (self.post_csv(good, "data.txt"), "Only .csv"),
            "empty file": (self.post_csv("", "empty.csv"), "empty"),
            "header only": (self.post_csv(",".join(feats) + "\n", "h.csv"), "no data rows"),
            "missing columns": (self.post_csv(good.drop(columns=["IN_BYTES", "TCP_FLAGS"])), "missing: IN_BYTES, TCP_FLAGS"),
            "non numeric": (self.post_csv(good.astype(object).assign(IN_BYTES=["a", 1, 2, 3, 4])), "non-numeric"),
            "nan value": (self.post_csv(good.assign(OUT_PKTS=[1, np.nan, 3, 4, 5])), "missing or non-numeric"),
            "infinite": (self.post_csv(good.assign(IN_PKTS=[1, np.inf, 3, 4, 5])), "infinite"),
            "binary junk": (self.post_csv(bytes([0xff, 0xfe, 0x00, 0x81, 0x99] * 50), "junk.csv"), None),
            "bad threshold": (self.post_csv(good, threshold="1.5"), "threshold"),
            "text threshold": (self.post_csv(good, threshold="abc"), "number"),
            "unknown model": (self.post_csv(good, model="svm"), "Unknown model"),
        }
        for name, (resp, needle) in cases.items():
            self.assertEqual(resp.status_code, 400, (name, resp.get_json()))
            j = resp.get_json()
            self.assertFalse(j["ok"])
            if needle:
                self.assertIn(needle.lower(), (j["error"] + " ".join(j["details"])).lower(), name)

    def test_excel_style_csv_variants_are_accepted(self):
        """Files saved from Excel on Windows: BOM, CRLF, ';' separator, Windows-1252 text."""
        base = self.sample.head(30).copy()
        base["IPV4_SRC_ADDR"] = "caf\u00e9-host"                     # a non-ASCII character in a non-feature column
        ref = self.post_csv(base[self.features]).get_json()
        variants = {
            "utf8 bom": ("\ufeff" + base.to_csv(index=False)).encode("utf-8"),
            "crlf": base.to_csv(index=False, lineterminator="\r\n").encode("utf-8"),
            "semicolon": base.to_csv(index=False, sep=";").encode("utf-8"),
            "cp1252": base.to_csv(index=False).encode("cp1252"),
        }
        for name, raw in variants.items():
            r = self.post_csv(raw, f"{name}.csv")
            self.assertEqual(r.status_code, 200, (name, r.get_json()))
            self.assertEqual(r.get_json()["summary"]["n_rows"], 30, name)
        self.assertTrue(ref["ok"])

    def test_oversized_upload_rejected(self):
        old = self.app.config["MAX_CONTENT_LENGTH"]
        self.app.config["MAX_CONTENT_LENGTH"] = 2000
        try:
            r = self.post_csv(self.sample.head(300))
            self.assertEqual(r.status_code, 413)
            self.assertIn("limit", r.get_json()["error"])
        finally:
            self.app.config["MAX_CONTENT_LENGTH"] = old

    def test_row_limit(self):
        old = config.MAX_ROWS
        config.MAX_ROWS = 10
        try:
            r = self.post_csv(self.sample[self.features].head(50))
            self.assertEqual(r.status_code, 400)
            self.assertIn("limit", r.get_json()["error"])
        finally:
            config.MAX_ROWS = old

    # ----------------------------------------------------------- history, rows, download
    def test_history_rows_download_delete(self):
        rid = self.client.post("/api/predict", data={"model": "random_forest", "sample": "1"}).get_json()["run_id"]
        hist = self.client.get("/api/history").get_json()
        self.assertIn(rid, [r["id"] for r in hist["runs"]])

        run = self.client.get(f"/api/runs/{rid}").get_json()
        n, n_atk = run["n_rows"], run["n_attack"]

        page = self.client.get(f"/api/runs/{rid}/rows?page=1&size=25").get_json()
        self.assertEqual(page["total"], n)
        self.assertEqual(len(page["rows"]), 25)
        atk = self.client.get(f"/api/runs/{rid}/rows?filter=attack&size=200").get_json()
        self.assertEqual(atk["total"], n_atk)
        probs = [r[atk["columns"].index("P_attack")] for r in atk["rows"]]
        desc = self.client.get(f"/api/runs/{rid}/rows?filter=attack&sort=prob_desc&size=50").get_json()
        dp = [r[desc["columns"].index("P_attack")] for r in desc["rows"]]
        self.assertEqual(dp, sorted(dp, reverse=True))
        self.assertTrue(all(0 <= p <= 1 for p in probs))
        self.assertGreater(self.client.get(f"/api/runs/{rid}/rows?q=59.166").get_json()["total"], 0)

        same = self.client.get(f"/api/runs/{rid}/threshold?value={run['threshold']}").get_json()
        self.assertEqual(same["n_attack"], n_atk)                       # what-if at the same threshold = stored result
        stricter = self.client.get(f"/api/runs/{rid}/threshold?value=0.99").get_json()
        self.assertLessEqual(stricter["n_attack"], n_atk)
        self.assertEqual(self.client.get(f"/api/runs/{rid}/threshold?value=7").status_code, 400)

        dl = self.client.get(f"/api/runs/{rid}/download")
        self.assertEqual(dl.status_code, 200)
        self.assertIn("attachment", dl.headers["Content-Disposition"])
        out = pd.read_csv(io.BytesIO(dl.data))
        self.assertEqual(len(out), n)
        for col in ("P_attack", "Prediction", "Verdict", "Confidence", "Risk"):
            self.assertIn(col, out.columns)

        self.assertEqual(self.client.delete(f"/api/runs/{rid}").status_code, 200)
        self.assertEqual(self.client.get(f"/api/runs/{rid}").status_code, 404)
        self.assertEqual(self.client.get(f"/api/runs/{rid}/download").status_code, 404)
        self.assertEqual(self.client.delete(f"/api/runs/{rid}").status_code, 404)

    def test_clear_history(self):
        self.client.post("/api/predict", data={"model": "ann", "sample": "1"})
        r = self.client.delete("/api/history")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get("/api/history").get_json()["runs"], [])

    # ----------------------------------------------------------- model battle
    def test_battle(self):
        r = self.client.post("/api/battle", data={"sample": "1"})
        self.assertEqual(r.status_code, 200, r.get_json())
        j = r.get_json()
        self.assertEqual(len(j["models"]), 4)
        self.assertTrue(j["has_labels"])
        for m in j["models"]:
            met = m["metrics"]
            self.assertEqual(met["tp"] + met["fp"], m["flagged"])
            self.assertEqual(met["tp"] + met["fn"], j["true_attacks"])
        bad = self.client.post("/api/battle", data={"sample": "1", "thr_ann": "2"})
        self.assertEqual(bad.status_code, 400)

    # ----------------------------------------------------------- pages
    def test_pages_render(self):
        rid = self.client.post("/api/predict", data={"model": "ann", "sample": "1"}).get_json()["run_id"]
        for url, needle in [("/", "Dashboard"), ("/predict", "Upload"), (f"/results/{rid}", "Results"),
                            ("/history", "History"), ("/why-ann", "Why ANN"), ("/battle", "Model Battle"),
                            ("/present", "Presentation")]:
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200, url)
            self.assertIn(needle, r.get_data(as_text=True), url)
        self.assertEqual(self.client.get("/results/999999").status_code, 404)
        self.assertEqual(self.client.get("/nope").status_code, 404)
        self.assertEqual(self.client.get("/api/nope").get_json()["ok"], False)


class MissingArtifactsTests(unittest.TestCase):
    """The app must start and explain itself clearly when the artifacts are not installed yet."""

    def test_empty_artifacts_folder(self):
        with tempfile.TemporaryDirectory() as art, tempfile.TemporaryDirectory() as data:
            app = create_app(artifact_dir=art, data_dir=data)
            c = app.test_client()
            h = c.get("/api/health")
            self.assertEqual(h.status_code, 503)
            self.assertFalse(h.get_json()["artifacts_found"])
            r = c.post("/api/predict", data={"sample": "1"})
            self.assertEqual(r.status_code, 503)
            self.assertIn("No trained model", r.get_json()["error"])
            for url in ("/", "/predict", "/history", "/why-ann", "/battle", "/present"):
                self.assertEqual(c.get(url).status_code, 200, url)
            self.assertEqual(c.get("/api/metrics").status_code, 404)

    def test_one_extra_folder_level_is_found(self):
        with tempfile.TemporaryDirectory() as art, tempfile.TemporaryDirectory() as data:
            nested = Path(art) / "nids_export"
            (nested).mkdir()
            (nested / "metrics.json").write_text(json.dumps({"dataset": {"features": config.DEFAULT_FEATURES}}))
            app = create_app(artifact_dir=art, data_dir=data)
            self.assertTrue(app.test_client().get("/api/health").get_json()["artifacts_found"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
