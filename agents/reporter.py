from pathlib import Path
import json
import re
from datetime import datetime, timezone
from typing import List, Optional

import pandas as pd

from core.config import REPORTS_DIR, GITHUB_TOKEN, GITHUB_BASE_URL, GITHUB_MODEL
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


def generate_report(gold_paths: List[str], business_intent: str, run_id: str) -> str:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    logger = AuditLogger(run_id)

    if not gold_paths:
        raise ValueError("No gold paths provided")
    df = pd.read_parquet(gold_paths[0])
    table_name = Path(gold_paths[0]).stem

    # Try LLM to generate SQL, narrative, charts
    schema_context = {"table": table_name, "columns": list(df.dtypes.apply(lambda t: str(t)).to_dict())}
    prompt = f"Given the schema {json.dumps(schema_context)} and intent: {business_intent}, return:\nSQL: ```sql ... ```\nNARRATIVE: ...\nCHARTS: ```json ... ```"
    resp = _call_llm(prompt)
    sql = None
    narrative = None
    charts_json = None
    if resp:
        sql = _extract_block("sql", resp)
        narrative = re.search(r"NARRATIVE:\s*([\s\S]*?)(?:CHARTS:|$)", resp)
        narrative = narrative.group(1).strip() if narrative else None
        charts_json = _extract_block("json", resp)

    if not sql:
        # fallback simple SQL
        numeric = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
        if numeric:
            sql = f"SELECT {', '.join(df.columns[:2])}, {numeric[0]} FROM {table_name} LIMIT 200"
        else:
            sql = f"SELECT * FROM {table_name} LIMIT 200"

    if not narrative:
        narrative = f"Answer for intent: {business_intent}.\nGenerated at {datetime.now(timezone.utc).isoformat()}"

    chart_html = ""
    if charts_json:
        try:
            specs = json.loads(charts_json)
            if px is not None and isinstance(specs, list) and len(specs) > 0:
                spec = specs[0]
                if spec.get("type") == "bar" and spec.get("x") in df.columns and spec.get("y") in df.columns:
                    fig = px.bar(df.head(10), x=spec["x"], y=spec["y"], title=spec.get("title", "Chart"))
                    chart_html = fig.to_html(full_html=False, include_plotlyjs="cdn")
        except Exception:
            chart_html = ""
    else:
        # fallback: simple bar if numeric exists
        if px is not None:
            numeric = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
            if numeric:
                fig = px.bar(df.head(10), x=df.columns[0], y=numeric[0], title="Top 10")
                chart_html = fig.to_html(full_html=False, include_plotlyjs="cdn")

    table_html = df.head(100).to_html(index=False)

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
<pre>{sql}</pre>
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
        json.dump({"run_id": run_id, "intent": business_intent, "sql": sql}, fh)

    logger.log(agent="reporter", action="generated", output=str(out_html))
    return str(out_html)


__all__ = ["generate_report"]
