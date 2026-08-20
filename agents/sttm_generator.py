from pathlib import Path
import json
import re
import os
import pandas as pd
from typing import List, Optional

from core.config import (
    STTM_DIR,
    PROFILES_DIR,
    BRONZE_DIR,
    SILVER_DIR,
    GOLD_DIR,
    GITHUB_TOKEN,
    GITHUB_BASE_URL,
    GITHUB_MODEL,
    LLM_PROVIDER,
    GROQ_API_KEY,
    GROQ_ENDPOINT,
)
from core.audit import AuditLogger


_llm = None


def _make_llm():
    global _llm
    if _llm is not None:
        return _llm
    # Provider switch: support GitHub Models or Groq
    if LLM_PROVIDER == "groq":
        if not GROQ_API_KEY:
            return None
        try:
            import requests
            from types import SimpleNamespace

            class GroqClient:
                def __init__(self, api_key, endpoint):
                    self.api_key = api_key
                    self.endpoint = endpoint

                def invoke(self, prompt: str):
                    headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
                    payload = {"input": prompt}
                    r = requests.post(self.endpoint, headers=headers, json=payload, timeout=30)
                    r.raise_for_status()
                    data = r.json()
                    # Try common keys that may hold text output
                    text = None
                    if isinstance(data, dict):
                        text = data.get("output") or data.get("result") or data.get("text") or json.dumps(data)
                    else:
                        text = str(data)
                    return SimpleNamespace(content=text)

            _llm = GroqClient(GROQ_API_KEY, GROQ_ENDPOINT)
            return _llm
        except Exception:
            return None

    # default: GitHub / LangChain ChatOpenAI
    if not GITHUB_TOKEN:
        return None
    try:
        from langchain_openai import ChatOpenAI

        _llm = ChatOpenAI(api_key=GITHUB_TOKEN, base_url=GITHUB_BASE_URL, model=GITHUB_MODEL, temperature=0)
        return _llm
    except Exception:
        return None


def _call_llm(prompt: str) -> Optional[str]:
    try:
        llm = _make_llm()
        if not llm:
            return None
        return llm.invoke(prompt).content
    except Exception:
        return None


def _extract_csv(text: str) -> Optional[str]:
    if not text:
        return None
    # look for ```csv fences
    m = re.search(r"```csv\n([\s\S]*?)```", text, re.I)
    if m:
        return m.group(1).strip()
    # fallback: attempt to find lines with commas and a header
    lines = text.strip().splitlines()
    csv_lines = [l for l in lines if "," in l]
    if len(csv_lines) >= 2:
        return "\n".join(csv_lines)
    return None


def _infer_type_from_dtype(dtype: str) -> str:
    if "datetime" in dtype or "date" in dtype:
        return "datetime"
    if "int" in dtype or "Int64" in dtype:
        return "int"
    if "float" in dtype or "double" in dtype:
        return "float"
    return "str"


def _ensure_sttm_dir():
    STTM_DIR.mkdir(parents=True, exist_ok=True)


def generate_bronze_sttm(profile_path: str, business_intent: str, run_id: str) -> str:
    """Generate a Bronze STTM CSV. If an LLM is configured, ask it; otherwise use deterministic rules."""
    _ensure_sttm_dir()
    with open(profile_path, "r", encoding="utf-8") as fh:
        profile = json.load(fh)

    # Attempt LLM generation first
    prompt = """
Generate a CSV with columns: source_schema, source_table, source_column, target_schema, target_table, target_column, transformation_type, transformation_logic.
Profile JSON:
""" + json.dumps(profile)
    llm_resp = _call_llm(prompt)
    csv_text = _extract_csv(llm_resp) if llm_resp else None
    rows = []
    if csv_text:
        try:
            df = pd.read_csv(pd.compat.StringIO(csv_text))
            # validate required columns
            required = {"source_schema", "source_table", "source_column", "target_schema", "target_table", "target_column", "transformation_type", "transformation_logic"}
            if required.issubset(set(df.columns)):
                out = STTM_DIR / f"sttm_bronze_{run_id}.csv"
                df.to_csv(out, index=False)
                AuditLogger(run_id).log(agent="sttm_generator", action="generated_bronze_llm", output=str(out))
                return str(out)
        except Exception:
            csv_text = None

    # Fallback deterministic generator
    for table, meta in profile.get("tables", {}).items():
        cols = meta.get("columns", {})
        for col, cmeta in cols.items():
            dtype = cmeta.get("dtype", "object")
            ttype = "type_cast"
            logic = _infer_type_from_dtype(dtype)
            rows.append({
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
        rows.append({
            "source_schema": "landing",
            "source_table": table,
            "source_column": "*",
            "target_schema": "bronze",
            "target_table": f"{table}_bronze",
            "target_column": "_load_timestamp",
            "transformation_type": "metadata_inject",
            "transformation_logic": "_load_timestamp",
        })
        rows.append({
            "source_schema": "landing",
            "source_table": table,
            "source_column": "*",
            "target_schema": "bronze",
            "target_table": f"{table}_bronze",
            "target_column": "_source_file",
            "transformation_type": "metadata_inject",
            "transformation_logic": "_source_file",
        })

    out = STTM_DIR / f"sttm_bronze_{run_id}.csv"
    pd.DataFrame(rows).to_csv(out, index=False)
    AuditLogger(run_id).log(agent="sttm_generator", action="generated_bronze", output=str(out))
    return str(out)


def generate_silver_sttm(bronze_paths: List[str], bronze_sttm_path: str, business_intent: str, run_id: str) -> str:
    _ensure_sttm_dir()
    # Try LLM-assisted silver generation
    try:
        bronze_schema = []
        for p in bronze_paths:
            df = pd.read_parquet(p)
            bronze_schema.append({"table": Path(p).stem, "columns": list(df.columns)})
        prompt = "Generate a Silver STTM CSV (columns as before). Bronze schemas:\n" + json.dumps(bronze_schema)
        llm_resp = _call_llm(prompt)
        csv_text = _extract_csv(llm_resp) if llm_resp else None
        if csv_text:
            try:
                df = pd.read_csv(pd.compat.StringIO(csv_text))
                required = {"source_schema", "source_table", "source_column", "target_schema", "target_table", "target_column", "transformation_type", "transformation_logic"}
                if required.issubset(set(df.columns)):
                    out = STTM_DIR / f"sttm_silver_{run_id}.csv"
                    df.to_csv(out, index=False)
                    AuditLogger(run_id).log(agent="sttm_generator", action="generated_silver_llm", output=str(out))
                    return str(out)
            except Exception:
                pass
    except Exception:
        pass

    # deterministic fallback
    bronze_tables = []
    for p in bronze_paths:
        bronze_tables.append(Path(p).stem.replace(f"_bronze_{run_id}", ""))

    rows = []
    df_bronze_sttm = pd.read_csv(bronze_sttm_path)
    for _, r in df_bronze_sttm.iterrows():
        src_table = r.source_table
        src_col = r.source_column
        logic = r.transformation_logic
        ttype = "passthrough"
        if logic == "datetime" or "date" in str(logic):
            ttype = "date"
            logic = "date"
        elif logic in ("int", "float"):
            ttype = "type_cast"
        rows.append({
            "source_schema": "bronze",
            "source_table": src_table,
            "source_column": src_col,
            "target_schema": "silver",
            "target_table": f"{src_table}_silver",
            "target_column": src_col,
            "transformation_type": ttype,
            "transformation_logic": logic,
        })

    out = STTM_DIR / f"sttm_silver_{run_id}.csv"
    pd.DataFrame(rows).to_csv(out, index=False)
    AuditLogger(run_id).log(agent="sttm_generator", action="generated_silver", output=str(out))
    return str(out)


def generate_gold_sttm(silver_paths: List[str], silver_sttm_path: str, business_intent: str, run_id: str) -> str:
    _ensure_sttm_dir()
    # Try LLM-assisted gold generation
    try:
        silver_schema = []
        for p in silver_paths:
            df = pd.read_parquet(p)
            silver_schema.append({"table": Path(p).stem, "columns": list(df.columns)})
        prompt = f"Generate a Gold STTM CSV for intent: {business_intent}. Silver schemas:\n" + json.dumps(silver_schema)
        llm_resp = _call_llm(prompt)
        csv_text = _extract_csv(llm_resp) if llm_resp else None
        if csv_text:
            try:
                df = pd.read_csv(pd.compat.StringIO(csv_text))
                required = {"source_schema", "source_table", "source_column", "target_schema", "target_table", "target_column", "transformation_type", "transformation_logic"}
                if required.issubset(set(df.columns)):
                    out = STTM_DIR / f"sttm_gold_{run_id}.csv"
                    df.to_csv(out, index=False)
                    AuditLogger(run_id).log(agent="sttm_generator", action="generated_gold_llm", output=str(out))
                    return str(out)
            except Exception:
                pass
    except Exception:
        pass

    # deterministic fallback
    rows = []
    cols_by_table = {}
    for p in silver_paths:
        df = pd.read_parquet(p)
        cols_by_table[Path(p).stem] = list(df.columns)

    if not cols_by_table:
        out = STTM_DIR / f"sttm_gold_{run_id}.csv"
        pd.DataFrame(rows).to_csv(out, index=False)
        AuditLogger(run_id).log(agent="sttm_generator", action="generated_gold", output=str(out))
        return str(out)

    base_table = list(cols_by_table.keys())[0]
    cols = cols_by_table[base_table]
    if "total_amount" in cols and "category" in cols:
        rows.append({
            "source_schema": "silver",
            "source_table": base_table,
            "source_column": "total_amount",
            "target_schema": "gold",
            "target_table": "gold_table",
            "target_column": "total_revenue",
            "transformation_type": "aggregate",
            "transformation_logic": "SUM(total_amount) AS total_revenue",
        })
        rows.append({
            "source_schema": "silver",
            "source_table": base_table,
            "source_column": "category",
            "target_schema": "gold",
            "target_table": "gold_table",
            "target_column": "category",
            "transformation_type": "group_by",
            "transformation_logic": "category",
        })
    else:
        for c in cols[:3]:
            rows.append({
                "source_schema": "silver",
                "source_table": base_table,
                "source_column": c,
                "target_schema": "gold",
                "target_table": "gold_table",
                "target_column": c,
                "transformation_type": "passthrough",
                "transformation_logic": "passthrough",
            })

    out = STTM_DIR / f"sttm_gold_{run_id}.csv"
    pd.DataFrame(rows).to_csv(out, index=False)
    AuditLogger(run_id).log(agent="sttm_generator", action="generated_gold", output=str(out))
    return str(out)


__all__ = [
    "generate_bronze_sttm",
    "generate_silver_sttm",
    "generate_gold_sttm",
]
