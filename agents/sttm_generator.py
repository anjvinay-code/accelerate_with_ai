"""STTM generator (deterministic fallback implementation).

This module provides simple, deterministic STTM generators so the
training quickstart can run without an LLM. It follows the contract
in the Quick-Start: produces CSVs with the 8 required columns.
"""
from typing import List
import json
import csv
from pathlib import Path

from core.config import STTM_DIR, PROFILES_DIR


def _map_dtype_to_logic(dtype: str) -> (str, str):
    d = dtype.lower()
    if "datetime" in d or "date" in d or d.startswith("datetime"):
        return "type_cast", "datetime"
    if "int" in d:
        return "type_cast", "int"
    if "float" in d or "double" in d or "decimal" in d:
        return "type_cast", "float"
    return "type_cast", "str"


def generate_bronze_sttm(profile_path: str, business_intent: str, run_id: str) -> str:
    """Read a profile JSON and generate a conservative Bronze STTM CSV.

    The Bronze STTM maps every source column to a type_cast target and
    injects two metadata_inject rows per table.
    """
    p = Path(profile_path)
    STTM_DIR.mkdir(parents=True, exist_ok=True)
    with open(p, "r", encoding="utf-8") as fh:
        profile = json.load(fh)

    out = STTM_DIR / f"sttm_bronze_{run_id}.csv"
    cols = [
        "source_schema",
        "source_table",
        "source_column",
        "target_schema",
        "target_table",
        "target_column",
        "transformation_type",
        "transformation_logic",
    ]
    with open(out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols)
        writer.writeheader()
        for table, meta in profile.get("tables", {}).items():
            for col, info in meta.get("columns", {}).items():
                ttype, logic = _map_dtype_to_logic(info.get("dtype", ""))
                writer.writerow({
                    "source_schema": "landing",
                    "source_table": table,
                    "source_column": col,
                    "target_schema": "bronze",
                    "target_table": f"{table}_bronze",
                    "target_column": col,
                    "transformation_type": ttype,
                    "transformation_logic": logic,
                })
            # metadata inject rows
            writer.writerow({
                "source_schema": "landing",
                "source_table": table,
                "source_column": "*",
                "target_schema": "bronze",
                "target_table": f"{table}_bronze",
                "target_column": "_load_timestamp",
                "transformation_type": "metadata_inject",
                "transformation_logic": "_load_timestamp",
            })
            writer.writerow({
                "source_schema": "landing",
                "source_table": table,
                "source_column": "*",
                "target_schema": "bronze",
                "target_table": f"{table}_bronze",
                "target_column": "_source_file",
                "transformation_type": "metadata_inject",
                "transformation_logic": "_source_file",
            })

    return str(out)


def generate_silver_sttm(bronze_paths: List[str], bronze_sttm_path: str, business_intent: str, run_id: str) -> str:
    """Create a simple Silver STTM based on bronze parquet schemas.

    This fallback marks date columns for standardisation and text types
    for lowercase where flagged. It is intentionally conservative.
    """
    STTM_DIR.mkdir(parents=True, exist_ok=True)
    out = STTM_DIR / f"sttm_silver_{run_id}.csv"
    bronze_sttm = Path(bronze_sttm_path)
    # naive strategy: read bronze sttm and promote datetime -> date normalise
    import pandas as pd

    df = pd.read_csv(bronze_sttm)
    cols = [
        "source_schema",
        "source_table",
        "source_column",
        "target_schema",
        "target_table",
        "target_column",
        "transformation_type",
        "transformation_logic",
    ]
    with open(out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols)
        writer.writeheader()
        for _, r in df.iterrows():
            ttype = r["transformation_type"]
            logic = r["transformation_logic"]
            # if bronze suggested datetime, ask silver to normalise dates
            if str(logic).lower() == "datetime":
                writer.writerow({**r, "transformation_type": "date", "transformation_logic": "date"})
            else:
                # default: passthrough (no-op) at Silver unless text normalisation makes sense
                if str(logic).lower() == "str":
                    writer.writerow({**r, "transformation_type": "lowercase", "transformation_logic": "lowercase"})
                else:
                    writer.writerow(r.to_dict())
    return str(out)


def generate_gold_sttm(silver_paths: List[str], silver_sttm_path: str, business_intent: str, run_id: str) -> str:
    """Produce a simple Gold STTM that aggregates numeric columns by a category.

    This is intentionally simplistic: it will generate a single aggregate
    target table if possible.
    """
    STTM_DIR.mkdir(parents=True, exist_ok=True)
    out = STTM_DIR / f"sttm_gold_{run_id}.csv"
    import pandas as pd

    # Preferentially look for sales_data and products silver tables.
    sample_table = None
    sales_path = None
    products_path = None
    cols = [
        "source_schema",
        "source_table",
        "source_column",
        "target_schema",
        "target_table",
        "target_column",
        "transformation_type",
        "transformation_logic",
    ]
    for p in silver_paths:
        sp = str(p)
        if "sales_data" in sp and sales_path is None:
            sales_path = p
        if "products" in sp and products_path is None:
            products_path = p

    # If we have both, read them and craft a join+aggregate STTM.
    if sales_path and products_path:
        try:
            sales_df = pd.read_parquet(sales_path)
            products_df = pd.read_parquet(products_path)
            # find numeric and categorical columns with heuristics
            def choose_numeric(cols, df):
                # prefer domain names, avoid surrogate keys / id columns
                prefer = ["total_amount", "total", "amount", "price", "quantity", "qty", "sales"]
                candidates = [c for c in cols if pd.api.types.is_numeric_dtype(df[c])]
                # exclude id-like and pk-like columns
                candidates = [c for c in candidates if not ("id" in c.lower() or c.lower().startswith("pk_"))]
                for p in prefer:
                    for c in candidates:
                        if p in c.lower():
                            return c
                return candidates[0] if candidates else None

            def choose_category(cols, df):
                prefer = ["category", "category_name", "product_category", "product_name", "store_name", "name", "region"]
                candidates = [c for c in cols if pd.api.types.is_string_dtype(df[c]) or pd.api.types.is_object_dtype(df[c])]
                for p in prefer:
                    for c in candidates:
                        if p in c.lower():
                            return c
                return candidates[0] if candidates else None

            num_cols = list(sales_df.columns)
            cat_cols = list(products_df.columns)
            target_table = f"sales_products_gold"
            with open(out, "w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=cols)
                writer.writeheader()
                if cat_cols and num_cols:
                    cat = choose_category(cat_cols, products_df)
                    num = choose_numeric(num_cols, sales_df)
                    # join rule between sales and products on product_id
                    writer.writerow({
                        "source_schema": "silver",
                        "source_table": Path(sales_path).stem,
                        "source_column": "product_id",
                        "target_schema": "gold",
                        "target_table": target_table,
                        "target_column": "product_id",
                        "transformation_type": "join",
                        "transformation_logic": f"join_left:{Path(sales_path).stem}:{Path(products_path).stem}:product_id",
                    })
                    # group_by row
                    writer.writerow({
                        "source_schema": "silver",
                        "source_table": Path(products_path).stem,
                        "source_column": cat,
                        "target_schema": "gold",
                        "target_table": target_table,
                        "target_column": cat,
                        "transformation_type": "group_by",
                        "transformation_logic": cat,
                    })
                    # aggregate row
                    writer.writerow({
                        "source_schema": "silver",
                        "source_table": Path(sales_path).stem,
                        "source_column": num,
                        "target_schema": "gold",
                        "target_table": target_table,
                        "target_column": f"total_{num}",
                        "transformation_type": "aggregate",
                        "transformation_logic": f"SUM({num}) AS total_{num}",
                    })
            return str(out)
        except Exception:
            # fall through to the generic path
            pass

    with open(out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols)
        writer.writeheader()
        if sample_table is None:
            return str(out)
        name, df = sample_table
        # find a categorical column and a numeric column (apply heuristics)
        cols_list = list(df.columns)
        num = None
        cat = None
        # numeric candidates, excluding id-like and pk-like columns
        numeric_candidates = [c for c in cols_list if pd.api.types.is_numeric_dtype(df[c])]
        numeric_candidates = [c for c in numeric_candidates if not ("id" in c.lower() or c.lower().startswith("pk_"))]
        for p in ["total_amount", "total", "amount", "price", "quantity", "qty", "sales"]:
            for c in numeric_candidates:
                if p in c.lower():
                    num = c
                    break
            if num:
                break
        if not num and numeric_candidates:
            num = numeric_candidates[0]

        cat_candidates = [c for c in cols_list if pd.api.types.is_string_dtype(df[c]) or pd.api.types.is_object_dtype(df[c])]
        for p in ["category", "category_name", "product_category", "product_name", "store_name", "name", "region"]:
            for c in cat_candidates:
                if p in c.lower():
                    cat = c
                    break
            if cat:
                break
        if not cat and cat_candidates:
            cat = cat_candidates[0]
        target_table = f"{name}_gold"
        if cat and num:
            # group_by row
            writer.writerow({
                "source_schema": "silver",
                "source_table": name,
                "source_column": cat,
                "target_schema": "gold",
                "target_table": target_table,
                "target_column": cat,
                "transformation_type": "group_by",
                "transformation_logic": cat,
            })
            # aggregate row
            writer.writerow({
                "source_schema": "silver",
                "source_table": name,
                "source_column": num,
                "target_schema": "gold",
                "target_table": target_table,
                "target_column": f"total_{num}",
                "transformation_type": "aggregate",
                "transformation_logic": f"SUM({num}) AS total_{num}",
            })
    return str(out)
