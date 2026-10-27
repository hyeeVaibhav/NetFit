"""artifacts_util.py - finding, extracting and checking the exported notebook artifacts.

The notebook export cell produces a folder (and a zip of it):

    nids_export/
        metrics.json  curves.json  sample_flows.csv  sample_template.csv
        models/  ann_model.keras  nids_random_forest.pkl  logistic_regression.pkl
                 balanced_logistic_regression.pkl  standard_scaler.pkl
        png/ ...

The app wants exactly that layout directly inside `artifacts/`. This module makes that forgiving:
* the layout may be nested (artifacts/nids_export/..., even artifacts/nids_export/artifacts/...): it is found;
* a nids_export.zip dropped into `artifacts/` (or the project folder) is extracted automatically, with any wrapper
  folder stripped, and without ever writing outside the destination folder;
* an inventory lists every expected file as present / missing, so the UI can say exactly what to fix.
"""
from __future__ import annotations

import logging
import zipfile
from pathlib import Path

log = logging.getLogger("nids.artifacts")

# (relative path, what it is, group). group: "model" = needed for predictions, "evaluation" = needed for charts, "optional"
EXPECTED = [
    ("models/ann_model.keras", "ANN model", "model"),
    ("models/nids_random_forest.pkl", "Random Forest model", "model"),
    ("models/logistic_regression.pkl", "Logistic Regression model", "model"),
    ("models/balanced_logistic_regression.pkl", "Balanced Logistic Regression model", "model"),
    ("models/standard_scaler.pkl", "StandardScaler (needed by the ANN and both Logistic Regressions)", "model"),
    ("metrics.json", "saved evaluation: Dashboard KPIs, Why ANN, Model Battle", "evaluation"),
    ("curves.json", "saved curves: ROC, PR, training history, threshold sweep", "evaluation"),
    ("sample_flows.csv", "demo sample file", "optional"),
    ("sample_template.csv", "blank CSV template", "optional"),
]
MAX_DEPTH = 3


def _looks_like_root(d: Path) -> bool:
    return (d / "metrics.json").is_file() or (d / "models").is_dir() and any(
        (d / rel).is_file() for rel, _, g in EXPECTED if g == "model")


def find_root(base) -> Path | None:
    """Shallowest folder at or below `base` (max 3 levels) that looks like an export. None if there is none."""
    base = Path(base)
    if not base.is_dir():
        return None
    level = [base]
    for _ in range(MAX_DEPTH + 1):
        for d in level:
            if _looks_like_root(d):
                return d
        level = [c for d in level for c in sorted(d.iterdir()) if c.is_dir() and c.name not in ("__pycache__", ".git")]
        if not level:
            break
    return None


def inventory(root) -> list[dict]:
    """One row per expected file: {path, label, group, present, size_kb}."""
    rows = []
    for rel, label, group in EXPECTED:
        p = Path(root) / rel if root else None
        present = bool(p and p.is_file() and p.stat().st_size > 0)
        rows.append({"path": rel.replace("/", "\\"), "label": label, "group": group, "present": present,
                     "size_kb": round(p.stat().st_size / 1024) if present else None})
    return rows


# ----------------------------------------------------------------------------------------- zip handling
def _candidate_zips(base: Path, extra_dirs=()) -> list[Path]:
    seen, out = set(), []
    for d in (base, *extra_dirs):
        if d and Path(d).is_dir():
            for z in sorted(Path(d).glob("*.zip")):
                if z.resolve() not in seen:
                    seen.add(z.resolve()); out.append(z)
    # prefer files called nids_export*.zip
    return sorted(out, key=lambda z: (0 if "nids_export" in z.name.lower() else 1, z.name))


def _zip_prefix(names: list[str]):
    """Folder prefix inside the zip that holds metrics.json or models/ (shortest one wins). None if it is not an export."""
    best = None
    for n in names:
        n = n.replace("\\", "/")
        if n == "metrics.json" or n.endswith("/metrics.json"):
            prefix = n[: -len("metrics.json")]
        elif n.startswith("models/"):
            prefix = ""
        elif "/models/" in n:
            prefix = n[: n.index("/models/") + 1]
        else:
            continue
        if best is None or len(prefix) < len(best):
            best = prefix
    return best


def extract_zip(zip_path: Path, dest: Path) -> list[str]:
    """Extract an export zip into `dest`, removing any wrapper folder. Never writes outside `dest`. Returns the files written."""
    dest = Path(dest).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    source_zip = Path(zip_path).resolve()
    written = []
    with zipfile.ZipFile(zip_path) as z:
        names = [i.filename for i in z.infolist() if not i.is_dir()]
        prefix = _zip_prefix(names)
        if prefix is None:
            raise ValueError(f"{Path(zip_path).name} does not look like an NIDS export (no metrics.json or models/ inside).")
        for info in z.infolist():
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/")
            if not name.startswith(prefix):
                continue                                         # ignore anything outside the export folder
            rel = name[len(prefix):]
            target = (dest / rel).resolve()
            if dest not in target.parents:                       # zip-slip protection
                raise ValueError(f"Unsafe path in zip: {info.filename}")
            if target == source_zip:                             # a zip that contains itself must not overwrite itself
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, "wb") as out:
                out.write(src.read())
            written.append(rel)
    return written


def prepare(base, extra_zip_dirs=()):
    """Return (root or None, note). Extracts a zip automatically, but only when no export is found yet."""
    base = Path(base)
    root = find_root(base)
    if root is not None:
        return root, None
    for z in _candidate_zips(base, extra_zip_dirs):
        try:
            files = extract_zip(z, base)
        except (ValueError, zipfile.BadZipFile) as e:
            log.warning("skipping %s: %s", z, e)
            continue
        root = find_root(base)
        if root is not None:
            note = f"Extracted {z.name} into {base} ({len(files)} files)."
            log.info(note)
            return root, note
    return None, None
