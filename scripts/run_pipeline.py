import sys
sys.path.insert(0, r"c:\Users\anjvinay\idamp")
from cli import run_pipeline

files = [
    r"c:\Users\anjvinay\idamp\data\landing\sales_data.csv",
    r"c:\Users\anjvinay\idamp\data\landing\products.csv",
    r"c:\Users\anjvinay\idamp\data\landing\stores.csv",
]
intent = "Which product category generated the highest total sales revenue?"

if __name__ == '__main__':
    run_pipeline(files, intent)
