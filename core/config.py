from pathlib import Path
import os
from dotenv import load_dotenv

# Load environment variables from .env at import time
load_dotenv()

BASE_DIR = Path(__file__).parent.parent.resolve()

# Path constants
LANDING_DIR = BASE_DIR / "data" / "landing"
PROFILES_DIR = BASE_DIR / "data" / "profiles"
STTM_DIR = BASE_DIR / "data" / "sttm"
BRONZE_DIR = BASE_DIR / "data" / "bronze_layer"
SILVER_DIR = BASE_DIR / "data" / "silver_layer"
GOLD_DIR = BASE_DIR / "data" / "gold_layer"
TRACES_DIR = BASE_DIR / "data" / "traces"
REPORTS_DIR = BASE_DIR / "reports"
AUDIT_DIR = BASE_DIR / "audit_logs"

# LLM / GitHub Models configuration
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_BASE_URL = os.getenv("GITHUB_BASE_URL", "https://models.github.ai/inference")
GITHUB_MODEL = os.getenv("GITHUB_MODEL", "gpt-4.1-mini")
if "/" not in GITHUB_MODEL:
    GITHUB_MODEL = f"openai/{GITHUB_MODEL}"

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "github").strip().lower()


def ensure_dirs() -> None:
    """Create all project directories used by the pipeline."""
    for p in [
        LANDING_DIR,
        PROFILES_DIR,
        STTM_DIR,
        BRONZE_DIR,
        SILVER_DIR,
        GOLD_DIR,
        TRACES_DIR,
        REPORTS_DIR,
        AUDIT_DIR,
    ]:
        p.mkdir(parents=True, exist_ok=True)
