"""Load generated CSV seeds into DuckDB.

Run after data/generate.py and before dbt run. Without this, every
staging model fails with a catalog error.
"""
import os
import sys

try:
    import duckdb
except ImportError:
    sys.exit("pip install -r requirements.txt")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEEDS = os.path.join(ROOT, "data", "seeds")
DB = os.path.join(ROOT, "subscriptions.duckdb")
TABLES = ["subscribers", "transactions", "refunds",
          "subscription_periods", "store_events", "test_accounts"]

def main():
    missing = [t for t in TABLES if not os.path.exists(os.path.join(SEEDS, f"{t}.csv"))]
    if missing:
        sys.exit(f"Missing seeds: {', '.join(missing)}. Run data/generate.py first.")
    con = duckdb.connect(DB)
    for t in TABLES:
        path = os.path.join(SEEDS, f"{t}.csv")
        con.execute(f"create or replace table {t} as select * from read_csv_auto('{path}')")
        n = con.execute(f"select count(*) from {t}").fetchone()[0]
        print(f"  {t:24s} {n:>8,} rows")
    con.close()
    print("\nNext: dbt run --profiles-dir .")

if __name__ == "__main__":
    main()
