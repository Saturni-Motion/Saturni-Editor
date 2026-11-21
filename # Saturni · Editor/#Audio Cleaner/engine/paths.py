from pathlib import Path

RUNTIME = Path.home() / ".stemstudio"
MSST_DIR = RUNTIME / "msst"
MODELS_DIR = RUNTIME / "models"
JOBS_DIR = RUNTIME / "jobs"
REFS_DIR = RUNTIME / "refs"

for d in (JOBS_DIR, REFS_DIR):
    d.mkdir(parents=True, exist_ok=True)
