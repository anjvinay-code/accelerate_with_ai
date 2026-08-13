from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class PipelineState:
    run_id: str
    input_files: List[str] = field(default_factory=list)
    business_intent: str = ""

    profile_path: Optional[str] = None
    bronze_sttm_path: Optional[str] = None
    bronze_paths: List[str] = field(default_factory=list)
    silver_sttm_path: Optional[str] = None
    silver_paths: List[str] = field(default_factory=list)
    gold_sttm_path: Optional[str] = None
    gold_paths: List[str] = field(default_factory=list)
    report_path: Optional[str] = None


__all__ = ["PipelineState"]
