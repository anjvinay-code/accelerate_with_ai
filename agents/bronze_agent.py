"""Bronze agent implementation: apply Bronze STTM to CSVs and write parquet."""
from typing import List
from pathlib import Path
import pandas as pd
from datetime import datetime, timezone

from core.config import BRONZE_DIR


def _apply_type_cast(df: pd.DataFrame, col: str, logic: str):
    logic = str(logic).lower()
    if logic == "datetime" or logic == "date":
        df[col] = pd.to_datetime(df[col], errors="coerce")
    elif logic == "float":
        df[col] = pd.to_numeric(df[col], errors="coerce")
    elif logic == "int":
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    else:
        df[col] = df[col].astype(str)


def run(input_files: List[str], sttm_path: str, run_id: str) -> List[str]:
    BRONZE_DIR.mkdir(parents=True, exist_ok=True)
    import pandas as pd

    sttm = pd.read_csv(sttm_path)
    out_paths = []
    for fp in input_files:
        p = Path(fp)
        table = p.stem
        table_rules = sttm[sttm["source_table"] == table]
        if table_rules.empty:
            # try matching without suffix
            base = table.replace("_bronze", "").replace("_silver", "")
            table_rules = sttm[sttm["source_table"] == base]
        try:
            df = pd.read_csv(p)
        except Exception:
            continue

        # apply rules
        for _, r in table_rules.iterrows():
            ttype = str(r["transformation_type"]).lower()
            src = r["source_column"]
            tgt = r["target_column"]
            logic = r.get("transformation_logic", "")
            if ttype == "type_cast":
                if src in df.columns:
                    _apply_type_cast(df, src, logic)
                    if src != tgt:
                        df = df.rename(columns={src: tgt})
            elif ttype == "passthrough":
                if src in df.columns and src != tgt:
                    df = df.rename(columns={src: tgt})
            elif ttype == "metadata_inject":
                # handled below
                pass

        # inject metadata
        df["_load_timestamp"] = datetime.now(timezone.utc).isoformat()
        df["_source_file"] = str(p)

        out_name = BRONZE_DIR / f"{table}_bronze_{run_id}.parquet"
        df.to_parquet(out_name, index=False)
        out_paths.append(str(out_name))

    return out_paths
