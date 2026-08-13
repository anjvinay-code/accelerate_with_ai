from pathlib import Path
from typing import List, Dict

import pandas as pd

from core.config import GOLD_DIR
from core.audit import AuditLogger


def _parse_join_logic(logic: str):
    # expected format: join_left:table_a:table_b:key
    parts = str(logic).split(":")
    if len(parts) == 4 and parts[0].startswith("join"):
        return parts[1], parts[2], parts[3]
    return None


def run(silver_paths: List[str], sttm_path: str, business_intent: str, run_id: str) -> List[str]:
    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    sttm = pd.read_csv(sttm_path)
    tables: Dict[str, pd.DataFrame] = {}
    for p in silver_paths:
        df = pd.read_parquet(p)
        tables[Path(p).stem] = df

    out_paths = []
    logger = AuditLogger(run_id)

    # group STTM by target_table
    for target_table, group in sttm.groupby("target_table"):
        df_result = None
        # look for join rules in group
        for _, r in group.iterrows():
            if str(r.transformation_type).lower() == "join":
                parsed = _parse_join_logic(r.transformation_logic)
                if parsed:
                    a, b, key = parsed
                    a_df = tables.get(a)
                    if a_df is None:
                        a_df = tables.get(f"{a}")
                    b_df = tables.get(b)
                    if b_df is None:
                        b_df = tables.get(f"{b}")
                    if a_df is None or b_df is None:
                        continue
                    df_result = a_df.merge(b_df, on=key, how="left")
        if df_result is None:
            # build from first table reference in group
            src = group.iloc[0].source_table
            df_result = tables.get(src)
            if df_result is None:
                df_result = tables.get(f"{src}")
            if df_result is None:
                df_result = pd.DataFrame()

        # apply aggregates and group_by
        # collect group_by columns
        group_cols = [r.target_column for _, r in group.iterrows() if str(r.transformation_type).lower() == "group_by"]
        agg_map = {}
        for _, r in group.iterrows():
            if str(r.transformation_type).lower() == "aggregate":
                # simplistic parse: SUM(col) AS alias
                logic = str(r.transformation_logic)
                if logic.upper().startswith("SUM("):
                    col = logic[4:logic.find(")")]
                    alias = r.target_column
                    agg_map[alias] = (col, "sum")

        if group_cols and agg_map:
            agg_dict = {v[0]: v[1] for v in agg_map.values()}
            df_result = df_result.groupby(group_cols).agg(agg_dict).reset_index()
            # rename aggregated columns to aliases
            rename_map = {v[0]: k for k, v in agg_map.items()}
            df_result = df_result.rename(columns=rename_map)

        # keep only target columns
        target_cols = list(group.target_column.dropna().unique())
        keep = [c for c in target_cols if c in df_result.columns]
        df_out = df_result[keep] if keep else df_result

        # surrogate key
        df_out.insert(0, "pk_gold_id", range(1, len(df_out) + 1))

        out_path = GOLD_DIR / f"{target_table}_{run_id}.parquet"
        df_out.to_parquet(out_path, index=False)
        out_paths.append(str(out_path))
        logger.log(agent="gold_agent", action="written", output=str(out_path), rows=len(df_out))

    return out_paths


__all__ = ["run"]
