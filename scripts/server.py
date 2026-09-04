from flask import Flask, request, jsonify, send_from_directory, render_template_string
from pathlib import Path
import threading
import time
import os

app = Flask(__name__)
ROOT = Path(__file__).resolve().parents[1]
LANDING = ROOT / 'data' / 'landing'
REPORTS = ROOT / 'reports'

# Simple in-memory run tracker
RUNS = {}

INDEX_HTML = '''
<!doctype html>
<title>IDAMP Local Server</title>
<h1>IDAMP Local Medallion Runner</h1>
<form action="/run" method="post">
    <label>Business intent (question):</label><br>
    <input type="text" name="intent" size="80" value="Which product category generated the highest total sales revenue?"><br><br>
    <label>Input files (comma-separated, or leave blank for all landing CSVs):</label><br>
    <input type="text" name="files" size="80" placeholder="data/landing/sales_data.csv,data/landing/products.csv"><br><br>
    <label>Phases:</label><br>
    <input type="checkbox" name="phases" value="silver" checked> Silver
    <input type="checkbox" name="phases" value="gold" checked> Gold
    <input type="checkbox" name="phases" value="report" checked> Report<br><br>
    <button type="submit">Run Pipeline</button>
</form>
<h2>Landing files</h2>
<ul>
{% for f in files %}
    <li>{{f}}</li>
{% endfor %}
</ul>
<h2>Recent runs</h2>
<ul>
{% for rid, info in runs.items() %}
    <li>
        <a href="/reports/{{rid}}">Report {{rid}}</a> — Status: {{info.status}}
        {% if info.status == 'running' %} (started at {{info.start}}) {% endif %}
        {% if info.status == 'error' %} — Error: {{info.error}} {% endif %}
    </li>
{% endfor %}
</ul>
'''

@app.route('/')
def index():
    files = sorted([str(p) for p in LANDING.glob('*.csv')])
    return render_template_string(INDEX_HTML, files=files, runs=RUNS)


def _run_pipeline(files, intent):
    # import locally to avoid startup overhead
    from cli import run_pipeline
    try:
        state = run_pipeline(files, intent)
        rid = state.run_id
        REPORTS.mkdir(parents=True, exist_ok=True)
        REPORTS_FILE = state.report_path
        RUNS[rid] = {"status": "done", "report": REPORTS_FILE, "start": time.strftime('%Y-%m-%d %H:%M:%S')}
    except Exception as e:
        rid = f"err_{int(time.time())}"
        RUNS[rid] = {"status": "error", "error": str(e), "report": None, "start": time.strftime('%Y-%m-%d %H:%M:%S')}


@app.route('/run', methods=['POST'])
def run():
    intent = request.form.get('intent') or (request.json.get('intent') if request.json else None)
    files_raw = request.form.get('files') or (request.json.get('files') if request.json else None)
    phases = request.form.getlist('phases') or (request.json.get('phases') if request.json else None)
    if files_raw:
        files = [f.strip() for f in files_raw.split(',') if f.strip()]
    else:
        files = sorted([str(p) for p in LANDING.glob('*.csv')])
    # create a tentative run id for status tracking
    rid = f"run_{int(time.time())}"
    RUNS[rid] = {"status": "running", "report": None, "start": time.strftime('%Y-%m-%d %H:%M:%S'), "intent": intent, "files": files, "phases": phases}
    # run in background thread to keep server responsive
    t = threading.Thread(target=_run_pipeline, args=(files, intent or ""), daemon=True)
    t.start()
    return jsonify({'status': 'started', 'files': files, 'intent': intent, 'run_id': rid}), 202


@app.route('/status/<run_id>')
def status(run_id):
    info = RUNS.get(run_id)
    if not info:
        return jsonify({'error': 'unknown run id'}), 404
    return jsonify(info)


@app.route('/reports/<run_id>')
def get_report(run_id):
    filename = f'report_{run_id}.html'
    path = REPORTS / filename
    if not path.exists():
        return f'Report {run_id} not ready', 404
    return send_from_directory(str(REPORTS), filename)


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8787, debug=True)
