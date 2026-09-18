from pathlib import Path
import pandas as pd

DATA_DIR = Path("data/sales")

files = list(DATA_DIR.glob("*"))

print("Total files:", len(files))
print("CSV files:", len(list(DATA_DIR.glob("*.csv"))))
print("Parquet files:", len(list(DATA_DIR.glob("*.parquet"))))

for file in files[:10]:
    print(file)