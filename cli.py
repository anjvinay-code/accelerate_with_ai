"""Minimal CLI orchestrator scaffold for IDAMP."""
import argparse
import sys
from pathlib import Path

from core.config import ensure_dirs
from core.audit import new_run_id, AuditLogger
from core.state import PipelineState
from agents import profiler, sttm_generator, bronze_agent, silver_agent, gold_agent, reporter
import pandas as pd
import time


def banner(text: str) -> None:
    print("= " + text + " =")


def run_pipeline(files, intent) -> PipelineState:
    ensure_dirs()
    run_id = new_run_id()
    state = PipelineState(run_id=run_id, input_files=files, business_intent=intent)
    banner(f"Run ID: {run_id}")
    logger = AuditLogger(run_id)

    # Phase 1: profile + bronze STTM
    print("Phase 1: profiling...")
    profile_path = profiler.profile(files, run_id)
    state.profile_path = profile_path
    logger.log("cli", "profile_completed", profile_path=profile_path)

    print("Generating Bronze STTM...")
    bronze_sttm = sttm_generator.generate_bronze_sttm(profile_path, intent, run_id)
    state.bronze_sttm_path = bronze_sttm
    logger.log("cli", "sttm_bronze_generated", path=bronze_sttm)

    # HITL gate simplified: auto-approve after showing a snippet
    print("Bronze STTM preview:")
    try:
        print(pd.read_csv(bronze_sttm).head().to_string())
    except Exception:
        pass
    time.sleep(0.5)

    # Phase 2: bronze execution + silver sttm
    print("Running Bronze agent...")
    bronze_paths = bronze_agent.run(files, bronze_sttm, run_id)
    state.bronze_paths = bronze_paths
    logger.log("cli", "bronze_completed", bronze_paths=bronze_paths)

    print("Generating Silver STTM...")
    silver_sttm = sttm_generator.generate_silver_sttm(bronze_paths, bronze_sttm, intent, run_id)
    state.silver_sttm_path = silver_sttm
    logger.log("cli", "sttm_silver_generated", path=silver_sttm)

    print("Silver STTM preview:")
    try:
        print(pd.read_csv(silver_sttm).head().to_string())
    except Exception:
        pass
    time.sleep(0.5)

    # Phase 3: silver execution + gold sttm
    print("Running Silver agent...")
    silver_paths = silver_agent.run(bronze_paths, silver_sttm, run_id)
    state.silver_paths = silver_paths
    logger.log("cli", "silver_completed", silver_paths=silver_paths)

    print("Generating Gold STTM...")
    gold_sttm = sttm_generator.generate_gold_sttm(silver_paths, silver_sttm, intent, run_id)
    state.gold_sttm_path = gold_sttm
    logger.log("cli", "sttm_gold_generated", path=gold_sttm)

    print("Gold STTM preview:")
    try:
        print(pd.read_csv(gold_sttm).head().to_string())
    except Exception:
        pass
    time.sleep(0.5)

    print("Running Gold agent...")
    gold_paths = gold_agent.run(silver_paths, gold_sttm, intent, run_id)
    state.gold_paths = gold_paths
    logger.log("cli", "gold_completed", gold_paths=gold_paths)

    # Phase 4: reporter
    print("Generating report...")
    report_path = reporter.generate_report(gold_paths, intent, run_id)
    state.report_path = report_path
    logger.log("cli", "report_generated", report_path=report_path)

    print(f"Run complete. Report: {report_path}")
    print(f"Audit log: audit_logs/{run_id}.jsonl")
    return state


def main(argv=None):
    p = argparse.ArgumentParser(description="IDAMP CLI")
    p.add_argument("--files", nargs="+", help="Input CSV files")
    p.add_argument("--intent", type=str, help="Business intent / question")
    args = p.parse_args(argv)
    files = args.files or []
    intent = args.intent or ""
    if not files:
        print("No input files specified. Use --files file1.csv file2.csv")
        sys.exit(1)
    if not intent:
        intent = input("Business intent: ")
    run_pipeline(files, intent)


if __name__ == "__main__":
    main()
