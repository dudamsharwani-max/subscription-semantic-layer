"""
Verification harness.

Runs each question in questions.yml twice -- once with the query an unguided
analyst or agent writes from the raw schema, once with the query that follows
semantic/DEFINITIONS.md -- and reports the gap.

WHAT THIS MEASURES, PRECISELY
-----------------------------
This is not a benchmark of any particular language model. The `naive` queries
are hand-written to represent the most plausible wrong reading of the schema.
Calling them "what an LLM produces" without having run one would be a claim
this harness does not support.

What it does measure is the thing that actually matters: for each question,
HOW WRONG is the plausible answer, and therefore how much the semantic layer is
load-bearing. A question with a 0% gap needs no semantic context. A question
with a 23% gap will produce a confident, wrong, unchallengeable number every
time someone queries the raw schema.

To measure a specific model instead, implement `llm_generate_sql()` below and
run with --llm. The scoring is identical; only the source of the naive query
changes.

Usage:
    python3 verification/run_harness.py
    python3 verification/run_harness.py --format md > verification/REPORT.md
"""

import argparse
import os
import sys

try:
    import duckdb
    import yaml
except ImportError:
    sys.exit("pip install duckdb pyyaml")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "subscriptions.duckdb")
QUESTIONS = os.path.join(ROOT, "verification", "questions.yml")

SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def llm_generate_sql(question, schema_description):
    """Hook for measuring a real model rather than the hand-written naive query.

    Implement to call whatever model you want, passing ONLY the raw schema --
    no semantic context. Return a SQL string. Then run with --llm.
    """
    raise NotImplementedError(
        "Not implemented. Without this, the harness uses the hand-written "
        "naive queries in questions.yml and reports on those. It does not "
        "claim to measure any specific model."
    )


def run_sql(con, sql):
    try:
        df = con.execute(sql).fetchdf()
        return df, None
    except Exception as e:
        return None, str(e)


def primary_scalar(df):
    """Single comparable number from a result set, with its column name.

    Returns (value, column_name). The column name matters: comparing a naive
    query's `conv` against a grounded query's `trials` produces a meaningless
    percentage. Callers must check the names match before computing a gap.
    """
    if df is None or df.empty:
        return None, None
    for col in df.columns:
        if df[col].dtype.kind in "ifu":
            try:
                v = float(df[col].iloc[0]) if len(df) == 1 else float(df[col].sum())
                return v, col
            except Exception:
                continue
    return None, None


def evaluate(con, q):
    naive_df, naive_err = run_sql(con, q["naive"])
    grounded_df, grounded_err = run_sql(con, q["grounded"])

    n, n_col = primary_scalar(naive_df)
    g, g_col = primary_scalar(grounded_df)

    comparable = (n_col is not None and n_col == g_col
                  and naive_df is not None and grounded_df is not None
                  and len(naive_df) == len(grounded_df))

    if naive_err or grounded_err:
        status, gap_pct = "ERROR", None
    elif n is None or g is None:
        status, gap_pct = "NO-RESULT", None
    elif not comparable:
        # The two queries return different shapes. That IS the failure -- the
        # naive query answers a different question -- but a percentage gap
        # between incomparable columns would be a fabricated number.
        status, gap_pct = "SHAPE-MISMATCH", None
    elif g == 0:
        status = "MATCH" if n == 0 else "DIVERGES"
        gap_pct = None
    else:
        gap_pct = (n - g) / abs(g) * 100
        status = "MATCH" if abs(gap_pct) < 0.5 else "DIVERGES"

    # A question can be answered with the right number and still be
    # under-specified: one blended figure where the decision needs a breakdown.
    if status == "MATCH" and naive_df is not None and grounded_df is not None:
        if len(grounded_df.columns) > len(naive_df.columns) + 1:
            status = "UNDER-SPECIFIED"

    return {
        "id": q["id"], "question": q["question"], "severity": q["severity"],
        "definition_ref": q["definition_ref"], "failure_mode": q["failure_mode"].strip(),
        "naive_value": n, "grounded_value": g, "gap_pct": gap_pct,
        "status": status, "error": naive_err or grounded_err,
        "note": q.get("note", "").strip(),
        "naive_cols": list(naive_df.columns) if naive_df is not None else [],
        "grounded_cols": list(grounded_df.columns) if grounded_df is not None else [],
    }


def fmt_val(v):
    if v is None:
        return "--"
    if abs(v) >= 1000:
        return f"{v:,.0f}"
    if abs(v) >= 1:
        return f"{v:,.2f}"
    return f"{v:.4f}"


def report_text(results):
    out = []
    out.append("=" * 100)
    out.append("VERIFICATION HARNESS -- naive schema reading vs documented semantic layer")
    out.append("=" * 100)
    for r in sorted(results, key=lambda x: SEVERITY_RANK[x["severity"]]):
        out.append("")
        out.append(f"[{r['id']}] {r['severity'].upper():<8} {r['status']}")
        out.append(f"  Q: {r['question']}")
        if r["error"]:
            out.append(f"  ERROR: {r['error'][:150]}")
            continue
        out.append(f"  naive    = {fmt_val(r['naive_value'])}")
        out.append(f"  grounded = {fmt_val(r['grounded_value'])}")
        if r["gap_pct"] is not None and r["status"] != "MATCH":
            out.append(f"  GAP      = {r['gap_pct']:+.1f}%")
        if r["status"] == "UNDER-SPECIFIED":
            out.append(f"  naive returns {len(r['naive_cols'])} column(s); "
                       f"correct answer needs {len(r['grounded_cols'])}")
        out.append(f"  why: {' '.join(r['failure_mode'].split())}")
        out.append(f"  ref: {r['definition_ref']}")
        if r["note"]:
            out.append(f"  NOTE: {' '.join(r['note'].split())}")

    diverged = [r for r in results if r["status"] in ("DIVERGES", "UNDER-SPECIFIED", "SHAPE-MISMATCH")]
    crit = [r for r in diverged if r["severity"] == "critical"]
    out.append("")
    out.append("=" * 100)
    out.append(f"{len(diverged)} of {len(results)} questions produce a wrong or "
               f"under-specified answer without the semantic layer "
               f"({len(crit)} critical).")
    gaps = [abs(r["gap_pct"]) for r in diverged if r["gap_pct"] is not None]
    if gaps:
        out.append(f"Largest magnitude error: {max(gaps):.1f}%. Median: "
                   f"{sorted(gaps)[len(gaps)//2]:.1f}%.")
    out.append("=" * 100)
    return "\n".join(out)


def report_md(results):
    out = ["# Verification Report", "",
           "Each question was answered twice: once with the query a competent analyst",
           "writes from the raw schema alone, once with the query that follows",
           "[`semantic/DEFINITIONS.md`](../semantic/DEFINITIONS.md).", "",
           "**This is not a model benchmark.** The naive queries are hand-written to",
           "represent the most plausible misreading of the schema. What the harness",
           "measures is how load-bearing the semantic layer is per question -- how wrong",
           "the reasonable-looking answer turns out to be.", "",
           "| # | Question | Severity | Naive | Correct | Gap | Status |",
           "|---|---|---|---|---|---|---|"]
    for r in sorted(results, key=lambda x: SEVERITY_RANK[x["severity"]]):
        gap = f"{r['gap_pct']:+.1f}%" if r["gap_pct"] is not None else "--"
        out.append(f"| {r['id']} | {r['question']} | {r['severity']} | "
                   f"{fmt_val(r['naive_value'])} | {fmt_val(r['grounded_value'])} | "
                   f"{gap} | {r['status']} |")

    out += ["", "## Failure modes", ""]
    for r in sorted(results, key=lambda x: SEVERITY_RANK[x["severity"]]):
        if r["status"] == "MATCH" and not r["note"]:
            continue
        gap = f" (**{r['gap_pct']:+.1f}%**)" if r["gap_pct"] is not None else ""
        out += [f"### {r['id']} — {r['question']}{gap}", "",
                f"*{r['severity'].upper()} · {r['definition_ref']}*", "",
                " ".join(r["failure_mode"].split()), ""]
        if r["note"]:
            out += [f"> **Note.** {' '.join(r['note'].split())}", ""]

    diverged = [r for r in results if r["status"] in ("DIVERGES", "UNDER-SPECIFIED", "SHAPE-MISMATCH")]
    crit = [r for r in diverged if r["severity"] == "critical"]
    gaps = [abs(r["gap_pct"]) for r in diverged if r["gap_pct"] is not None]
    out += ["## Summary", "",
            f"- **{len(diverged)} of {len(results)}** questions produce a wrong or "
            f"under-specified answer without the semantic layer.",
            f"- **{len(crit)}** are critical severity.",
            f"- Largest magnitude error: **{max(gaps):.1f}%**." if gaps else "",
            "", "The pattern worth noting: none of the naive queries are incompetent.",
            "Every one is a defensible reading of the column names. That is exactly why",
            "the errors survive review — there is nothing in the SQL to object to.",
            "The information needed to write the correct query does not exist in the",
            "schema. It exists only in the documentation."]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--format", choices=["text", "md"], default="text")
    ap.add_argument("--llm", action="store_true",
                    help="Generate naive queries from a live model instead "
                         "(requires implementing llm_generate_sql)")
    args = ap.parse_args()

    if args.llm:
        llm_generate_sql("", "")  # raises with an explanation

    if not os.path.exists(DB):
        sys.exit(f"No database at {DB}. Run data/generate.py and dbt run first.")

    with open(QUESTIONS) as f:
        spec = yaml.safe_load(f)

    con = duckdb.connect(DB, read_only=True)
    results = [evaluate(con, q) for q in spec["questions"]]
    con.close()

    print(report_md(results) if args.format == "md" else report_text(results))


if __name__ == "__main__":
    main()
