from pathlib import Path
from datetime import datetime, timezone
from typing import List

import pandas as pd

from core.config import BRONZE_DIR
from core.audit import AuditLogger


def _apply_type_cast(df: pd.DataFrame, col: str, logic: str):
    if logic == "datetime":
        df[col] = pd.to_datetime(df[col], errors="coerce")
    elif logic == "float":
        df[col] = pd.to_numeric(df[col], errors="coerce")
    elif logic == "int":
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    elif logic == "str":
        df[col] = df[col].astype(str)


def run(input_files: List[str], sttm_path: str, run_id: str) -> List[str]:
    BRONZE_DIR.mkdir(parents=True, exist_ok=True)
    sttm = pd.read_csv(sttm_path)
    out_paths = []
    logger = AuditLogger(run_id)

    for fp in input_files:
        p = Path(fp)
        table = p.stem
        df = pd.read_csv(p)
        in_shape = df.shape

        # slice sttm for this table
        rules = sttm[sttm.source_table == table]
        # apply rules
        out_df = pd.DataFrame()
        for _, r in rules.iterrows():
            ttype = str(r.transformation_type)
            src_col = r.source_column
            tgt_col = r.target_column
            logic = r.transformation_logic
            if ttype == "type_cast":
                if src_col in df.columns:
                    out_df[tgt_col] = df[src_col]
                    _apply_type_cast(out_df, tgt_col, logic)
            elif ttype == "passthrough":
                if src_col in df.columns:
                    out_df[tgt_col] = df[src_col]
            elif ttype == "metadata_inject":
                # handled later
                continue
            else:
                # unknown types: try passthrough
                if src_col in df.columns:
                    out_df[tgt_col] = df[src_col]

        # ensure metadata columns
        out_df["_load_timestamp"] = datetime.now(timezone.utc).isoformat()
        out_df["_source_file"] = str(p)

        out_path = BRONZE_DIR / f"{table}_bronze_{run_id}.parquet"
        out_df.to_parquet(out_path, index=False)
        out_paths.append(str(out_path))

        logger.log(agent="bronze_agent", action="written", input_shape=str(in_shape), output_shape=str(out_df.shape), output=str(out_path))

    return out_paths


__all__ = ["run"]
