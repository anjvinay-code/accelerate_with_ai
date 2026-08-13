import argparse
import shutil
import subprocess
from pathlib import Path
from typing import List

from core.config import ensure_dirs, LANDING_DIR
from core.audit import new_run_id, AuditLogger
from core.state import PipelineState

from agents import profiler, sttm_generator, bronze_agent, silver_agent, gold_agent, reporter


def banner(text: str) -> None:
    print("= " + text + " =")


def display_sttm(sttm_path: str, layer: str) -> None:
    import pandas as pd
    df = pd.read_csv(sttm_path)
    print(f"--- {layer} STTM: {sttm_path} ---")
    print(df.to_string(index=False))


def hitl_gate(layer: str, sttm_path: str) -> bool:
    display_sttm(sttm_path, layer)
    while True:
        ans = input("[y]es / [e]dit then re-review / [n]o abort > ").strip().lower()
        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
            print("Aborting pipeline.")
            return False
        if ans == "e":
            editor = shutil.which("code") or shutil.which("notepad") or shutil.which("nano")
            if not editor:
                print("No editor found. Please edit the file manually and press Enter when done.")
                input()
            else:
                subprocess.call([editor, sttm_path])
            display_sttm(sttm_path, layer)


def copy_into_landing(files: List[str]) -> List[str]:
    out = []
    for f in files:
        src = Path(f)
        dst = LANDING_DIR / src.name
        if src.resolve() != dst.resolve():
            shutil.copy(src, dst)
        out.append(str(dst))
    return out


def run_pipeline(files: List[str], intent: str) -> PipelineState:
    ensure_dirs()
    run_id = new_run_id()
    state = PipelineState(run_id=run_id, input_files=files, business_intent=intent)
    logger = AuditLogger(run_id)

    # Phase 1: profile + bronze sttm
    prof_path = profiler.profile(files, run_id)
    state.profile_path = prof_path
    bronze_sttm = sttm_generator.generate_bronze_sttm(prof_path, intent, run_id)
    state.bronze_sttm_path = bronze_sttm
    if not hitl_gate("Bronze", bronze_sttm):
        return state

    # Phase 2: bronze agent + silver sttm
    bronze_paths = bronze_agent.run(files, bronze_sttm, run_id)
    state.bronze_paths = bronze_paths
    silver_sttm = sttm_generator.generate_silver_sttm(bronze_paths, bronze_sttm, intent, run_id)
    state.silver_sttm_path = silver_sttm
    if not hitl_gate("Silver", silver_sttm):
        return state

    # Phase 3: silver agent + gold sttm
    silver_paths = silver_agent.run(bronze_paths, silver_sttm, run_id)
    state.silver_paths = silver_paths
    gold_sttm = sttm_generator.generate_gold_sttm(silver_paths, silver_sttm, intent, run_id)
    state.gold_sttm_path = gold_sttm
    if not hitl_gate("Gold", gold_sttm):
        return state

    # Phase 4: gold agent + report
    gold_paths = gold_agent.run(silver_paths, gold_sttm, intent, run_id)
    state.gold_paths = gold_paths
    report_path = reporter.generate_report(gold_paths, intent, run_id)
    state.report_path = report_path

    logger.log(agent="cli", action="completed", report=report_path)
    print(f"Run complete. report: {report_path}")
    print(f"Audit: audit_logs/{run_id}.jsonl")
    return state


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--files", nargs="+", help="input CSV files")
    parser.add_argument("--intent", type=str, help="business intent/question")
    args = parser.parse_args()

    files = args.files
    intent = args.intent
    if not files:
        files = input("Enter input files (space-separated): ").split()
    if not intent:
        intent = input("Enter business intent: ")

    files = copy_into_landing(files)
    run_pipeline(files, intent)


if __name__ == "__main__":
    main()
