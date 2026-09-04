"""Gold agent implementation: execute joins and aggregates per Gold STTM."""
from typing import List
from pathlib import Path
import pandas as pd
import re

from core.config import GOLD_DIR


def _parse_join_logic(logic: str):
    # expected format: join_left:table_a:table_b:key
    parts = str(logic).split(":")
    if len(parts) == 4 and parts[0] == "join_left":
        return parts[1], parts[2], parts[3]
    return None


def _parse_aggregate(logic: str):
    # expected: SUM(col) AS alias
    m = re.match(r"\s*(SUM|AVG|COUNT|MAX|MIN)\s*\(([^)]+)\)\s*(?:AS\s+(.+))?", logic, re.I)
    if not m:
        return None
    func = m.group(1).upper()
    col = m.group(2)
    alias = m.group(3) or f"{func.lower()}_{col}"
    return func, col, alias


def run(silver_paths: List[str], sttm_path: str, business_intent: str, run_id: str) -> List[str]:
    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    sttm = pd.read_csv(sttm_path)
    # load silver tables into dict
    tables = {}
    for p in silver_paths:
        try:
            df = pd.read_parquet(p)
            name = Path(p).stem
            tables[name] = df
        except Exception:
            continue

    out_paths = []
    # group by target_table
    for target_table, group in sttm.groupby("target_table"):
        df_work = None
        agg_specs = []
        group_cols = []
        for _, r in group.iterrows():
            ttype = str(r["transformation_type"]).lower()
            logic = str(r.get("transformation_logic", ""))
            src_table = r["source_table"]
            src_col = r["source_column"]
            tgt_col = r["target_column"]

            if ttype == "join":
                parsed = _parse_join_logic(logic)
                if parsed:
                    a, b, key = parsed
                    a_df = tables.get(a)
                    if a_df is None:
                        a_df = tables.get(f"{a}_silver")
                    b_df = tables.get(b)
                    if b_df is None:
                        b_df = tables.get(f"{b}_silver")
                    if a_df is None:
                        a_df = tables.get(list(tables.keys())[0])
                    if b_df is None:
                        b_df = tables.get(list(tables.keys())[0])
                    df_work = a_df.merge(b_df, on=key, how="left")
            elif ttype == "group_by":
                group_cols.append(tgt_col)
            elif ttype == "aggregate":
                parsed = _parse_aggregate(logic)
                if parsed:
                    agg_specs.append(parsed)

        if df_work is None:
            # fallback: pick first silver table
            if tables:
                df_work = next(iter(tables.values())).copy()
            else:
                continue

        # apply aggregates
        if agg_specs and group_cols:
            agg_dict = {}
            rename_map = {}
            for func, col, alias in agg_specs:
                func = func.upper()
                if func == "SUM":
                    agg_dict[alias] = (col, "sum")
                elif func == "AVG":
                    agg_dict[alias] = (col, "mean")
                elif func == "COUNT":
                    agg_dict[alias] = (col, "count")
                elif func == "MAX":
                    agg_dict[alias] = (col, "max")
                elif func == "MIN":
                    agg_dict[alias] = (col, "min")

            # pandas named aggregation
            named = {alias: (col, op) for alias, (col, op) in agg_dict.items()}
            df_grouped = df_work.groupby(group_cols).agg(**named).reset_index()
            df_out = df_grouped
        else:
            df_out = df_work

        # keep only target columns if they exist in df_out
        # insert pk
        df_out.insert(0, "pk_gold_id", range(1, len(df_out) + 1))
        out_name = GOLD_DIR / f"{target_table}_{run_id}.parquet"
        df_out.to_parquet(out_name, index=False)
        out_paths.append(str(out_name))

    return out_paths
