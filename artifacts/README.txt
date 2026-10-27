Put the files exported by the notebook here (extract nids_export.zip into this folder).
After extraction these must exist:
  metrics.json
  curves.json
  models\ann_model.keras
  models\standard_scaler.pkl
  models\nids_random_forest.pkl
  models\logistic_regression.pkl
  models\balanced_logistic_regression.pkl
  sample_flows.csv
  sample_template.csv
  png\*.png   (optional)
Alternatively leave this folder empty and set  $env:NIDS_ARTIFACT_DIR  to the export folder.
