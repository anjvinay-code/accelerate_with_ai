"""Silver agent implementation: apply cleansing rules from Silver STTM."""
from typing import List
from pathlib import Path
import pandas as pd

from core.config import SILVER_DIR


def _apply_logic(df: pd.DataFrame, col: str, logic: str) -> pd.DataFrame:
    logic = str(logic).lower()
    if "drop null" in logic or "remove null" in logic:
        df = df.dropna(subset=[col])
    elif "fill null" in logic:
        if pd.api.types.is_numeric_dtype(df[col]):
            df[col] = df[col].fillna(df[col].mean())
        else:
            df[col] = df[col].fillna("")
    elif "date" in logic or "datetime" in logic:
        df[col] = pd.to_datetime(df[col], errors="coerce").dt.strftime("%Y-%m-%d")
    elif "lowercase" in logic:
        df[col] = df[col].astype(str).str.lower()
    elif "uppercase" in logic:
        df[col] = df[col].astype(str).str.upper()
    elif "strip" in logic or "trim" in logic:
        df[col] = df[col].astype(str).str.strip()
    return df


def run(bronze_paths: List[str], sttm_path: str, run_id: str) -> List[str]:
    SILVER_DIR.mkdir(parents=True, exist_ok=True)
    sttm = pd.read_csv(sttm_path)
    out_paths = []
    for bp in bronze_paths:
        p = Path(bp)
        base = p.stem
        # derive table name before _bronze_<run_id>
        table = base.split("_bronze_")[0]
        try:
            df = pd.read_parquet(p)
        except Exception:
            continue

        table_rules = sttm[sttm["source_table"] == table]
        if table_rules.empty:
            table_rules = sttm[sttm["source_table"] == base]

        for _, r in table_rules.iterrows():
            ttype = str(r["transformation_type"]).lower()
            src = r["source_column"]
            tgt = r["target_column"]
            logic = r.get("transformation_logic", "")
            if ttype in ("date", "drop null", "fill null", "lowercase", "uppercase", "strip") or "date" in logic or "lowercase" in logic:
                if src in df.columns:
                    df = _apply_logic(df, src, logic)
                    if src != tgt:
                        df = df.rename(columns={src: tgt})
            elif ttype == "deduplicate" or "dedup" in str(logic).lower():
                df = df.drop_duplicates()

        # insert surrogate key as first column
        pk_name = f"pk_{table}_silver_id"
        df.insert(0, pk_name, range(1, len(df) + 1))

        out_name = SILVER_DIR / f"{table}_silver_{run_id}.parquet"
        df.to_parquet(out_name, index=False)
        out_paths.append(str(out_name))

    return out_paths
