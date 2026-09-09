# Verification Report

Each question was answered twice: once with the query a competent analyst
writes from the raw schema alone, once with the query that follows
[`semantic/DEFINITIONS.md`](../semantic/DEFINITIONS.md).

**This is not a model benchmark.** The naive queries are hand-written to
represent the most plausible misreading of the schema. What the harness
measures is how load-bearing the semantic layer is per question -- how wrong
the reasonable-looking answer turns out to be.

| # | Question | Severity | Naive | Correct | Gap | Status |
|---|---|---|---|---|---|---|
| q03 | What is our realized revenue -- what the business actually keeps? | critical | 950,088 | 758,611 | +25.2% | DIVERGES |
| q05 | What was our realized revenue last month? | critical | 61,860 | 61,860 | +0.0% | UNDER-SPECIFIED |
| q02 | How much revenue did we actually keep in Q1 2026, after refunds? | high | 222,895 | 219,121 | +1.7% | DIVERGES |
| q04 | Apply the standard 30% app store commission to get our net revenue. | high | 690,087 | 794,362 | -13.1% | DIVERGES |
| q06 | What is our trial conversion rate? | high | 0.4306 | 0.4304 | +0.0% | MATCH |
| q07 | How many active subscribers do we have right now? | high | 5,549 | 5,731 | -3.2% | DIVERGES |
| q08 | What is our churn rate, and is it getting worse? | high | 14,338 | 12,928 | -- | SHAPE-MISMATCH |
| q11 | How is Brazil revenue trending? It looks like it's declining. | high | 100,288 | 99,297 | +1.0% | DIVERGES |
| q01 | What was our total revenue in Q1 2026? | medium | 237,895 | 227,903 | +4.4% | DIVERGES |
| q09 | How many unique customers do we have? | medium | 20,000 | 18,524 | +8.0% | DIVERGES |
| q10 | How many trials did we start last quarter? | medium | 15,649 | 15,865 | -1.4% | DIVERGES |
| q12 | Which acquisition channel has the best trial conversion? | medium | 2.59 | 15,865 | -- | SHAPE-MISMATCH |

## Failure modes

### q03 — What is our realized revenue -- what the business actually keeps? (**+25.2%**)

*CRITICAL · Section 4 -- Realized Revenue*

Store commission is omitted entirely. There is a `store_commission_rate` column but nothing indicates it must be applied; "revenue minus refunds" reads as a complete definition of net revenue.

### q05 — What was our realized revenue last month? (**+0.0%**)

*CRITICAL · Section 4 -- the settlement rule*

Answers with a settled-looking number for a period still inside the 70-day refund window. The figure is provisional and will fall. Nothing in the schema warns of this; only the documented settlement window does.

### q02 — How much revenue did we actually keep in Q1 2026, after refunds? (**+1.7%**)

*HIGH · Section 4 -- Realized Revenue*

Refunds are joined on `refunded_at` falling inside the period, rather than being attributed to the transaction they reverse. A refund in March for a January purchase is charged to March. This looks completely correct and silently misstates every month.

### q04 — Apply the standard 30% app store commission to get our net revenue. (**-13.1%**)

*HIGH · Section 4 -- store commission is not flat*

The premise of the question is wrong, and a compliant agent will implement it. Small-business program accounts pay 15% and Stripe is ~2.9%. Three distinct rates exist in the data and the correct answer is to use the column, not the constant the user supplied.

### q06 — What is our trial conversion rate? (**+0.0%**)

*HIGH · Section 2 -- cohort by trial END*

Cohorts on trial START date and includes trials that have not yet ended. Unresolved trials sit in the denominator and can never be in the numerator, depressing the rate.

> **Note.** THIS ONE MATCHES, and the match is itself the finding. The dataset is static and ends 2026-06-30, by which point almost every trial has resolved -- so start-date and end-date cohorting converge. In production, where trials are always in flight, the same naive query understates conversion by roughly the share of the trial window still open (order of 15-30% of a month for a 14-day trial). A harness run against a frozen extract will not catch this class of error. That is a limitation of the harness, not evidence the definition is unnecessary.

### q07 — How many active subscribers do we have right now? (**-3.2%**)

*HIGH · Section 5 -- Active Subscriber*

Counts only status = 'active', silently dropping subscribers in grace period and billing retry who still have product access. Undercounts the product-facing number and hides the payments-recovery opportunity.

### q08 — What is our churn rate, and is it getting worse?

*HIGH · Section 6 -- Churn*

Blends voluntary and involuntary churn into one number. Presents a payments problem and a product problem as a single retention figure with no owner and no actionable fix.

### q11 — How is Brazil revenue trending? It looks like it's declining. (**+1.0%**)

*HIGH · Section 3 -- FX converted at transaction date*

Reports the USD trend without separating FX movement from volume movement. The BRL rate fell ~15% over the period, so a flat-volume market shows as a decline and someone reallocates spend away from a healthy market.

### q01 — What was our total revenue in Q1 2026? (**+4.4%**)

*MEDIUM · Always-filters*

Sandbox transactions and internal test accounts are included. Nothing in the column names signals they should not be -- `environment` looks like infrastructure metadata, not a filter.

### q09 — How many unique customers do we have? (**+8.0%**)

*MEDIUM · Section 7 -- Cross-Platform Identity*

Counts subscriber_id, which is a store-and-device identity, not a person. One human who subscribed on iOS and later on web counts twice. Overstates the customer base and understates revenue per customer.

### q10 — How many trials did we start last quarter? (**-1.4%**)

*MEDIUM · Section 1 -- Trial Start*

Counts distinct subscribers rather than trial-start events, collapsing repeat trialers. A returning subscriber's second trial disappears, and the figure stops reconciling with ad-platform conversion counts.

### q12 — Which acquisition channel has the best trial conversion?

*MEDIUM · Section 2 -- segment or don't quote it*

Joins channel without excluding test accounts, and blends billing periods. Annual and monthly convert at materially different rates, so a channel skewed toward annual products looks better than it is.

## Summary

- **11 of 12** questions produce a wrong or under-specified answer without the semantic layer.
- **2** are critical severity.
- Largest magnitude error: **25.2%**.

The pattern worth noting: none of the naive queries are incompetent.
Every one is a defensible reading of the column names. That is exactly why
the errors survive review — there is nothing in the SQL to object to.
The information needed to write the correct query does not exist in the
schema. It exists only in the documentation.
