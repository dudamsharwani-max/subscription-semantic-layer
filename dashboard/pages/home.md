---
title: Subscription Metrics
description: Tracked vs realized revenue, trials, churn — with the caveats attached
---

# Subscription Metrics

```sql headline
select
  sum(tracked_revenue)                                    as tracked,
  sum(realized_revenue)                                   as realized,
  sum(refunded_revenue)                                   as refunded,
  sum(commission)                                         as commission,
  sum(realized_revenue) / sum(tracked_revenue)            as realized_rate
from revenue_daily
```

{% big_value data="headline" value="tracked" fmt="usd0" title="Tracked Revenue" /%}
{% big_value data="headline" value="realized" fmt="usd0" title="Realized Revenue" /%}
{% big_value data="headline" value="realized_rate" fmt="pct1" title="Realized as % of Tracked" /%}

Tracked revenue is gross transaction value at purchase. Realized revenue is what
the business keeps after refunds and store commission. The gap is
{% value data="headline" value="realized_rate" fmt="pct1" /%} — a difference large enough
that a cash forecast built on tracked revenue is wrong by roughly a quarter.


> **Note on this page.** The charts and figures render blank without a warehouse
> connection. Evidence Core (0.9+) executes SQL against a hosted warehouse and
> does not support the local DuckDB file this project builds. The markup and
> queries are correct; the data path is not available in this version. The same
> numbers are reproducible via `dbt run` and `verification/run_harness.py` — see
> the project README.


## The number that keeps moving

```sql settlement
select
  case when is_settled then 'Settled (>70 days old)' else 'Provisional (last 70 days)' end as status,
  sum(tracked_revenue)                          as tracked,
  sum(realized_revenue)                         as realized,
  sum(realized_revenue)/sum(tracked_revenue)    as realized_rate
from revenue_daily
group by 1
order by 1
```

{% table data="settlement" %}
  {% dimension value="status" title="Period" /%}
  {% dimension value="tracked" fmt="usd0" /%}
  {% dimension value="realized" fmt="usd0" /%}
  {% measure value="realized_rate" title="Realized %" fmt="pct1" viz="color" /%}
{% /table %}

Refunds land a **median of 37 days** after purchase, with a p90 of 65 days. So
realized revenue for any recent period is incomplete and **will fall** as refunds
arrive. The provisional bucket above looks worse than the settled bucket, but that
is not a performance decline — it is data that hasn't finished arriving.

{% callout type="warning" %}

**Never compare a realized-revenue figure from the last 70 days against an older
one.** Use tracked revenue for recent comparisons, or wait for the window to close.

{% /callout %}

```sql revenue_trend
select
  date_trunc('month', revenue_date)  as month,
  sum(tracked_revenue)               as tracked,
  sum(realized_revenue)              as realized
from revenue_daily
group by 1
having count(*) > 20
order by 1
```

{% line_chart
    data="revenue_trend"
    x="month"
    y=["tracked", "realized"]
    y_fmt="usd0"
    title="Tracked vs Realized Revenue by Month"
    subtitle="The gap is refunds plus store commission. Recent months will still move."
    handle_missing="gaps"
/%}

## Trials

```sql trial_summary
select
  count(*)                                                  as trial_starts,
  count(*) filter (where is_qualified)                      as qualified_starts,
  count(*) filter (where not is_qualified)                  as sub_hour_cancels,
  avg(case when trial_ended_at is not null then converted::int end) as conversion_rate
from trials
```

{% big_value data="trial_summary" value="trial_starts" fmt="num0" title="Trial Starts" /%}
{% big_value data="trial_summary" value="sub_hour_cancels" fmt="num0" title="Cancelled <1hr" /%}
{% big_value data="trial_summary" value="conversion_rate" fmt="pct1" title="Conversion Rate" /%}

Sub-hour cancellations are **counted** as trial starts, because the acquisition
spend that produced them was real and excluding them breaks reconciliation against
ad-platform numbers. The `qualified_starts` measure exists for when you want the
cleaner figure — so that nobody redefines `trial_starts` privately in their own query.

```sql conversion_by_plan
select
  case when product_id like '%annual%' then 'Annual' else 'Monthly' end as plan,
  count(*)                        as trials,
  avg(converted::int)             as conversion_rate
from trials
where trial_ended_at is not null
group by 1
order by 1
```

{% bar_chart
    data="conversion_by_plan"
    x="plan"
    y="conversion_rate"
    y_fmt="pct1"
    title="Trial Conversion by Billing Period"
    subtitle="Cohorted on trial END date — a trial cannot convert until it ends"
/%}

Blended conversion moves whenever the product mix moves. Segment it or don't quote it.

## Churn is two problems

```sql churn_split
select
  case churn_type when 'voluntary' then 'Voluntary (chose to cancel)'
                  else 'Involuntary (payment failed)' end as type,
  count(*)                                                as subscribers,
  count(*) * 1.0 / sum(count(*)) over ()                  as share
from churn
group by 1
order by 2 desc
```

{% table data="churn_split" %}
  {% dimension value="type" title="Churn Type" /%}
  {% dimension value="subscribers" fmt="num0" /%}
  {% dimension value="share" fmt="pct1" /%}
{% /table %}

Blended, this reads as a single retention problem. Split, it is one product problem
and one payments problem — different owners, different fixes. Involuntary churn is
also partly recoverable: roughly 40% of billing retries recover, so subscribers
still in retry have not churned yet.

## Active subscribers: whose definition?

```sql active_now
select
  as_of_date,
  entitled_subscribers,
  paying_subscribers,
  in_grace_period,
  in_billing_retry,
  entitled_humans
from active_subscribers
where as_of_date = (select max(as_of_date) - 30 from active_subscribers)
```

{% table data="active_now" /%}

`entitled_subscribers` counts anyone with product access, including grace period
and billing retry. `paying_subscribers` counts only those actually paying. Both are
published deliberately: Product and Finance mean different things by "active", and
when only one number exists the other team quietly builds their own.

`entitled_humans` deduplicates on `app_user_id` rather than `subscriber_id`, because
one person subscribing on iOS and later on web is two subscriber rows.

---

Every metric on this page is defined in
[`semantic/DEFINITIONS.md`](https://github.com/dudamsharwani-max/subscription-semantic-layer/blob/main/semantic/DEFINITIONS.md), including what
each number **does not** say. Data is synthetic.
