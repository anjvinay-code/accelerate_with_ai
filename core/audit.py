from datetime import datetime, timezone
import json
from typing import List, Dict
from pathlib import Path

from core.config import AUDIT_DIR


def new_run_id() -> str:
    """Human-readable run id based on local time, e.g. "20260718_191117"."""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


class AuditLogger:
    def __init__(self, run_id: str | None = None):
        self.run_id = run_id or new_run_id()
        self.log_path = AUDIT_DIR / f"{self.run_id}.jsonl"
        AUDIT_DIR.mkdir(parents=True, exist_ok=True)

    def log(self, agent: str, action: str, **kwargs) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "agent": agent,
            "action": action,
            **kwargs,
        }
        with open(self.log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")

    def get_logs(self) -> List[Dict]:
        if not self.log_path.exists():
            return []
        with open(self.log_path, "r", encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]
