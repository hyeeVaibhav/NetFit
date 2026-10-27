"""setup_artifacts.py - put the exported notebook files in the right place.

    python setup_artifacts.py                      search your drives for the export and install it
    python setup_artifacts.py --source "E:\\...\\nids_export.zip"      use a specific zip
    python setup_artifacts.py --source "E:\\...\\nids_export"          ... or a specific export folder
    python setup_artifacts.py --source "E:\\GitHub\\Network-Intrusion-Detection-System\\models"   ... or a folder with just the models
    add --force to replace an existing installation

What it handles:  nids_export.zip · the nids_export folder · a bare models folder (ann_model.keras, *.pkl).
Wrapper folders are removed, so you never get artifacts\\nids_export\\artifacts\\models. The source is never modified or deleted.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

import artifacts_util as au
import config

SKIP_DIRS = {"windows", "program files", "program files (x86)", "programdata", "appdata", "$recycle.bin", "system volume information",
             "node_modules", ".git", "site-packages", "__pycache__", "venv", ".venv", "anaconda3", "miniconda3", "envs", "pkgs"}
MODEL_FILES = [rel for rel, _, g in au.EXPECTED if g == "model"]


def default_search_roots(wide: bool = False) -> list[Path]:
    """Likely places first; with wide=True the whole D: and E: drives (slower)."""
    home = Path.home()
    if wide:
        names = ["D:/", "E:/", "F:/", "C:/Users"]
    else:
        names = ["E:/Udemy_ML", "E:/GitHub", "D:/Nids_APP", "D:/GitHub", "D:/Udemy_ML", home / "Downloads", home / "Desktop",
                 home / "Documents", config.BASE_DIR.parent]
    return [Path(n) for n in names if Path(n).exists()]


def walk(root: Path, max_depth: int):
    root = Path(root)
    base_depth = len(root.parts)
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None):
        depth = len(Path(dirpath).parts) - base_depth
        dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIRS and not d.startswith("$")]
        if depth >= max_depth:
            dirnames[:] = []
        yield Path(dirpath), dirnames, filenames


def find_candidates(roots: list[Path], dest: Path, max_depth: int = 6) -> list[dict]:
    """Return candidates sorted best-first: complete exports (newest first), then folders that only hold models."""
    found, seen = [], set()
    dest = dest.resolve()
    for root in roots:
        for d, _dirs, files in walk(root, max_depth):
            try:
                if dest == d.resolve() or dest in d.resolve().parents:
                    continue                                     # never offer the destination itself
            except OSError:
                continue
            lower = {f.lower(): f for f in files}
            for low, real in lower.items():
                if low.endswith(".zip") and low.startswith("nids_export"):
                    p = d / real
                    if p.resolve() not in seen:
                        seen.add(p.resolve()); found.append({"kind": "zip", "path": p, "complete": True, "mtime": p.stat().st_mtime})
            if "metrics.json" in lower and (d / "models").is_dir():
                if d.resolve() not in seen:
                    seen.add(d.resolve()); found.append({"kind": "export folder", "path": d, "complete": True, "mtime": (d / "metrics.json").stat().st_mtime})
            if "ann_model.keras" in lower and "standard_scaler.pkl" in lower:
                # a folder that directly holds the model files (like E:\GitHub\...\models)
                if not (d.parent / "metrics.json").exists() and d.resolve() not in seen:
                    seen.add(d.resolve())
                    found.append({"kind": "models folder", "path": d, "complete": False, "mtime": (d / "ann_model.keras").stat().st_mtime})
    return sorted(found, key=lambda c: (not c["complete"], -c["mtime"]))


def _copy_tree(src: Path, dst: Path):
    for p in src.rglob("*"):
        if p.is_file():
            target = dst / p.relative_to(src)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, target)


def install(source: Path, dest: Path) -> str:
    """Install `source` (zip / export folder / models folder) into `dest`. Returns a description of what was done."""
    source = Path(source)
    dest.mkdir(parents=True, exist_ok=True)
    if source.is_file() and source.suffix.lower() == ".zip":
        files = au.extract_zip(source, dest)
        return f"extracted {source.name} ({len(files)} files)"
    if source.is_dir():
        root = au.find_root(source)
        if root is not None and (root / "metrics.json").exists():
            _copy_tree(root, dest)
            return f"copied the export folder {root}"
        direct = [rel for rel in MODEL_FILES if (source / Path(rel).name).is_file()]
        if direct:                                                # a bare folder of model files
            (dest / "models").mkdir(parents=True, exist_ok=True)
            for rel in direct:
                shutil.copy2(source / Path(rel).name, dest / rel)
            return f"copied {len(direct)} model file(s) from {source} (no metrics.json found there)"
        if root is not None:
            _copy_tree(root, dest)
            return f"copied {root}"
    raise ValueError(f"'{source}' is not an NIDS export zip, export folder or models folder.")


def flatten(dest: Path) -> str | None:
    """If the export ended up in a sub-folder of `dest` (e.g. dest\\nids_export\\...), move it up. Returns a note."""
    root = au.find_root(dest)
    if root is None or root.resolve() == dest.resolve():
        return None
    first = dest / root.resolve().relative_to(dest.resolve()).parts[0]
    _copy_tree(root, dest)
    shutil.rmtree(first, ignore_errors=True)
    return f"removed the extra folder level '{first.name}'"


def print_inventory(dest: Path) -> bool:
    inv = au.inventory(dest)
    print("\nChecklist for", dest)
    for r in inv:
        mark = "OK     " if r["present"] else ("MISSING" if r["group"] != "optional" else "missing")
        print(f"  [{mark}] {r['path']:<45} {r['label']}")
    return all(r["present"] for r in inv if r["group"] == "model")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Install the exported NIDS artifacts into the app's artifacts folder.")
    ap.add_argument("--source", help="export zip, export folder, or a folder that holds the model files")
    ap.add_argument("--dest", default=str(config.ARTIFACT_DIR), help="default: %(default)s")
    ap.add_argument("--search-root", action="append", default=[], help="extra folder to search (can repeat)")
    ap.add_argument("--force", action="store_true", help="replace an existing installation")
    a = ap.parse_args(argv)
    dest = Path(a.dest)

    existing = au.find_root(dest)
    if existing is not None and not a.force and any(r["present"] for r in au.inventory(existing) if r["group"] == "model"):
        print(f"Artifacts already present in {existing}. Nothing copied (use --force to replace).")
        note = flatten(dest)
        if note:
            print("Tidied up:", note)
        return 0 if print_inventory(dest if note else existing) else 1

    if a.source:
        source = Path(a.source.strip('"'))
        if not source.exists():
            print(f"ERROR: '{source}' does not exist."); return 2
    else:
        roots = [Path(r) for r in a.search_root] + default_search_roots()
        print("Searching for an NIDS export in:\n  " + "\n  ".join(str(r) for r in roots))
        cands = find_candidates(roots, dest)
        if not cands and not a.search_root:
            wide = default_search_roots(wide=True)
            print("Not found there. Searching whole drives (this can take a minute):\n  " + "\n  ".join(str(r) for r in wide))
            cands = find_candidates(wide, dest)
        if not cands:
            print("\nNo nids_export.zip, nids_export folder or model files were found.")
            print("If the export no longer exists, recreate it with the recovery cell in README.md (section 3).")
            print_inventory(dest); return 1
        print("\nFound:")
        for c in cands[:8]:
            print(f"  - {c['kind']:<14} {c['path']}   ({'complete' if c['complete'] else 'models only'})")
        best = cands[0]; source = best["path"]
        print(f"\nUsing the best match: {source}")

    if a.force and dest.exists():
        for rel, _, _ in au.EXPECTED:
            (dest / rel).unlink(missing_ok=True)
    try:
        print("Installing:", install(source, dest))
    except (ValueError, zipfile.BadZipFile, OSError) as e:
        print("ERROR:", e); return 2
    note = flatten(dest)
    if note:
        print("Tidied up:", note)
    complete = print_inventory(dest)
    root = au.find_root(dest)
    if root is not None and not (root / "metrics.json").exists():
        print("\nNOTE: only the models were found. Predictions will work, but Dashboard KPIs, Why ANN and Model Battle need\n"
              "metrics.json / curves.json. Create them with the recovery cell in README.md (section 3).")
    print("\nNext:  python check_setup.py     then     python app.py")
    return 0 if complete else 1


if __name__ == "__main__":
    sys.exit(main())
