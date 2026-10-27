"""Central configuration for the NIDS web app.

Everything can be overridden with environment variables, so no source edit is needed:
    NIDS_ARTIFACT_DIR   folder that contains the exported notebook artifacts (default: ./artifacts)
    NIDS_DATA_DIR       folder for the SQLite database and result files (default: ./data)
    NIDS_MAX_UPLOAD_MB  maximum accepted upload size in MB (default: 25)
    NIDS_MAX_ROWS       maximum number of flows per upload (default: 200000)
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

ARTIFACT_DIR = Path(os.environ.get("NIDS_ARTIFACT_DIR", BASE_DIR / "artifacts"))
DATA_DIR = Path(os.environ.get("NIDS_DATA_DIR", BASE_DIR / "data"))
RESULTS_DIR = DATA_DIR / "results"
DB_PATH = DATA_DIR / "nids.db"

MAX_UPLOAD_MB = int(os.environ.get("NIDS_MAX_UPLOAD_MB", "25"))
MAX_ROWS = int(os.environ.get("NIDS_MAX_ROWS", "200000"))

DEFAULT_THRESHOLD = 0.5

# The ten input features, in the exact order the models were trained on.
# (The app prefers the list stored in metrics.json when it is available.)
DEFAULT_FEATURES = [
    "L4_SRC_PORT", "L4_DST_PORT", "PROTOCOL", "L7_PROTO", "IN_BYTES",
    "OUT_BYTES", "IN_PKTS", "OUT_PKTS", "TCP_FLAGS", "FLOW_DURATION_MILLISECONDS",
]

# model key -> (display name, file relative to the artifact root, needs scaled input)
MODEL_FILES = {
    "ann": ("ANN", "models/ann_model.keras", True),
    "random_forest": ("Random Forest", "models/nids_random_forest.pkl", False),
    "logistic_regression": ("Logistic Regression", "models/logistic_regression.pkl", True),
    "logistic_regression_balanced": ("Balanced Logistic Regression", "models/balanced_logistic_regression.pkl", True),
}
SCALER_FILE = "models/standard_scaler.pkl"
