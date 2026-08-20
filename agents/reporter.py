from pathlib import Path
import json
import re
from datetime import datetime, timezone
from typing import List, Optional

import pandas as pd
import duckdb

from core.config import REPORTS_DIR, GITHUB_TOKEN, GITHUB_BASE_URL, GITHUB_MODEL, LLM_PROVIDER, GROQ_API_KEY, GROQ_ENDPOINT
from core.audit import AuditLogger

try:
    import plotly.express as px
except Exception:
    px = None


_llm = None


def _make_llm():
    global _llm
    if _llm is not None:
        return _llm
    # Support multiple providers (groq or github)
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


def _extract_block(kind: str, text: str) -> Optional[str]:
    if not text:
        return None
    m = re.search(rf"```{kind}\\n([\\s\\S]*?)```", text, re.I)
    if m:
        return m.group(1).strip()
    return None


def _validate_sql(sql: str, allowed_tables: List[str]) -> (bool, str):
    if not sql:
        return False, "empty"
    lower = sql.lower()
    # forbid destructive or DDL statements
    forbidden = ["drop", "delete", "insert", "update", "alter", "create", "attach", "detach", "truncate"]
    for w in forbidden:
        if re.search(rf"\b{w}\b", lower):
            return False, f"forbidden token: {w}"
    # require a SELECT
    if not re.search(r"^\s*select\b", lower):
        return False, "not a SELECT statement"
    # ensure only allowed table names are referenced
    refs = set()
    for t in allowed_tables:
        if re.search(rf"\b{re.escape(t.lower())}\b", lower):
            refs.add(t)
    if not refs:
        return False, "no allowed table referenced"
    # disallow multiple statements
    if ";" in sql.strip().rstrip(";"):
        return False, "multiple statements or stray semicolons"
    return True, "ok"


def generate_report(gold_paths: List[str], business_intent: str, run_id: str) -> str:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    logger = AuditLogger(run_id)
    if not gold_paths:
        raise ValueError("No gold paths provided")

    # Build DuckDB in-memory connection and register gold parquet tables
    conn = duckdb.connect(database=':memory:')
    table_names = []
    table_map = {}
    for p in gold_paths:
        orig_name = Path(p).stem
        # sanitize to a safe DuckDB identifier: replace non-word chars with underscore
        safe_name = re.sub(r"\W+", "_", orig_name).strip("_").lower() or orig_name
        table_names.append(safe_name)
        table_map[orig_name] = safe_name
        try:
            df_tbl = pd.read_parquet(p)
            # rename dataframe columns that conflict with DuckDB? keep original columns
            conn.register(safe_name, df_tbl)
        except Exception:
            # last-resort: register an empty dataframe with same (safe) name
            conn.register(safe_name, pd.DataFrame())

    # Build a schema context string including sample rows (use safe table names)
    schema_context = {}
    for name in table_names:
        try:
            sample = conn.execute(f"SELECT * FROM \"{name}\" LIMIT 5").df()
            cols = {c: str(t) for c, t in zip(sample.columns, sample.dtypes)}
            schema_context[name] = {"columns": cols, "sample": sample.head(3).to_dict(orient="records")}
        except Exception:
            schema_context[name] = {"columns": {}, "sample": []}

    table_list = ", ".join(table_names)
    # include mapping to help LLM reference original file/table names
    mapping_note = {"original_to_safe": table_map}

    prompt = (
        "You are given gold table schemas and samples. Produce exactly three sections in this exact order:\n"
        "\n1) A single fenced ```sql``` block containing only one SQL SELECT statement.\n"
        "   - The SQL must reference only the provided table names and must use those exact names (case-insensitive).\n"
        "   - Do NOT include any explanatory text inside the code fence, and do NOT return multiple statements or semicolons.\n"
        "\n2) A NARRATIVE: a short human-readable explanation (plain text).\n"
        "\n3) CHARTS: a single fenced ```json``` block containing an array of chart specs, each like {\"type\":\"bar\",\"x\":\"col\",\"y\":\"col2\",\"title\":\"...\"}.\n"
        "\nStrict rules: Only reference these tables: " + table_list + ". Only return valid, executable SQL (DuckDB compatible). If you cannot produce SQL, respond with an empty SQL fence.\n"
        "\nExample output:\n```sql\nSELECT store_id, SUM(sales) as total_sales FROM \"gold_sales\" GROUP BY store_id\n```\n\nNARRATIVE:\nA short explanation of what the query returns.\n\nCHARTS:\n```json\n[{\"type\":\"bar\",\"x\":\"store_id\",\"y\":\"total_sales\",\"title\":\"Sales by Store\"}]\n```\n"
        f"\nSchemas: {json.dumps(schema_context)}\nTable name mapping: {json.dumps(mapping_note)}\nBusiness intent: {business_intent}\n"
    )

    resp = _call_llm(prompt)
    sql = _extract_block("sql", resp) if resp else None
    narrative = None
    charts_json = None
    if resp:
        narrative_m = re.search(r"NARRATIVE:\s*([\s\S]*?)(?:CHARTS:|$)", resp)
        narrative = narrative_m.group(1).strip() if narrative_m else None
        charts_json = _extract_block("json", resp)

    # Validate SQL and, if invalid, ask LLM to correct once with explicit error
    validated = False
    if sql:
        ok, reason = _validate_sql(sql, table_names)
        if ok:
            validated = True
        else:
            # Retry: ask for a single corrected SQL only
            retry_prompt = (
                "The previously returned SQL is invalid: " + reason + ".\n"
                "Please return only a single fenced ```sql``` block containing a single valid SELECT statement that references only these tables: "
                + ", ".join(table_names) + ". Do not include any other text inside the fence.\n"
                "If you cannot produce such a query, return an empty ```sql``` fence.\n"
                "Original response:\n" + (resp or "")
            )
            resp2 = _call_llm(retry_prompt)
            sql = _extract_block("sql", resp2) if resp2 else None
            if sql:
                ok2, reason2 = _validate_sql(sql, table_names)
                if ok2:
                    validated = True
                else:
                    validated = False

    # Execute SQL via DuckDB, retry once, else fallback
    result_df = None
    executed_sql = None
    if sql:
        try:
            executed_sql = sql
            result_df = conn.execute(sql).df()
        except Exception:
            # Retry once with a simple wrapper
            try:
                executed_sql = sql
                result_df = conn.execute(sql).df()
            except Exception:
                result_df = None

    if result_df is None:
        # fallback to first table limited select
        first_table = table_names[0]
        executed_sql = f"SELECT * FROM \"{first_table}\" LIMIT 20"
        try:
            result_df = conn.execute(executed_sql).df()
        except Exception:
            # give up and produce empty df
            result_df = pd.DataFrame()

    if not narrative:
        narrative = f"Answer for intent: {business_intent}. Generated at {datetime.now(timezone.utc).isoformat()}"

    # Render charts
    chart_html = ""
    if charts_json:
        try:
            specs = json.loads(charts_json)
            if px is not None and isinstance(specs, list) and len(specs) > 0:
                spec = specs[0]
                if spec.get("type") == "bar" and spec.get("x") in result_df.columns and spec.get("y") in result_df.columns:
                    fig = px.bar(result_df.head(10), x=spec["x"], y=spec["y"], title=spec.get("title", "Chart"))
                    chart_html = fig.to_html(full_html=False, include_plotlyjs="cdn")
        except Exception:
            chart_html = ""
    else:
        if px is not None:
            numeric = [c for c in result_df.columns if pd.api.types.is_numeric_dtype(result_df[c])]
            if numeric and len(result_df) > 0:
                fig = px.bar(result_df.head(10), x=result_df.columns[0], y=numeric[0], title="Top 10")
                chart_html = fig.to_html(full_html=False, include_plotlyjs="cdn")

    table_html = result_df.head(100).to_html(index=False)

    html = f"""<!doctype html>
<html>
<head><meta charset='utf-8'><title>Report {run_id}</title></head>
<body>
<h1>Report — {run_id}</h1>
<h2>Intent</h2>
<p>{business_intent}</p>
<h2>Narrative</h2>
<pre>{narrative}</pre>
<h2>SQL</h2>
<pre>{executed_sql}</pre>
<h2>Charts</h2>
{chart_html}
<h2>Data</h2>
{table_html}
<footer>Generated {datetime.now(timezone.utc).isoformat()}</footer>
</body></html>"""

    out_html = REPORTS_DIR / f"report_{run_id}.html"
    with open(out_html, "w", encoding="utf-8") as fh:
        fh.write(html)

    out_json = REPORTS_DIR / f"report_{run_id}.json"
    with open(out_json, "w", encoding="utf-8") as fh:
        json.dump({"run_id": run_id, "intent": business_intent, "sql": executed_sql}, fh)

    logger.log(agent="reporter", action="generated", output=str(out_html))
    return str(out_html)


__all__ = ["generate_report"]
