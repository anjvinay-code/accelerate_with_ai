"""Reporter implementation (simple deterministic reporter).

Generates a self-contained HTML report using Plotly and pandas. This is
not LLM-backed; it produces a basic analysis so trainees can see output.
"""
from typing import List
from pathlib import Path
import pandas as pd
import json

import plotly.express as px

from core.config import REPORTS_DIR


def generate_report(gold_paths: List[str], business_intent: str, run_id: str) -> str:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    if not gold_paths:
        raise ValueError("No gold paths provided")

    # load first gold table
    p = Path(gold_paths[0])
    df = pd.read_parquet(p)

    # pick a numeric column and a category if possible
    num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    cat_cols = [c for c in df.columns if pd.api.types.is_object_dtype(df[c])]

    charts_html = ""
    if num_cols and cat_cols:
        num = num_cols[0]
        cat = cat_cols[0]
        agg = df.groupby(cat)[num].sum().reset_index()
        fig = px.bar(agg, x=cat, y=num, title=f"{num} by {cat}")
        charts_html = fig.to_html(full_html=False, include_plotlyjs='cdn')

    table_html = df.to_html(index=False)

    html = f"""
<html><head><meta charset='utf-8'><title>Report {run_id}</title></head><body>
<h1>Report — {business_intent}</h1>
<h3>Source: {p.name}</h3>
<div>{charts_html}</div>
<h2>Data</h2>
{table_html}
<footer><p>run_id: {run_id}</p></footer>
</body></html>
"""

    out = REPORTS_DIR / f"report_{run_id}.html"
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)

    # machine summary
    summary = {
        "run_id": run_id,
        "report_path": str(out),
        "source_table": p.name,
        "rows": int(len(df)),
    }
    with open(REPORTS_DIR / f"report_{run_id}.json", "w", encoding="utf-8") as fh:
        json.dump(summary, fh)

    return str(out)
