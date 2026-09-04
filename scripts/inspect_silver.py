from pathlib import Path
import pandas as pd
p = Path('data/silver_layer')
sales = sorted(p.glob('sales_data_silver_*.parquet'))
prods = sorted(p.glob('products_silver_*.parquet'))
if prods:
    pf = prods[-1]
    print('PRODUCTS:', pf)
    df = pd.read_parquet(pf)
    print(df.dtypes)
    print(df.head())
if sales:
    sf = sales[-1]
    print('\nSALES:', sf)
    df2 = pd.read_parquet(sf)
    print(df2.dtypes)
    print(df2.head())
else:
    print('No sales/product parquet files found')
