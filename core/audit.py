from datetime import datetime, timezone
import json
from typing import List, Dict, Any

from .config import AUDIT_DIR


def new_run_id() -> str:
    """Return a human-readable run id based on local time: YYYYMMDD_HHMMSS"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


class AuditLogger:
    def __init__(self, run_id: str | None = None):
        self.run_id = run_id or new_run_id()
        AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        self.log_path = AUDIT_DIR / f"{self.run_id}.jsonl"

    def log(self, agent: str, action: str, **kwargs) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "agent": agent,
            "action": action,
        }
        entry.update(kwargs)
        with open(self.log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")

    def get_logs(self) -> List[Dict[str, Any]]:
        if not self.log_path.exists():
            return []
        with open(self.log_path, "r", encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]


__all__ = ["new_run_id", "AuditLogger"]
