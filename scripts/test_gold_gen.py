import sys
sys.path.insert(0, r"c:\Users\anjvinay\idamp")
from pathlib import Path
from agents import sttm_generator

silver_dir = Path('data/silver_layer')
paths = [str(p) for p in silver_dir.glob('*.parquet')]
print('silver_paths:', paths)
import pandas as pd
for p in paths:
	try:
		df = pd.read_parquet(p)
		print(p, 'columns->', df.dtypes.to_dict())
	except Exception as e:
		print('failed to read', p, e)

out = sttm_generator.generate_gold_sttm(paths, None, 'intent', 'test_run')
print('gold sttm written to:', out)
print('contents:')
print(open(out,'r',encoding='utf-8').read())
