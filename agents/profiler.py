from pathlib import Path
import re
import json
from typing import List

import pandas as pd

from core.config import PROFILES_DIR
from core.audit import AuditLogger


def _matches_pattern(s: str, pattern: re.Pattern) -> bool:
    try:
        return bool(pattern.match(s))
    except Exception:
        return False


def profile(file_paths: List[str], run_id: str) -> str:
    """Profile input CSV files and write a combined JSON profile.

    Returns the written profile path as a string.
    """
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    profile = {"run_id": run_id, "tables": {}, "candidate_join_keys": {}}

    id_candidates = {}

    mmdd_pat = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
    iso_pat = re.compile(r"^\d{4}-\d{2}-\d{2}$")

    for fp in file_paths:
        p = Path(fp)
        table_name = p.stem
        try:
            df = pd.read_csv(p, low_memory=False)
        except Exception as e:
            # record an empty table with an error note
            profile["tables"][table_name] = {"row_count": 0, "error": str(e), "columns": {}}
            continue

        row_count = int(len(df))
        cols = {}
        for col in df.columns:
            s = df[col]
            non_null = s.dropna()
            non_null_count = int(non_null.shape[0])
            null_count = int(row_count - non_null_count)
            null_pct = float(null_count / row_count) if row_count > 0 else 0.0
            unique_count = int(non_null.nunique(dropna=True))
            sample_values = []
            try:
                sample_values = list(map(str, non_null.astype(str).unique()[:5]))
            except Exception:
                sample_values = []

            col_info = {
                "dtype": str(s.dtype),
                "null_count": null_count,
                "null_pct": round(null_pct, 4),
                "unique_count": unique_count,
                "sample_values": sample_values,
                "quality_flags": [],
            }

            # numeric stats
            try:
                if pd.api.types.is_numeric_dtype(s):
                    numeric = pd.to_numeric(non_null, errors="coerce").dropna()
                    if not numeric.empty:
                        col_info.update({
                            "min": float(numeric.min()),
                            "max": float(numeric.max()),
                            "mean": float(numeric.mean()),
                        })
            except Exception:
                pass

            # quality flags for object columns
            try:
                if s.dtype == object or pd.api.types.is_string_dtype(s):
                    sample = non_null.astype(str)
                    # check date format mixes
                    if not sample.empty:
                        # limit to first 1000 non-null values for speed
                        vals = sample.iloc[:1000].astype(str)
                        mmdd_count = sum(1 for v in vals if _matches_pattern(v, mmdd_pat))
                        iso_count = sum(1 for v in vals if _matches_pattern(v, iso_pat))
                        total = len(vals)
                        if total > 0 and (mmdd_count / total) > 0.1 and (iso_count / total) > 0.1:
                            col_info["quality_flags"].append("mixed_date_formats")

                        # possible abbreviations
                        try:
                            avg_len = float(vals.str.len().mean())
                            if avg_len > 0 and avg_len < 6:
                                col_info["quality_flags"].append("possible_abbreviations")
                        except Exception:
                            pass
            except Exception:
                pass

            cols[col] = col_info

            # candidate join keys detection
            if col.lower().endswith("_id"):
                id_candidates.setdefault(col, []).append(table_name)

        profile["tables"][table_name] = {"row_count": row_count, "columns": cols}

    # assemble candidate_join_keys (columns that appear in 2 or more tables)
    for col, tables in id_candidates.items():
        uniq = sorted(set(tables))
        if len(uniq) >= 2:
            profile["candidate_join_keys"][col] = uniq

    out_path = PROFILES_DIR / f"profile_combined_{run_id}.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(profile, fh, indent=2)

    # audit log
    try:
        logger = AuditLogger(run_id)
        logger.log(agent="profiler", action="completed", profile_path=str(out_path))
    except Exception:
        pass

    return str(out_path)
