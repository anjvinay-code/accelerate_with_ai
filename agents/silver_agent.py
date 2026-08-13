from pathlib import Path
from typing import List

import pandas as pd

from core.config import SILVER_DIR
from core.audit import AuditLogger


def _apply_silver_logic(df: pd.DataFrame, col: str, logic: str):
    l = str(logic).lower()
    if "date" in l or "datetime" in l:
        df[col] = pd.to_datetime(df[col], errors="coerce").dt.strftime("%Y-%m-%d")
    elif "lower" in l:
        df[col] = df[col].astype(str).str.lower()
    elif "upper" in l:
        df[col] = df[col].astype(str).str.upper()
    elif "strip" in l or "trim" in l:
        df[col] = df[col].astype(str).str.strip()
    # numeric casts
    elif "int" in l or "integer" in l:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    elif "float" in l or "numeric" in l:
        df[col] = pd.to_numeric(df[col], errors="coerce")


def run(bronze_paths: List[str], sttm_path: str, run_id: str) -> List[str]:
    SILVER_DIR.mkdir(parents=True, exist_ok=True)
    sttm = pd.read_csv(sttm_path)
    out_paths = []
    logger = AuditLogger(run_id)

    for p in bronze_paths:
        path = Path(p)
        base = path.stem.replace(f"_bronze_{run_id}", "")
        df = pd.read_parquet(path)
        in_shape = df.shape

        # match sttm rows for this table (flexible)
        rules = sttm[sttm.source_table == base]
        if rules.empty:
            # try matching with original bronze table name that includes suffix
            rules = sttm[sttm.source_table == f"{base}"]

        out_df = df.copy()

        # apply per-column rules
        for _, r in rules.iterrows():
            src_col = r.source_column
            tgt_col = r.target_column
            logic = r.transformation_logic
            if src_col not in out_df.columns:
                continue
            _apply_silver_logic(out_df, src_col, logic)
            # rename if needed
            if src_col != tgt_col:
                out_df = out_df.rename(columns={src_col: tgt_col})

        # deduplicate
        out_df = out_df.drop_duplicates()

        # surrogate key
        pk_name = f"pk_{base}_silver_id"
        out_df.insert(0, pk_name, range(1, len(out_df) + 1))

        out_path = SILVER_DIR / f"{base}_silver_{run_id}.parquet"
        out_df.to_parquet(out_path, index=False)
        out_paths.append(str(out_path))

        logger.log(agent="silver_agent", action="written", input_shape=str(in_shape), output_shape=str(out_df.shape), output=str(out_path))

    return out_paths


__all__ = ["run"]
