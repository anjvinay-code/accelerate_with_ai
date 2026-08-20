#!/usr/bin/env python
import argparse
from pathlib import Path
from core.config import ensure_dirs, LANDING_DIR
from core.audit import new_run_id
from agents import profiler, sttm_generator, bronze_agent, silver_agent, gold_agent, reporter

import glob


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--files', nargs='*', help='input CSV files')
    parser.add_argument('--intent', type=str, default='Explore key metrics', help='business intent')
    parser.add_argument('--run_id', type=str, default=None, help='run id')
    args = parser.parse_args()

    files = args.files
    if not files:
        # find CSVs in landing
        files = [str(p) for p in sorted(Path('data/landing').glob('*.csv'))]
    if not files:
        print('No input CSVs found in data/landing and no --files provided')
        return

    ensure_dirs()
    run_id = args.run_id or new_run_id()
    intent = args.intent

    print('Profiling...')
    prof = profiler.profile(files, run_id)
    print('Bronze STTM...')
    bronze_sttm = sttm_generator.generate_bronze_sttm(prof, intent, run_id)
    print('Bronze agent...')
    bronze_paths = bronze_agent.run(files, bronze_sttm, run_id)
    print('Silver STTM...')
    silver_sttm = sttm_generator.generate_silver_sttm(bronze_paths, bronze_sttm, intent, run_id)
    print('Silver agent...')
    silver_paths = silver_agent.run(bronze_paths, silver_sttm, run_id)
    print('Gold STTM...')
    gold_sttm = sttm_generator.generate_gold_sttm(silver_paths, silver_sttm, intent, run_id)
    print('Gold agent...')
    gold_paths = gold_agent.run(silver_paths, gold_sttm, intent, run_id)
    print('Reporting...')
    report = reporter.generate_report(gold_paths, intent, run_id)
    print('Report written to:', report)


if __name__ == '__main__':
    main()
