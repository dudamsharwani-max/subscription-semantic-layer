# Subscription Metric Definitions

The reference for what each subscription metric means, how it is computed, and
what it does not say.

Every metric below has four parts, and the fourth is the one that matters most:

| Part | Why it exists |
|---|---|
| **Definition** | The business meaning, in one sentence a non-analyst can act on |
| **Implementation** | The SQL that produces it, so there is one answer and not five |
| **Gotchas** | The decisions baked into the definition that a reader would not guess |
| **What it does not say** | The wrong conclusion someone will reach from this number |

Metrics without the fourth section get misused. That is the entire reason this
document exists rather than a list of column names.

---

## Always-filters

These apply to **every** metric in this document unless explicitly noted. They
are not optional, and omitting them is the single most common way a subscription
number comes out wrong.

```sql
where environment = 'production'                        -- exclude sandbox / StoreKit test
  and subscriber_id not in (select subscriber_id from test_accounts)
```

**In this dataset:** sandbox is 2.99% of transactions and internal accounts are
1.55% of subscribers. Together they inflate raw transaction counts by roughly
4-5%. That is small enough to look plausible and large enough to change a
decision — which is exactly what makes it dangerous.

**A note on `test_accounts`.** This table has to be maintained by a human. It
will go stale. Any metric that depends on it inherits that staleness, and a
sudden unexplained jump in subscriber counts should send you here first.

---

## 1. Trial Start

**Definition.** A subscriber entering a free trial period for the first time on
a given product family.

**Implementation.** `semantic/metrics.yml → trial_starts`

```sql
select count(*)
from store_events
where event_type = 'trial_start'
  and environment = 'production'
  and subscriber_id not in (select subscriber_id from test_accounts)
```

**Gotchas.**

- **Sub-hour cancellations still count.** 8.34% of trial starts in this dataset
  are cancelled within 60 minutes. They are counted as trial starts, because the
  user did start a trial and the acquisition spend that produced them was real.
  If you exclude them, your trial-start count stops reconciling with your ad
  platform's conversion count, and nobody will be able to work out why. If you
  want the cleaner figure, use `qualified_trial_starts` (>60 min) — it exists
  precisely so people stop silently redefining `trial_starts` in their own query.
- **Trial starts are not unique users.** 490 subscribers in this dataset started
  more than one trial. Someone who trialled, churned, and returned eight months
  later generates two trial starts. For unique-human counts you need
  `count(distinct app_user_id)`, not `count(distinct subscriber_id)` — see §7.
- **Weekly products have no trial.** `premium_weekly` has zero trial days.
  Segmenting trial conversion by product without excluding it produces a
  division-by-zero or a silent null, depending on your BI tool.

**What it does not say.** A trial start is not demand and it is not intent. Trial
volume moves with paywall placement and with how aggressively the trial is
offered, so a trial-start increase alongside a conversion-rate decrease is very
often the same event viewed twice, not two findings.

---

## 2. Trial Conversion Rate

**Definition.** Of trials that ended in a given period, the share that converted
to a paid subscription.

**Implementation.**

```sql
select
  count(*) filter (where converted) * 1.0 / nullif(count(*), 0) as trial_conversion_rate
from trial_cohorts
where trial_ended_at between :start and :end
```

**Gotchas.**

- **Cohort by trial END, not trial start.** This is the one people get wrong. A
  14-day trial started on the 25th cannot convert until the following month.
  Cohorting on start date puts an unresolved trial in the denominator and
  permanently understates the current month. **Always-filter: exclude trials that
  have not yet ended.**
- **Conversion rates differ sharply by billing period** (38.8% monthly vs 47.2%
  annual, measured on cohorts whose trial has ended). A blended number will move purely because the product mix
  moved. Segment or don't quote it.
- **Conversion is not the same as revenue.** A converted annual trial is worth
  8x a converted monthly one.

**What it does not say.** Trial conversion says nothing about retention after
conversion. A paywall change that lifts conversion by pulling in lower-intent
users can raise this metric and lower LTV at the same time. Pair it with D30
retention of the converted cohort or don't act on it.

---

## 3. Tracked Revenue

**Definition.** Gross customer-facing transaction value at the moment of
purchase, before refunds and before store commission.

**Implementation.**

```sql
select sum(price_usd)
from transactions
where environment = 'production'
  and subscriber_id not in (select subscriber_id from test_accounts)
  and purchased_at between :start and :end
```

**Gotchas.**

- **It is gross, not what anyone receives.** In this dataset tracked revenue is
  $985,838 and realized revenue is $758,611 — **realized is 77.0% of tracked.**
- **It never revises downward.** Tracked revenue for March, queried in March,
  equals tracked revenue for March queried in December. That stability is why
  it's useful for attribution and why it's wrong for forecasting cash.
- **FX is converted at the transaction date.** The BRL rate moved from 0.1967 to
  0.1672 over the period covered here. Restating history at today's rate would
  change past reported revenue — so we don't. Consequence: tracked revenue mixes
  currency movement with volume movement, and a Brazil "decline" may be entirely FX.

**What it does not say.** Tracked revenue is not cash, not recognized revenue,
and not what a finance team can book. Anyone building a cash forecast on it will
be over by roughly 23%.

---

## 4. Realized Revenue

**Definition.** Tracked revenue net of refunds and store commission — what the
business actually keeps.

**Implementation.**

```sql
select
  sum(t.price_usd)                                        as tracked,
  sum(coalesce(r.refund_amount_usd, 0))                   as refunded,
  sum(t.price_usd * t.store_commission_rate)              as commission,
  sum(t.price_usd)
    - sum(coalesce(r.refund_amount_usd, 0))
    - sum(t.price_usd * t.store_commission_rate)          as realized
from transactions t
left join refunds r on r.transaction_id = t.transaction_id
where t.environment = 'production'
  and t.subscriber_id not in (select subscriber_id from test_accounts)
```

**Gotchas.**

- **This is the big one: realized revenue for a past period keeps moving.**
  Refunds land a **median of 37 days** after purchase, p90 of 65 days, max 70.
  So realized revenue for any month within the last ~70 days is *provisional and
  will fall*. Reporting it as final is the most consequential mistake available
  in this domain.
- **Attribute the refund to the original purchase date, not the refund date.**
  Otherwise a refund-heavy week corrupts a month it had nothing to do with. The
  cost of doing it correctly is that past months restate; that is the correct
  behaviour and dashboards must be built to expect it.
- **Commission is not a flat 30%.** Small-business program accounts pay 15%,
  Stripe is ~2.9%. Three distinct rates appear in this dataset. Applying a flat
  30% overstates commission by roughly a third and understates realized revenue
  accordingly.
- **Chargebacks are not modelled here.** In production they behave like refunds
  with a longer and heavier tail.

**What it does not say.** Realized revenue is not profit — it is before COGS,
infrastructure, and support cost. And a realized figure for a recent month is not
comparable to one for a settled month, because the recent one hasn't finished
falling yet.

### The rule that follows from this

**Observed in this dataset:** settled days realize at 77.0% of tracked;
days still inside the window sit at 74.3% *and will fall further*. The gap is
not a performance change, it is incomplete data.

> **Never compare a realized-revenue figure from the last 70 days against an
> older one.** The recent number is structurally incomplete. Use tracked revenue
> for recent-period comparisons, or wait for the refund window to close.

---

## 5. Active Subscriber

**Definition.** A subscriber with an entitlement in force as of a given instant.

**Implementation.**

```sql
select count(distinct subscriber_id)
from subscription_periods
where :as_of between started_at and ended_at
  and status in ('active', 'grace_period', 'billing_retry')
  and environment = 'production'
  and subscriber_id not in (select subscriber_id from test_accounts)
```

**Gotchas.**

- **Grace period and billing retry count as active, and this is a judgement
  call.** These users still have access to the product, so from a product and
  support perspective they are active. From a revenue perspective they are not
  paying. This dataset has 119 in grace period and 159 in billing retry. The
  definition above chooses *product* semantics. **If Finance asks for active
  subscribers, confirm which they mean before answering.**
- **"Active" requires a timestamp.** Active *as of when*? Month-end, month
  average, and today's count are three different numbers and get conflated
  constantly. Default here is instant-in-time at period end.
- **Deduplicate on `app_user_id`, not `subscriber_id`,** for anything
  human-shaped. See §7.

**What it does not say.** Active subscriber count is not paying-subscriber count
and it is not MRR. It also lags reality — a user who cancels today stays active
until their period ends, which for an annual plan can be eleven months away.

---

## 6. Churn — Voluntary vs Involuntary

**Definition.** Two separate metrics that must never be blended.

- **Voluntary churn** — the subscriber chose to cancel.
- **Involuntary churn** — payment failed and never recovered.

**Implementation.** `semantic/metrics.yml → voluntary_churn`, `involuntary_churn`

```sql
select
  count(*) filter (where churn_type = 'voluntary')   as voluntary,
  count(*) filter (where churn_type = 'involuntary') as involuntary
from subscription_periods
where ended_at between :start and :end
  and environment = 'production'
```

**Gotchas.**

- **In this dataset: 13,552 voluntary and 1,245 involuntary — 8.4% of churn is
  involuntary.** Blended, that reads as a single retention problem. Split, it is
  one product problem and one payments problem with completely different owners
  and completely different fixes.
- **Involuntary churn is partly recoverable.** Around 40% of billing retries
  recover here. A subscriber in retry has not churned yet, and counting them as
  churned overstates churn and understates the recovery opportunity.
- **Do not annualize monthly churn by multiplying by 12.** Compounding, and a
  mix of weekly/monthly/annual billing periods, both break that.

**What it does not say.** Churn rate says nothing about *value* churned. Losing
100 weekly subscribers and losing 100 annual subscribers are the same churn count
and a 20x difference in revenue.

---

## 7. Cross-Platform Identity

**Definition.** `app_user_id` identifies a human. `subscriber_id` identifies a
store-and-device identity. They are not the same and the gap is not small.

**Gotchas.**

- **1,163 humans in this dataset hold more than one `subscriber_id`,** up to 4.
  Someone who subscribes on iOS and later on web is two subscriber rows.
- Counting subscribers by `subscriber_id` **overstates unique customers by
  5.8% cumulatively**, but only ~1.1% among *concurrently active* subscribers,
  because a human's multiple identities are usually sequential (iOS, then later
  web) rather than simultaneous. Quote the right one: lifetime counts use the
  first, point-in-time active counts the second.
- It also **understates LTV per customer**, because one human's spend is split
  across rows and each row looks less valuable than the person actually is.

**Rule.** Revenue aggregates use `subscriber_id`. Human counts, retention curves,
and LTV use `app_user_id`.

**What it does not say.** Identity resolution is best-effort. Two people sharing
a device, or one person who never signed in, will both be wrong in ways this
field cannot detect.

---

## 8. MRR

**Definition.** Monthly-normalized recurring revenue from active paid
subscriptions.

**Implementation.** Annual plans are amortized: `price_usd / 12`. Weekly plans
are `price_usd * 52 / 12`.

**Gotchas.**

- **Amortization is a choice, and the alternative is defensible.** Recognizing
  annual revenue at the point of sale gives spikier, cash-truer numbers.
  Amortizing gives smoother, comparison-truer numbers. This layer amortizes.
  17.8% of transactions here are annual, so the choice materially changes the
  shape of the curve — and comparing an amortized MRR to a point-of-sale one
  produces a discrepancy nobody will be able to locate.
- **MRR is based on list price, not realized.** It ignores refunds and
  commission. MRR and realized revenue will never tie out, and should not be
  expected to.
- **Product changes mid-period** (741 in this dataset) mean a subscriber's MRR
  contribution can change without a new transaction.

**What it does not say.** MRR is a run-rate construct, not a cash figure and not
a forecast. It assumes everyone currently active renews at their current price.

---

## Open questions

Things this layer does not yet resolve. Listed rather than silently decided:

1. **Proration on upgrades.** Product changes are recorded as events but the
   partial-period revenue is not prorated. Upgrade revenue is currently attributed
   to the following full period.
2. **Partial refunds.** The `is_partial` flag exists and is always 0. Real store
   data has partial refunds and the realized-revenue calculation would need to
   handle them.
3. **Chargebacks.** Not modelled. Longer tail than refunds.
4. **Tax.** Not modelled. In several jurisdictions the store remits tax and the
   gross figure is tax-inclusive, which changes realized revenue again.
5. **The `test_accounts` staleness problem.** No process defined for keeping it
   current.

---

## How to use this document

If you are about to write a subscription query: read §Always-filters, then the
section for your metric, then the "what it does not say" line. If you are about to
present a number: read the "what it does not say" line again and put it in the
footnote.

If you find a case this document does not cover, that is a gap in the layer, not
a judgement call for you to make privately in a saved query. Open a PR against
this file.
