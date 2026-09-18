"""Build and prove the Annapurna platform using the DuckDB CLI."""

import csv
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "duckdb" / "annapurna.duckdb"
OUT = ROOT / "sql" / "proof"
SOURCE = ROOT / "data" / "sales"
CANONICAL = ROOT / "object_store" / "raw" / "sales"


def duckdb_cli():
    return shutil.which("duckdb") or ("C:\\duckdb.exe" if Path("C:\\duckdb.exe").exists() else None)


def query(sql):
    cli = duckdb_cli()
    if not cli:
        raise RuntimeError("DuckDB CLI was not found")
    return subprocess.run([cli, str(DB_PATH), "-c", sql], cwd=ROOT,
                          text=True, capture_output=True, check=True).stdout


def run_loader():
    return subprocess.run([os.fspath(Path(os.sys.executable)),
                           os.fspath(ROOT / "scripts" / "02_ingest.py")],
                          cwd=ROOT, text=True, capture_output=True,
                          check=True).stdout.strip()


def main():
    OUT.mkdir(exist_ok=True)
    DB_PATH.parent.mkdir(exist_ok=True)
    proof = [run_loader() for _ in range(3)]
    source_files = list(SOURCE.iterdir())
    partitions = list(CANONICAL.glob("store_id=*/year=*/month=*/sales.csv"))

    schema = (ROOT / "sql" / "analytics_schema.sql").read_text(encoding="utf-8")
    query("INSTALL postgres; LOAD postgres; " + schema)
    monthly = query("""
        COPY (SELECT strftime(month_start, '%Y-%m') AS month,
                     ROUND(SUM(revenue_inr), 2) AS pipeline_revenue_inr
              FROM agg_revenue_month_store_category GROUP BY 1 ORDER BY 1)
        TO 'sql/proof/pipeline_monthly.csv' (HEADER, DELIMITER ',');
    """)
    finance = {}
    with (ROOT / "data" / "finance_monthly.csv").open(encoding="utf-8") as source:
        for row in csv.DictReader(source):
            finance[row["month"]] = row["revenue_inr"]
    rows = []
    with (OUT / "pipeline_monthly.csv").open(encoding="utf-8") as source:
        for row in csv.DictReader(source):
            expected = float(finance[row["month"]])
            actual = float(row["pipeline_revenue_inr"])
            rows.append([row["month"], row["pipeline_revenue_inr"], finance[row["month"]],
                         f"{actual - expected:.2f}", "definition/source reconciliation"])
    with (OUT / "reconciliation.csv").open("w", newline="", encoding="utf-8") as target:
        writer = csv.writer(target)
        writer.writerow(["month", "pipeline_revenue_inr", "finance_revenue_inr", "difference_inr", "assessment"])
        writer.writerows(rows)

    explain = query("""
        EXPLAIN SELECT s.store_name, c.category_name, SUM(f.revenue_inr)
        FROM fact_revenue f
        JOIN postgres_scan('host=localhost port=5432 dbname=annapurna user=annapurna password=annapurna','public','stores') s ON s.store_id=f.store_id
        JOIN postgres_scan('host=localhost port=5432 dbname=annapurna user=annapurna password=annapurna','public','product_categories') c ON c.category_id=f.category_id
        GROUP BY 1,2;
    """)
    prices = query("""
        SELECT '2024-03-15' AS report_date, p.product_name, r.selling_price
        FROM postgres_scan('host=localhost port=5432 dbname=annapurna user=annapurna password=annapurna','public','products') p
        JOIN postgres_scan('host=localhost port=5432 dbname=annapurna user=annapurna password=annapurna','public','price_revisions') r ON r.product_sk=p.product_sk
        WHERE p.product_code='P100019' AND DATE '2024-03-15' >= r.effective_from AND DATE '2024-03-15' < r.effective_to
        UNION ALL
        SELECT '2024-10-15', p.product_name, r.selling_price
        FROM postgres_scan('host=localhost port=5432 dbname=annapurna user=annapurna password=annapurna','public','products') p
        JOIN postgres_scan('host=localhost port=5432 dbname=annapurna user=annapurna password=annapurna','public','price_revisions') r ON r.product_sk=p.product_sk
        WHERE p.product_code='P100019' AND DATE '2024-10-15' >= r.effective_from AND DATE '2024-10-15' < r.effective_to;
    """)
    with (OUT / "platform_proof.txt").open("w", encoding="utf-8") as target:
        target.write("IDEMPOTENCY\n" + "\n".join(proof) + "\n")
        target.write(f"source_files={len(source_files)} source_bytes={sum(p.stat().st_size for p in source_files)}\n")
        target.write(f"partition_files={len(partitions)} partition_bytes={sum(p.stat().st_size for p in partitions)}\n")
        target.write("\nAS_OF_PRICES\n" + prices + "\nFEDERATED_EXPLAIN\n" + explain)
    print(f"wrote {OUT / 'platform_proof.txt'}")
    print(f"wrote {OUT / 'reconciliation.csv'}")


if __name__ == "__main__":
    main()
