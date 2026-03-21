from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
DEFAULT_DB_PATH = DATA_DIR / "skill_hub.db"
FRONTEND_STATIC_DIR = ROOT_DIR / "app" / "static"
ARCHIVES_DIR = DATA_DIR / "archives"
