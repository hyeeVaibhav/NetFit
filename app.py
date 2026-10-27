"""app.py - Flask backend for the NIDS project.

Run:  python app.py        then open  http://127.0.0.1:5000

Pages : /  /predict  /results/<id>  /history  /why-ann  /battle  /present
API   : /api/health /api/models /api/metrics /api/curves /api/insights
        POST /api/predict   POST /api/battle
        /api/history  /api/runs/<id>  /api/runs/<id>/rows  /api/runs/<id>/threshold  /api/runs/<id>/download
        DELETE /api/runs/<id>   DELETE /api/history
"""
from __future__ import annotations

import logging
import os
import time

import numpy as np
import pandas as pd
from flask import Flask, jsonify, render_template, request, send_file, send_from_directory, abort
from werkzeug.exceptions import HTTPException

import config
from database import Database
from insights import build_insights
from predictor import Predictor, ValidationError, confusion_metrics, detect_labels, read_csv_bytes

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("nids.app")

DISPLAY_COLUMNS = ["row_id", "IPV4_SRC_ADDR", "IPV4_DST_ADDR", "L4_SRC_PORT", "L4_DST_PORT", "PROTOCOL", "IN_BYTES",
                   "OUT_BYTES", "TCP_FLAGS", "FLOW_DURATION_MILLISECONDS", "Label", "Attack",
                   "P_attack", "Verdict", "Confidence", "Risk"]


def create_app(artifact_dir=None, data_dir=None) -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = config.MAX_UPLOAD_MB * 1024 * 1024

    data_dir = data_dir or config.DATA_DIR
    db = Database(os.path.join(data_dir, "nids.db"), os.path.join(data_dir, "results"))
    log.info("Loading models from %s ... (TensorFlow can take 10-30 seconds)", artifact_dir or config.ARTIFACT_DIR)
    predictor = Predictor(artifact_dir or config.ARTIFACT_DIR)
    app.extensions["nids"] = {"db": db, "predictor": predictor}
    log.info("Predictor status: %s", {k: v for k, v in predictor.status().items() if k != "features"})

    _frame_cache: dict = {}

    # ------------------------------------------------------------------ helpers
    def err(status, message, details=None):
        return jsonify(ok=False, error=message, details=details or []), status

    def load_result_frame(run_id: int):
        path = db.result_path(run_id)
        if path is None:
            return None
        stamp = path.stat().st_mtime
        cached = _frame_cache.get(run_id)
        if cached and cached[0] == stamp:
            return cached[1]
        df = pd.read_csv(path, low_memory=False)
        _frame_cache.clear() if len(_frame_cache) >= 3 else None
        _frame_cache[run_id] = (stamp, df)
        return df

    def read_upload():
        """Return (DataFrame, filename) from the uploaded file, or from the bundled sample when sample=1."""
        if request.form.get("sample", "").lower() in ("1", "true", "yes"):
            path = predictor.sample_path()
            if path is None:
                raise ValidationError("The sample file (sample_flows.csv) was not found in the artifacts folder.")
            return read_csv_bytes(path.read_bytes()), "sample_flows.csv"
        f = request.files.get("file")
        if f is None or not f.filename:
            raise ValidationError("No file was uploaded. Choose a .csv file first.")
        if not f.filename.lower().endswith(".csv"):
            raise ValidationError("Only .csv files are accepted.")
        return read_csv_bytes(f.read()), os.path.basename(f.filename)

    def parse_threshold(raw, default=config.DEFAULT_THRESHOLD):
        if raw in (None, ""):
            return default
        try:
            value = float(raw)
        except ValueError:
            raise ValidationError("The threshold must be a number between 0 and 1.")
        if not 0.0 < value < 1.0:
            raise ValidationError("The threshold must be between 0 and 1 (exclusive).")
        return value

    # ------------------------------------------------------------------ template context
    @app.context_processor
    def inject_status():
        st = predictor.status()
        return {"app_status": st, "tuned_threshold": predictor.tuned_ann_threshold()}

    # ------------------------------------------------------------------ pages
    @app.get("/")
    def page_dashboard():
        return render_template("dashboard.html", page="dashboard", totals=db.totals(),
                               recent=db.list_runs(5), insights=build_insights(predictor.metrics),
                               dataset=predictor.metrics.get("dataset", {}))

    @app.get("/predict")
    def page_predict():
        return render_template("predict.html", page="predict", models=predictor.catalog(),
                               max_mb=config.MAX_UPLOAD_MB, max_rows=config.MAX_ROWS, features=predictor.features)

    @app.get("/results/<int:run_id>")
    def page_results(run_id):
        run = db.get_run(run_id)
        if run is None:
            return render_template("error.html", page="", code=404, message=f"Prediction run #{run_id} was not found."), 404
        return render_template("results.html", page="results", run=run)

    @app.get("/history")
    def page_history():
        return render_template("history.html", page="history")

    @app.get("/why-ann")
    def page_why():
        return render_template("why_ann.html", page="why", insights=build_insights(predictor.metrics),
                               pngs=_png_list())

    @app.get("/battle")
    def page_battle():
        return render_template("battle.html", page="battle", models=predictor.catalog())

    @app.get("/present")
    def page_present():
        return render_template("present.html", page="present")

    def _png_list():
        if predictor.root and (predictor.root / "png").is_dir():
            return sorted(p.name for p in (predictor.root / "png").glob("*.png"))
        return []

    # ------------------------------------------------------------------ artifact files
    @app.get("/artifacts/png/<path:name>")
    def artifact_png(name):
        if not predictor.root or not (predictor.root / "png").is_dir():
            abort(404)
        return send_from_directory(predictor.root / "png", name)

    @app.get("/api/sample")
    def api_sample():
        path = predictor.sample_path()
        if path is None:
            return err(404, "sample_flows.csv is not available in the artifacts folder.")
        return send_file(path, as_attachment=True, download_name="sample_flows.csv", mimetype="text/csv")

    @app.get("/api/template")
    def api_template():
        path = predictor.template_path()
        if path is None:
            return err(404, "sample_template.csv is not available in the artifacts folder.")
        return send_file(path, as_attachment=True, download_name="nids_template.csv", mimetype="text/csv")

    # ------------------------------------------------------------------ info API
    @app.get("/api/health")
    def api_health():
        st = predictor.status()
        st["database"] = db.ok()
        st["status"] = "ok" if (st["ready"] and st["database"]) else "degraded"
        st["max_upload_mb"], st["max_rows"] = config.MAX_UPLOAD_MB, config.MAX_ROWS
        return jsonify(st), (200 if st["status"] == "ok" else 503)

    @app.get("/api/models")
    def api_models():
        return jsonify(models=predictor.catalog(), tuned_ann_threshold=predictor.tuned_ann_threshold())

    @app.get("/api/metrics")
    def api_metrics():
        if not predictor.metrics:
            return err(404, "metrics.json was not found in the artifacts folder.")
        return jsonify(predictor.metrics)

    @app.get("/api/curves")
    def api_curves():
        if not predictor.curves:
            return err(404, "curves.json was not found in the artifacts folder.")
        return jsonify(predictor.curves)

    @app.get("/api/insights")
    def api_insights():
        return jsonify(insights=build_insights(predictor.metrics))

    # ------------------------------------------------------------------ prediction API
    @app.post("/api/predict")
    def api_predict():
        if not predictor.models:
            return err(503, "No trained model could be loaded, so predictions are unavailable.",
                       [f"{k}: {v}" for k, v in predictor.errors.items()])
        try:
            model_key = request.form.get("model", "ann")
            if model_key not in config.MODEL_FILES:
                raise ValidationError(f"Unknown model '{model_key}'.")
            threshold = parse_threshold(request.form.get("threshold"))
            df, filename = read_upload()
            t0 = time.perf_counter()
            result, summary = predictor.predict(df, model_key, threshold)
            duration_ms = (time.perf_counter() - t0) * 1000
        except ValidationError as e:
            return err(400, e.message, e.details)
        except HTTPException:
            raise
        except Exception:
            log.exception("prediction failed")
            return err(500, "The prediction failed unexpectedly. See the server console for details.")
        run_id = db.add_run(filename=filename, model_key=model_key, model_name=predictor.display_name(model_key),
                            threshold=threshold, summary=summary, duration_ms=duration_ms, result_df=result)
        return jsonify(ok=True, run_id=run_id, redirect=f"/results/{run_id}", summary=summary,
                       model=predictor.display_name(model_key), duration_ms=round(duration_ms))

    @app.post("/api/battle")
    def api_battle():
        if not predictor.models:
            return err(503, "No trained model could be loaded.")
        try:
            thresholds = {}
            for key in config.MODEL_FILES:
                raw = request.form.get(f"thr_{key}")
                if raw not in (None, ""):
                    thresholds[key] = parse_threshold(raw)
            df, filename = read_upload()
            out = predictor.battle(df, thresholds)
            out.update(ok=True, filename=filename)
            return jsonify(out)
        except ValidationError as e:
            return err(400, e.message, e.details)
        except HTTPException:
            raise
        except Exception:
            log.exception("battle failed")
            return err(500, "The model battle failed unexpectedly. See the server console for details.")

    # ------------------------------------------------------------------ history API
    @app.get("/api/history")
    def api_history():
        return jsonify(runs=db.list_runs(), totals=db.totals())

    @app.get("/api/runs/<int:run_id>")
    def api_run(run_id):
        run = db.get_run(run_id)
        return jsonify(run) if run else err(404, f"Run #{run_id} was not found.")

    @app.delete("/api/runs/<int:run_id>")
    def api_delete_run(run_id):
        _frame_cache.pop(run_id, None)
        return jsonify(ok=True) if db.delete_run(run_id) else err(404, f"Run #{run_id} was not found.")

    @app.delete("/api/history")
    def api_clear_history():
        _frame_cache.clear()
        return jsonify(ok=True, deleted=db.clear())

    @app.get("/api/runs/<int:run_id>/download")
    def api_download(run_id):
        path = db.result_path(run_id)
        if path is None:
            return err(404, f"The result file of run #{run_id} was not found.")
        return send_file(path, as_attachment=True, download_name=f"nids_results_run{run_id}.csv", mimetype="text/csv")

    @app.get("/api/runs/<int:run_id>/rows")
    def api_rows(run_id):
        df = load_result_frame(run_id)
        if df is None:
            return err(404, f"The result file of run #{run_id} was not found.")
        flt, sort = request.args.get("filter", "all"), request.args.get("sort", "row")
        q = request.args.get("q", "").strip()
        try:
            page = max(1, int(request.args.get("page", 1)))
            size = min(200, max(5, int(request.args.get("size", 25))))
        except ValueError:
            return err(400, "page and size must be integers.")
        view = df
        if flt == "attack":
            view = view[view["Prediction"] == 1]
        elif flt == "normal":
            view = view[view["Prediction"] == 0]
        elif flt == "wrong" and "Label" in view.columns:
            view = view[(view["Label"] != view["Prediction"])]
        if q:
            cols = [c for c in ("IPV4_SRC_ADDR", "IPV4_DST_ADDR", "L4_DST_PORT", "Attack", "Risk") if c in view.columns]
            if cols:
                mask = np.zeros(len(view), dtype=bool)
                for c in cols:
                    mask |= view[c].astype(str).str.contains(q, case=False, regex=False).to_numpy()
                view = view[mask]
        if sort == "prob_desc":
            view = view.sort_values("P_attack", ascending=False, kind="stable")
        elif sort == "prob_asc":
            view = view.sort_values("P_attack", ascending=True, kind="stable")
        total = len(view)
        cols = [c for c in DISPLAY_COLUMNS if c in view.columns]
        chunk = view.iloc[(page - 1) * size: page * size][cols]
        rows = chunk.astype(object).where(pd.notna(chunk), None).values.tolist()
        return jsonify(columns=cols, rows=rows, total=total, page=page, size=size,
                       pages=max(1, -(-total // size)))

    @app.get("/api/runs/<int:run_id>/threshold")
    def api_threshold(run_id):
        """What-if: re-apply a different threshold to the saved probabilities (no re-upload, no re-prediction)."""
        df = load_result_frame(run_id)
        if df is None:
            return err(404, f"The result file of run #{run_id} was not found.")
        try:
            value = parse_threshold(request.args.get("value"))
        except ValidationError as e:
            return err(400, e.message)
        pred = (df["P_attack"].to_numpy() >= value).astype(int)
        out = {"threshold": value, "n_rows": int(len(df)), "n_attack": int(pred.sum()),
               "n_normal": int(len(df) - pred.sum()), "attack_rate": float(pred.mean())}
        y = detect_labels(df)
        if y is not None:
            out["labels"] = confusion_metrics(y, pred)
        return jsonify(out)

    # ------------------------------------------------------------------ error handlers
    def wants_json():
        return request.path.startswith("/api/")

    @app.errorhandler(404)
    def not_found(_e):
        if wants_json():
            return err(404, "Not found.")
        return render_template("error.html", page="", code=404, message="That page does not exist."), 404

    @app.errorhandler(413)
    def too_large(_e):
        msg = f"The file is larger than the {config.MAX_UPLOAD_MB} MB upload limit."
        return err(413, msg) if wants_json() else (render_template("error.html", page="", code=413, message=msg), 413)

    @app.errorhandler(405)
    def bad_method(_e):
        return err(405, "Method not allowed.") if wants_json() else (
            render_template("error.html", page="", code=405, message="Method not allowed."), 405)

    @app.errorhandler(500)
    def server_error(_e):
        log.exception("unhandled error")
        if wants_json():
            return err(500, "Internal server error.")
        return render_template("error.html", page="", code=500, message="Something went wrong on the server."), 500

    return app


if __name__ == "__main__":
    application = create_app()
    port = int(os.environ.get("PORT", "5000"))
    print(f"\n  NIDS app running at  http://127.0.0.1:{port}\n  (press Ctrl+C to stop)\n")
    application.run(host="127.0.0.1", port=port, debug=False, use_reloader=False, threaded=True)
