from pathlib import Path
import json
import re
from typing import List

import pandas as pd

from core.config import PROFILES_DIR
from core.audit import AuditLogger


_MMDDYYYY = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
_YYYYMMDD = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}$")


def _is_mmddyyyy(s: str) -> bool:
    return bool(_MMDDYYYY.match(s))


def _is_yyyy_mm_dd(s: str) -> bool:
    return bool(_YYYYMMDD.match(s))


def profile(file_paths: List[str], run_id: str) -> str:
    """Profile a list of CSV files and write a combined JSON profile.

    Returns the path to the written profile JSON as a string.
    """
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    out_path = PROFILES_DIR / f"profile_combined_{run_id}.json"

    profile = {"run_id": run_id, "tables": {}, "candidate_join_keys": {}}
    id_columns = {}

    for fp in file_paths:
        path = Path(fp)
        table_name = path.stem
        try:
            df = pd.read_csv(path, low_memory=False)
        except Exception as e:
            # Record an empty table entry on failure
            profile["tables"][table_name] = {"row_count": 0, "error": str(e), "columns": {}}
            continue

        row_count = int(len(df))
        cols = {}

        for col in df.columns:
            s = df[col]
            non_null = s.dropna()
            dtype = str(s.dtype)
            null_count = int(s.isnull().sum())
            null_pct = float(null_count / row_count) if row_count > 0 else 0.0
            unique_count = int(non_null.nunique())
            sample_values = [str(x) for x in list(pd.unique(non_null))[:5]]

            col_entry = {
                "dtype": dtype,
                "null_count": null_count,
                "null_pct": round(null_pct, 4),
                "unique_count": unique_count,
                "sample_values": sample_values,
                "quality_flags": [],
            }

            # Numeric stats
            if pd.api.types.is_numeric_dtype(s):
                try:
                    nums = pd.to_numeric(non_null, errors="coerce").dropna()
                    if len(nums) > 0:
                        col_entry.update({
                            "min": float(nums.min()),
                            "max": float(nums.max()),
                            "mean": float(nums.mean()),
                        })
                except Exception:
                    pass

            # Detect mixed date formats for object columns
            if pd.api.types.is_object_dtype(s) and len(non_null) > 0:
                samples = non_null.astype(str)
                mm = samples.apply(_is_mmddyyyy).sum()
                yy = samples.apply(_is_yyyy_mm_dd).sum()
                if row_count > 0 and (mm / row_count) > 0.1 and (yy / row_count) > 0.1:
                    col_entry["quality_flags"].append("mixed_date_formats")

                # possible abbreviations: short average string length
                try:
                    avg_len = samples.str.len().mean()
                    if avg_len is not None and avg_len < 6:
                        col_entry["quality_flags"].append("possible_abbreviations")
                except Exception:
                    pass

            cols[col] = col_entry

            # track id-like columns for candidate joins
            if col.lower().endswith("_id"):
                id_columns.setdefault(col, []).append(table_name)

        profile["tables"][table_name] = {"row_count": row_count, "columns": cols}

    # candidate join keys: ids present in 2+ tables
    candidate = {k: v for k, v in id_columns.items() if len(set(v)) >= 2}
    profile["candidate_join_keys"] = candidate

    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(profile, fh, indent=2, default=str)

    # Audit log
    logger = AuditLogger(run_id)
    logger.log(agent="profiler", action="completed", output=str(out_path), tables=list(profile["tables"].keys()))

    return str(out_path)


__all__ = ["profile"]
