# IDAMP — Intent-Driven Agentic Medallion Pipeline

Quickstart to run the local medallion pipeline (raw CSV → Bronze → Silver → Gold → Report).

Prerequisites
- Python 3.10+
- Create a `.env` in the project root with your LLM token (example below).

Install
```bash
python -m pip install -r requirements.txt
```

Create `.env` (example)
```
LLM_PROVIDER=github
GITHUB_TOKEN=ghp_your_token_here
GITHUB_MODEL=gpt-4.1-mini
```

Run the pipeline (example)
```bash
python cli.py --files "data/landing/sales_data 2.csv" "data/landing/products 3.csv" "data/landing/stores 3.csv" --intent "Which product category generated the highest total sales revenue?"
```

Inspect generated report
- HTML reports are written to `reports/` (open in browser or serve with `python -m http.server`).

Utilities
- `tools/inspect_parquet.py` prints Bronze/Silver/Gold schemas and samples.

CI
- A GitHub Actions workflow is added at `.github/workflows/pipeline.yml` (workflow dispatch).

Security
- Do not commit `.env` or any tokens. Use GitHub Secrets for CI.
