"""Tests for artifact discovery, ZIP handling, partial setups and the setup/check utilities.

    python -m unittest tests.test_artifacts -v
Uses the real artifacts in ./artifacts (or NIDS_ARTIFACT_DIR) as the source of valid files; everything else is temporary.
"""
import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import artifacts_util as au  # noqa: E402
import check_setup  # noqa: E402
import config  # noqa: E402
import setup_artifacts  # noqa: E402
from app import create_app  # noqa: E402
from predictor import Predictor, ValidationError  # noqa: E402

SRC = au.find_root(os.environ.get("NIDS_ARTIFACT_DIR", str(config.ARTIFACT_DIR)))


def copy_export(dst: Path, skip=()):
    """Copy the valid export into dst (optionally leaving some relative paths out)."""
    for p in SRC.rglob("*"):
        rel = p.relative_to(SRC).as_posix()
        if p.is_file() and rel not in skip and not rel.startswith("png/"):
            t = dst / rel
            t.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, t)


def make_zip(path: Path, prefix: str = ""):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in SRC.rglob("*"):
            if p.is_file() and not p.relative_to(SRC).as_posix().startswith("png/"):
                z.write(p, prefix + p.relative_to(SRC).as_posix())


def quiet(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn(*a, **k)
    return rc, buf.getvalue()


class DiscoveryTests(unittest.TestCase):
    def test_find_root_flat_wrapped_and_double_nested(self):
        for sub in ("", "nids_export", "nids_export/artifacts"):
            with tempfile.TemporaryDirectory() as t:
                copy_export(Path(t) / sub)
                self.assertEqual(au.find_root(t), (Path(t) / sub).resolve() if sub else Path(t), sub)

    def test_find_root_none_when_empty(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "README.txt").write_text("hi")
            self.assertIsNone(au.find_root(t))

    def test_zip_auto_extraction_removes_wrapper_folders(self):
        for prefix in ("", "nids_export/", "nids_export/artifacts/"):
            with tempfile.TemporaryDirectory() as t:
                art = Path(t) / "artifacts"; art.mkdir()
                make_zip(art / "nids_export.zip", prefix)
                root, note = au.prepare(art)
                self.assertEqual(root.resolve(), art.resolve(), prefix)        # flattened: no nested layout
                self.assertTrue((art / "models" / "ann_model.keras").is_file())
                self.assertIn("Extracted", note)

    def test_existing_install_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as t:
            art = Path(t); copy_export(art)
            (art / "metrics.json").write_text('{"marker": 1}')
            make_zip(art / "nids_export.zip")
            root, note = au.prepare(art)
            self.assertIsNone(note)
            self.assertIn("marker", (art / "metrics.json").read_text())

    def test_zip_slip_is_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            zp = Path(t) / "evil.zip"
            with zipfile.ZipFile(zp, "w") as z:
                z.writestr("metrics.json", "{}")
                z.writestr("../escaped.txt", "bad")
            dest = Path(t) / "dest"
            with self.assertRaises(ValueError):
                au.extract_zip(zp, dest)
            self.assertFalse((Path(t) / "escaped.txt").exists())

    def test_zip_that_is_not_an_export_is_ignored(self):
        with tempfile.TemporaryDirectory() as t:
            art = Path(t)
            with zipfile.ZipFile(art / "holiday_photos.zip", "w") as z:
                z.writestr("photo.txt", "x")
            root, note = au.prepare(art)
            self.assertIsNone(root)


class PredictorSetupTests(unittest.TestCase):
    def test_empty_folder_not_ready_and_inventory_lists_everything(self):
        with tempfile.TemporaryDirectory() as t:
            st = Predictor(t).status()
            self.assertFalse(st["ready"])
            self.assertFalse(any(r["present"] for r in st["inventory"]))
            self.assertEqual(len(st["missing_models"]), 5)

    def test_models_only_install_predicts_without_metrics(self):
        with tempfile.TemporaryDirectory() as t:
            copy_export(Path(t), skip=("metrics.json", "curves.json", "sample_flows.csv", "sample_template.csv"))
            p = Predictor(t)
            st = p.status()
            self.assertTrue(st["ready"])
            self.assertTrue(all(st["models"].values()), st["errors"])
            self.assertIn("metrics.json", " ".join(st["missing_evaluation"]))
            self.assertEqual(p.features, list(config.DEFAULT_FEATURES))           # taken from the scaler, not metrics
            app = create_app(artifact_dir=t, data_dir=tempfile.mkdtemp())
            html = app.test_client().get("/").get_data(as_text=True)
            self.assertIn("Partly set up", html)
            self.assertIn("metrics.json", html)

    def test_corrupt_model_is_reported_not_loaded(self):
        with tempfile.TemporaryDirectory() as t:
            copy_export(Path(t))
            (Path(t) / "models" / "nids_random_forest.pkl").write_bytes(b"this is not a pickle")
            p = Predictor(t)
            self.assertFalse(p.status()["models"]["random_forest"])
            self.assertTrue(p.errors["random_forest"])
            self.assertTrue(p.status()["models"]["ann"] and p.status()["models"]["logistic_regression"])
            with self.assertRaises(ValidationError):
                p.predict_proba("random_forest", None)

    def test_missing_scaler_blocks_only_the_scaled_models(self):
        with tempfile.TemporaryDirectory() as t:
            copy_export(Path(t), skip=("models/standard_scaler.pkl",))
            m = Predictor(t).status()["models"]
            self.assertEqual(m, {"ann": False, "random_forest": True, "logistic_regression": False,
                                 "logistic_regression_balanced": False})

    def test_demo_sample_in_project_folder_is_found(self):
        with tempfile.TemporaryDirectory() as t:
            copy_export(Path(t), skip=("sample_flows.csv",))
            self.assertIsNone(Predictor(t).sample_path())
            shutil.copy2(SRC / "sample_flows.csv", config.BASE_DIR / "nids_demo_sample.csv")
            try:
                self.assertEqual(Predictor(t).sample_path().name, "nids_demo_sample.csv")
            finally:
                (config.BASE_DIR / "nids_demo_sample.csv").unlink(missing_ok=True)

    def test_setup_required_page_shows_checklist(self):
        with tempfile.TemporaryDirectory() as t:
            html = create_app(artifact_dir=t, data_dir=tempfile.mkdtemp()).test_client().get("/predict").get_data(as_text=True)
            self.assertIn("Setup required", html)
            self.assertIn("models\\ann_model.keras", html)
            self.assertIn("setup_artifacts.ps1", html)


class SetupScriptTests(unittest.TestCase):
    def _run(self, *args):
        return quiet(setup_artifacts.main, list(args))

    def test_install_from_zip_found_by_search(self):
        with tempfile.TemporaryDirectory() as t:
            drive = Path(t) / "E" / "Udemy_ML" / "NIDS_Project.ipynb" / "nids_export"; drive.mkdir(parents=True)
            make_zip(drive / "nids_export.zip")
            dest = Path(t) / "app" / "artifacts"
            rc, out = self._run("--dest", str(dest), "--search-root", str(Path(t) / "E"))
            self.assertEqual(rc, 0, out)
            self.assertTrue((dest / "models" / "ann_model.keras").is_file())
            self.assertTrue((dest / "metrics.json").is_file())
            self.assertFalse((dest / "nids_export").exists())

    def test_install_from_export_folder_with_wrapper(self):
        with tempfile.TemporaryDirectory() as t:
            src = Path(t) / "x" / "nids_export"; copy_export(src)
            dest = Path(t) / "artifacts"
            rc, out = self._run("--dest", str(dest), "--source", str(src))
            self.assertEqual(rc, 0, out)
            self.assertTrue((dest / "models" / "standard_scaler.pkl").is_file())

    def test_install_from_models_only_folder(self):
        with tempfile.TemporaryDirectory() as t:
            models = Path(t) / "GitHub" / "Network-Intrusion-Detection-System" / "models"; models.mkdir(parents=True)
            for f in (SRC / "models").iterdir():
                shutil.copy2(f, models / f.name)
            dest = Path(t) / "artifacts"
            rc, out = self._run("--dest", str(dest), "--search-root", str(Path(t) / "GitHub"))
            self.assertEqual(rc, 0, out)                       # all 5 model files present = success
            self.assertIn("only the models", out)              # ... but it says metrics are missing
            self.assertTrue(Predictor(dest).status()["ready"])

    def test_nested_wrong_layout_is_flattened(self):
        with tempfile.TemporaryDirectory() as t:
            dest = Path(t) / "artifacts"
            copy_export(dest / "nids_export" / "artifacts")    # the mistake the user must never end up with
            rc, out = self._run("--dest", str(dest))
            self.assertEqual(rc, 0, out)
            self.assertTrue((dest / "models" / "ann_model.keras").is_file())
            self.assertFalse((dest / "nids_export").exists())

    def test_nothing_found_gives_clear_message(self):
        with tempfile.TemporaryDirectory() as t:
            rc, out = self._run("--dest", str(Path(t) / "artifacts"), "--search-root", t)
            self.assertEqual(rc, 1)
            self.assertIn("README.md", out)

    def test_bad_source_path(self):
        with tempfile.TemporaryDirectory() as t:
            rc, out = self._run("--dest", str(Path(t) / "a"), "--source", str(Path(t) / "does_not_exist.zip"))
            self.assertEqual(rc, 2)
            self.assertIn("does not exist", out)


class CheckSetupTests(unittest.TestCase):
    def test_full_install_passes_and_scores_the_sample(self):
        old = config.ARTIFACT_DIR
        config.ARTIFACT_DIR = SRC
        try:
            rc, out = quiet(check_setup.main, [])
        finally:
            config.ARTIFACT_DIR = old
        self.assertEqual(rc, 0, out)
        self.assertIn("all 4 models loaded", out)
        self.assertIn("recall", out)

    def test_empty_install_fails_with_next_steps(self):
        old = config.ARTIFACT_DIR
        with tempfile.TemporaryDirectory() as t:
            config.ARTIFACT_DIR = Path(t)
            try:
                rc, out = quiet(check_setup.main, [])
            finally:
                config.ARTIFACT_DIR = old
        self.assertEqual(rc, 1)
        self.assertIn("setup_artifacts.py", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
