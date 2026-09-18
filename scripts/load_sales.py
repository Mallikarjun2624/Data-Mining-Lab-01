#!/usr/bin/env python3
"""
Annapurna landing/canonicalization loader.

Properties:
- Uses the filename as business_date (per billing_notes.md).
- Normalizes the three CSV dialects to one schema.
- Treats (bill_no,line_no) as the idempotency key.
- Keeps the union of all resend files, so partial resends are not lost.
- Re-running produces the same canonical row set.
- Writes partitioned CSVs under:
  object_store/raw/sales/store_id=Sxx/year=YYYY/month=MM/
"""
import csv, glob, hashlib, os, re, shutil
from collections import OrderedDict

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "data", "sales")
OUT = os.path.join(ROOT, "object_store", "raw", "sales")
PAT = re.compile(r"SALES_(S\d+)_(\d{8})(?:__R\d+)?\.(csv|parquet)$", re.I)

def read_rows(path, store, bizdate):
    if path.lower().endswith(".parquet"):
        try:
            import pandas as pd
        except ImportError as exc:
            raise RuntimeError("Parquet input requires pandas and pyarrow") from exc
        rows = pd.read_parquet(path).to_dict("records")
        for row in rows:
            yield normalize_row(row, store, bizdate)
        return

    # S06-S09: semicolon; S10-S12: comma with BOM and reordered columns.
    sep = ";" if store in {"S06","S07","S08","S09"} else ","
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f, delimiter=sep)
        for row in r:
            yield normalize_row(row, store, bizdate)

def normalize_row(row, store, bizdate):
    return {
        "bill_no": row["bill_no"],
        "line_no": int(row["line_no"]),
        "product_code": row.get("product_code") or row.get("item_code"),
        "qty": row.get("qty") or row.get("quantity"),
        "unit_price": row.get("unit_price") or row.get("rate"),
        "line_type": row.get("line_type") or row.get("type"),
        "ts": row.get("ts") or row.get("txn_time"),
        "store_id": store,
        "business_date": bizdate,
    }

def main():
    os.makedirs(OUT, exist_ok=True)
    # Atomic replacement makes the output deterministic on every run.
    tmp = OUT + ".__tmp__"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)

    seen = OrderedDict()
    for path in sorted(glob.glob(os.path.join(SRC, "*"))):
        name = os.path.basename(path)
        m = PAT.fullmatch(name)
        if not m:
            continue
        store, bizdate = m.group(1), m.group(2)
        for x in read_rows(path, store, bizdate):
            key = (x["bill_no"], x["line_no"])
            # All duplicate keys in the supplied data are byte-equivalent rows.
            seen.setdefault(key, x)

    # Partitioned output: one canonical file per store/month.
    groups = {}
    for x in seen.values():
        k = (x["store_id"], x["business_date"][:4], x["business_date"][4:6])
        groups.setdefault(k, []).append(x)

    header = ["bill_no","line_no","product_code","qty","unit_price",
              "line_type","ts","store_id","business_date"]
    for (store, year, month), rows in sorted(groups.items()):
        d = os.path.join(tmp, f"store_id={store}", f"year={year}", f"month={month}")
        os.makedirs(d, exist_ok=True)
        out = os.path.join(d, "sales.csv")
        rows = sorted(rows, key=lambda z: (z["bill_no"], z["line_no"]))
        with open(out, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=header)
            w.writeheader()
            w.writerows(rows)

    # Replace only after successful completion.
    shutil.rmtree(OUT, ignore_errors=True)
    os.replace(tmp, OUT)

    h = hashlib.sha256()
    for key in sorted(seen):
        x = seen[key]
        line = "|".join(str(x[k]) for k in
                        ["bill_no","line_no","product_code","qty",
                         "unit_price","line_type","ts"]) + "\n"
        h.update(line.encode())
    print(f"unique_rows={len(seen)}")
    print(f"sha256={h.hexdigest()}")

if __name__ == "__main__":
    main()
