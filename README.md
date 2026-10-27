# NIDS Web App: Network Intrusion Detection with an ANN
Author: Vaibhav Kr Singh,Atharv Saxena,Shubham Saurabh | B.Tech CSE (AIML-C) Student

A Flask + SQLite web application around your trained models. Upload a CSV of network flows, choose a model and a
threshold, and get a verdict (Normal / Attack), a probability and a risk band for every flow. The app also presents the
evaluation from your notebook: **Why ANN?**, **Model Battle** and a full-screen **Presentation Mode**.

Nothing in the app is invented. Predictions come from your trained models; every chart and sentence about model quality
is built from the `metrics.json` / `curves.json` that your notebook export cell produced.

---

## 1. Quick start (Windows PowerShell)

Use the **same Python environment you use for the notebook** (the models are pickled with its scikit-learn / TensorFlow).

```powershell
cd D:\Nids_APP

python -m pip install -r requirements.txt     # only Flask is normally missing
python setup_artifacts.py                     # finds your export and puts it in D:\Nids_APP\artifacts
python check_setup.py                         # must end with: RESULT: all 4 models loaded
python app.py                                 # then open http://127.0.0.1:5000
```

(`.\setup_artifacts.ps1` does the same as `python setup_artifacts.py`. If PowerShell blocks it, run `Set-ExecutionPolicy -Scope Process Bypass` once.)

What `setup_artifacts.py` does: it looks for `nids_export.zip`, a `nids_export` folder, or a folder that holds the model files
(for example `E:\GitHub\Network-Intrusion-Detection-System\models`), installs the best match into `artifacts\`, removes any wrapper folder
(so you never end up with `artifacts\nids_export\artifacts\models`), and prints a checklist. It never changes or deletes the source.
You can also point it at something specific:

```powershell
python setup_artifacts.py --source "E:\Udemy_ML\NIDS_Project.ipynb\nids_export\nids_export.zip"
python setup_artifacts.py --source "E:\GitHub\Network-Intrusion-Detection-System\models"
python setup_artifacts.py --force            # replace an existing installation
```

Manual alternative: extract the zip yourself, so that `D:\Nids_APP\artifacts\metrics.json` and `D:\Nids_APP\artifacts\models\ann_model.keras` exist.
Even a nested folder or a `nids_export.zip` dropped into `artifacts\` is found/extracted automatically when the app starts.

### Verification checklist
- [ ] `python check_setup.py` prints four lines `[LOADED     ]` and `RESULT: all 4 models loaded.`
- [ ] It scores `sample_flows.csv` (or `--csv nids_demo_sample.csv`) with every model without a CSV error.
- [ ] The app sidebar shows **4 / 4 models loaded** and the Dashboard shows real KPIs and charts.
- [ ] CSV Prediction → *Run prediction* on your CSV opens a Results page.

A model is only counted as loaded after it has made a real test prediction, so "4 / 4 loaded" means 4 models that can actually predict.

### Test your own demo CSV
```powershell
python check_setup.py --csv D:\Nids_APP\nids_demo_sample.csv
```
Prints each model's flagged count (and recall/precision if the CSV has a 0/1 `Label` column), or exactly what is wrong with the file.

### Automated tests (optional)
```powershell
python -m unittest tests.test_smoke tests.test_artifacts
```

---

## 2. Required artifacts

Everything comes from the notebook export cell. After setup, `artifacts\` must contain:

| File | Needed for |
|------|-----------|
| `models\ann_model.keras` | the ANN |
| `models\standard_scaler.pkl` | scaling for the ANN and both Logistic Regressions |
| `models\nids_random_forest.pkl` | Random Forest (trained on unscaled data) |
| `models\logistic_regression.pkl` | Logistic Regression |
| `models\balanced_logistic_regression.pkl` | class-weighted Logistic Regression |
| `metrics.json`, `curves.json` | Dashboard KPIs, Why ANN, Model Battle, Presentation (not needed for predictions) |
| `sample_flows.csv`, `sample_template.csv` | "Use sample file" and the template download (optional; a `nids_demo_sample.csv` in the app folder also works) |
| `png\*.png` | notebook chart gallery (optional) |

If a model file is missing or broken, the other models still work and the missing one is shown as "not loaded" with the reason.
With only the five model files, predictions work, and the app shows a "Partly set up" notice saying which files the charts need.

---

## 3. If the export is lost: recovery without retraining

**Step 1: look for it first** (it is probably still on the laptop):
```powershell
Get-ChildItem -Path D:\,E:\ -Filter "nids_export*.zip" -Recurse -ErrorAction SilentlyContinue | Select-Object FullName, LastWriteTime
Get-ChildItem -Path D:\,E:\ -Filter "ann_model.keras" -Recurse -ErrorAction SilentlyContinue | Select-Object FullName, LastWriteTime
```
Found a zip or an export folder → `python setup_artifacts.py --source "<that path>"`.

**Step 2: only the model files exist** (your notebook's save cells wrote them to `E:\GitHub\Network-Intrusion-Detection-System\models`):
`python setup_artifacts.py --source "E:\GitHub\Network-Intrusion-Detection-System\models"` gives you working **predictions** straight away.
To also get the Dashboard, Why ANN and Model Battle, re-create `metrics.json` / `curves.json` from those saved models with the recovery cell below.

**Step 3: re-create the evaluation files from the saved models (no retraining).** In a **fresh** notebook session:
1. Run only these four original cells: **O-11** (read the 200,000 rows), **O-21** (features and target), **O-24** (train/test split), **O-26** (StandardScaler).
   Do **not** run the model-training cells (O-28, O-35, O-43, the ANN cells): that would overwrite your trained models.
2. Run `nids_recover_cell.py` as a new cell. Set `MODEL_DIR` at its top. It loads your saved models, checks the scaler, and prints each model's test results
   so you can confirm they are the models you expect.
3. Run the updated `nids_export_cell.py` as the next cell. It creates `nids_export\` (metrics, curves, charts, sample CSV, models, zip).
4. `python setup_artifacts.py` from `D:\Nids_APP` installs it, then `python check_setup.py`.

What you lose: the ANN **training curves** (the training log only exists in the session that trained it). Everything else is identical, because the
saved models, the saved scaler and the deterministic split (`random_state=42`) are the same ones.

**If a model file itself is gone:**
- Logistic Regression (either): rerun cells **O-35** / **O-43**. They are fast and deterministic, so the result is the same model.
- ANN or Random Forest: it cannot be recovered without retraining, and a retrained model will give slightly different numbers.
  The app never invents replacements. Retrain deliberately, say so in your report, and re-export.

---

## 4. Project structure

```
nids_app/
  app.py            Flask routes: pages + JSON API
  predictor.py      THE prediction interface: loads artifacts once, validates CSVs, predicts, summarises
  database.py       SQLite layer (prediction history)
  insights.py       plain-English findings generated from metrics.json
  config.py         paths, upload limits, feature list (all overridable by environment variables)
  artifacts_util.py finds the export (even nested), extracts zips safely, checks which files exist
  setup_artifacts.py / .ps1   installs the export into artifacts\ (searches your drives, flattens, verifies)
  check_setup.py    verifies that all models load and predict; scores a CSV of your choice
  requirements.txt
  artifacts/        <- put your exported files here
  data/             created at run time: nids.db and results/run_<id>.csv
  templates/        base, dashboard, predict, results, history, why_ann, battle, present, error
  static/           css/app.css, js/*.js, vendor/ (Bootstrap and Chart.js: no internet needed)
  tests/            test_smoke.py (app + API), test_artifacts.py (setup + recovery handling)
  scripts/          run.ps1 (check, then start)
```

Environment variables (all optional): `NIDS_ARTIFACT_DIR`, `NIDS_DATA_DIR`, `NIDS_MAX_UPLOAD_MB` (default 25),
`NIDS_MAX_ROWS` (default 200000), `PORT` (default 5000).

---

## 5. Pages

| Page | URL | What it does |
|------|-----|--------------|
| Dashboard | `/` | KPIs of the ANN, model comparison, class balance, generated insights, recent runs |
| CSV Prediction | `/predict` | drag-and-drop upload or sample file, model choice, threshold slider with presets |
| Results | `/results/<id>` | counts, probability histogram, risk bands, top ports, table with filter / sort / search / paging, what-if threshold, CSV download. If your file has a `Label` column: confusion matrix and real metrics |
| Prediction History | `/history` | saved runs from SQLite: open, download, delete, delete all |
| Why ANN? | `/why-ann` | 12 evidence sections: charts, confusion matrices, sensitivity slider, architecture, one flow step by step |
| Model Battle | `/battle` | saved comparison table (sortable, best value highlighted) and a live run of all models on one file |
| Presentation Mode | `/present` | 17 full-screen slides. Arrows / Space = next, F = full screen, Home / End |

### Input CSV rules
* Required numeric columns (any order, any capitalisation): `L4_SRC_PORT, L4_DST_PORT, PROTOCOL, L7_PROTO, IN_BYTES, OUT_BYTES, IN_PKTS, OUT_PKTS, TCP_FLAGS, FLOW_DURATION_MILLISECONDS`
* Optional: `Label` (0 = normal, 1 = attack) enables measured accuracy / recall; `Attack` (type name), IP columns are kept for display.
* Rejected with a clear message: empty file, header only, wrong extension, unreadable file, missing columns, non-numeric / missing / infinite values, more rows than the limit, larger than the size limit, bad threshold.

### Result CSV columns
Your original columns plus `row_id` (first), `P_attack`, `Prediction` (0/1), `Verdict`, `Confidence`, `Risk`.
`Risk`: High when P ≥ 0.90, Medium when P ≥ 0.70, Low otherwise (for flows called attacks), `-` for normal flows.

---

## 6. API reference

| Method and path | Purpose |
|-----------------|---------|
| `GET /api/health` | status of artifacts, each model, database (HTTP 503 when no model is loaded) |
| `GET /api/models` | models, load status, saved metrics, tuned ANN threshold |
| `GET /api/metrics` · `GET /api/curves` · `GET /api/insights` | the exported evaluation data |
| `POST /api/predict` | multipart form: `file` **or** `sample=1`; `model` (`ann`, `random_forest`, `logistic_regression`, `logistic_regression_balanced`; default `ann`); `threshold` (0 to 1 exclusive, default 0.5). Returns `{ok, run_id, redirect, model, duration_ms, summary}` |
| `POST /api/battle` | same data fields plus optional `thr_<model key>`; runs every loaded model on the same flows |
| `GET /api/history` | saved runs and totals |
| `GET /api/runs/<id>` | one run with its summary |
| `GET /api/runs/<id>/rows` | `page`, `size` (5 to 200), `filter` (`all` `attack` `normal` `wrong`), `sort` (`row` `prob_desc` `prob_asc`), `q` (search IP, port, attack type) |
| `GET /api/runs/<id>/threshold?value=0.7` | what-if: re-apply a threshold to the saved probabilities |
| `GET /api/runs/<id>/download` | results CSV |
| `DELETE /api/runs/<id>` · `DELETE /api/history` | delete one run / all runs |
| `GET /api/sample` · `GET /api/template` | sample flows / blank template CSV |

Errors are always JSON: `{"ok": false, "error": "...", "details": ["..."]}` with status 400 (bad input), 404, 405, 413 (too large), 503 (no model) or 500.

PowerShell example:
```powershell
curl.exe -F "file=@flows.csv" -F "model=ann" -F "threshold=0.5" http://127.0.0.1:5000/api/predict
```

### Database (SQLite, `data\nids.db`)
Table `runs`: `id, created_at, filename, model_key, model_name, threshold, n_rows, n_attack, n_normal, attack_rate, has_labels, accuracy, precision_, recall, f1, duration_ms, result_file, summary_json`.
The per-flow results are stored as `data\results\run_<id>.csv` and referenced from the row.

---

## 7. Suggested 5-minute class demo

1. **Presentation Mode** (`/present`): problem, accuracy trap, architecture, recall, missed vs false alarms (slides 1 to 7).
2. Press the "Live demo" slide link, or go to **CSV Prediction**: click *Use the bundled sample file*, model **ANN**, run.
3. On **Results**: show the confusion matrix, drag the *what-if threshold* slider, show the table sorted by "Most suspicious first".
4. **Model Battle** → *Use sample file* → *Run battle*: all four models on the same flows.
5. **History**: show the saved run and the downloaded CSV. Finish on the "honest comparison" slide.

Before presenting: start the app **before** the class (TensorFlow loads slowly), run the sample once, and keep the browser on `http://127.0.0.1:5000`.

---

## 8. Troubleshooting

| Symptom | Fix |
|---------|-----|
| Banner "Setup required" with a checklist | `python setup_artifacts.py`, then `python check_setup.py`. Export gone? README section 3 |
| Banner "Partly set up" | predictions work; `metrics.json` / `curves.json` are missing, so run the recovery cell (section 3) |
| A model shows "not loaded" with an error | read the reason shown next to it. Typical cause: the pickle was made with a different scikit-learn/TensorFlow version, so run the app in the **same Python environment as the notebook** (version warnings are listed in the banner and by `check_setup.py`) |
| Start-up takes 10 to 30 seconds | TensorFlow is loading. Wait for the "NIDS app running" line |
| `Address already in use` | `$env:PORT=5001; python app.py` |
| Upload rejected: "required column(s) are missing" | use the template (`/api/template`), check spelling of the 10 columns |
| "larger than the upload limit" | `$env:NIDS_MAX_UPLOAD_MB=100` before starting |

---

## 9. Limitations (say these honestly)

* The models are binary (attack / normal). They do not name the attack type.
* They were trained on NF-UNSW-NB15 flow records with ten features; other networks or feature sets will behave differently.
* The app scores uploaded flow files. It does **not** capture live packets, run in real time, or block traffic.
* Probabilities of class-weighted models (ANN, balanced Logistic Regression) are shifted upward by the weights, so "0.8" is not an 80 % real chance. Use them to rank flows and choose a threshold, not as literal probabilities.
* The built-in server (`python app.py`) is for a demo on one machine. For a real deployment use a production server and add authentication.
* There is no login or CSRF protection because the app is meant for local use.
  
