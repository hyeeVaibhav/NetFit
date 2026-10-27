"""check_setup.py - verify that the app can load every model and predict, BEFORE you start the web server.

    python check_setup.py                         check the artifacts
    python check_setup.py --csv nids_demo_sample.csv     also run your CSV through every loaded model

Exit code 0 = all four models loaded and predicted; 1 = something needs fixing (the output says what).
"""
from __future__ import annotations

import argparse
import importlib
import platform
import sys
from pathlib import Path

import config


def version(mod: str) -> str:
    try:
        return getattr(importlib.import_module(mod), "__version__", "installed")
    except Exception as e:  # noqa: BLE001
        return f"NOT INSTALLED ({type(e).__name__})"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", help="a CSV to validate and score with every loaded model")
    a = ap.parse_args(argv)

    print("=" * 66)
    print(" NIDS setup check")
    print("=" * 66)
    print(f" Python      {platform.python_version()}  ({sys.executable})")
    for m in ("flask", "pandas", "numpy", "sklearn", "joblib", "tensorflow"):
        print(f" {m:<11} {version(m)}")
    print(f" Artifacts   {config.ARTIFACT_DIR}")

    from predictor import Predictor, ValidationError, read_csv_bytes   # imported late: loading TensorFlow is slow
    print("\nLoading models (TensorFlow can take 10-30 seconds) ...")
    p = Predictor(config.ARTIFACT_DIR)
    st = p.status()

    if st["auto_extracted"]:
        print(" ", st["auto_extracted"])
    print("\nFiles:")
    for r in st["inventory"]:
        mark = "OK     " if r["present"] else ("MISSING" if r["group"] != "optional" else "missing")
        print(f"  [{mark}] {r['path']:<45} {r['label']}")

    print("\nModels (a model is LOADED only after it made a real test prediction):")
    for m in p.catalog():
        if m["loaded"]:
            print(f"  [LOADED     ] {m['name']}")
        else:
            print(f"  [NOT LOADED ] {m['name']}: {m['error']}")
    for k, v in st["errors"].items():
        if k not in {m["key"] for m in p.catalog()}:
            print(f"  [PROBLEM    ] {k}: {v}")
    if st["warnings"]:
        print("\nLibrary version warnings (a model made with a different library version may misbehave):")
        for w in st["warnings"]:
            print("  -", w)

    # ---- optional: run a CSV through everything ----
    csv_path = Path(a.csv) if a.csv else p.sample_path()
    if csv_path and p.models:
        print(f"\nScoring {csv_path} with every loaded model:")
        try:
            df = read_csv_bytes(Path(csv_path).read_bytes())
            res = p.battle(df)
            print(f"  {res['n_rows']:,} flows" + (f", {res['true_attacks']:,} real attacks (from the Label column)" if res["has_labels"] else ", no Label column"))
            for m in res["models"]:
                line = f"  {m['name']:<30} flagged {m['flagged']:>6,}"
                if "metrics" in m:
                    line += f" | recall {m['metrics']['recall']:.3f} | precision {m['metrics']['precision']:.3f} | missed {m['metrics']['fn']:,}"
                print(line)
        except ValidationError as e:
            print("  CSV problem:", e.message)
            for d in e.details:
                print("   ", d)
            return 1
    elif a.csv:
        print(f"\nCannot score {a.csv}: no model is loaded.")

    n_ok = sum(st["models"].values())
    print("\n" + "-" * 66)
    if n_ok == len(config.MODEL_FILES):
        print(f" RESULT: all {n_ok} models loaded.")
        if st["missing_evaluation"]:
            print(" Note: metrics.json / curves.json missing -> Dashboard KPIs, Why ANN and Model Battle will be empty.")
            print("       Create them with the recovery cell (README.md, section 3).")
        print(" Next:   python app.py     then open http://127.0.0.1:5000")
        return 0
    print(f" RESULT: {n_ok} of {len(config.MODEL_FILES)} models loaded. Fix the items marked MISSING / NOT LOADED above.")
    print(" Files missing?  python setup_artifacts.py        Export gone?  see README.md, section 3.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
