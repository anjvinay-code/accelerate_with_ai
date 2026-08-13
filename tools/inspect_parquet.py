from pathlib import Path
import pandas as pd

base = Path(__file__).resolve().parents[1]
layers = [
    ("bronze", "data/bronze_layer"),
    ("silver", "data/silver_layer"),
    ("gold", "data/gold_layer"),
]

for name, rel in layers:
    p = base / rel
    print('\n---', name.upper(), 'LAYER ---')
    if not p.exists():
        print('  (no files)')
        continue
    files = sorted(list(p.glob('*.parquet')))
    if not files:
        print('  (no parquet files)')
        continue
    for f in files:
        print(f'File: {f.name}')
        try:
            df = pd.read_parquet(f)
            print(f'  shape: {df.shape}')
            print('  dtypes:')
            for col, dt in df.dtypes.astype(str).items():
                print(f'    - {col}: {dt}')
            print('  sample rows:')
            print(df.head(5).to_string(index=False))
        except Exception as e:
            print('  error reading:', e)
