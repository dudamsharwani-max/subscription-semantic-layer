{{ config(materialized='table') }}

-- Tracked vs realized revenue by day.
--
-- The critical decision here: refunds are attributed to the ORIGINAL PURCHASE
-- DATE, not the refund date. That keeps refund cost with the revenue that
-- caused it. The consequence is that past days restate as refunds land, which
-- is correct behaviour and the reason `is_settled` exists.
--
-- See semantic/DEFINITIONS.md sections 3 and 4.

with txn as (
    select * from {{ ref('stg_transactions') }} t
    where {{ production_only('t') }}
),

refunds_at_purchase_date as (
    select
        r.transaction_id,
        sum(r.refund_amount_usd) as refund_amount_usd
    from {{ ref('stg_refunds') }} r
    inner join txn on txn.transaction_id = r.transaction_id
    group by 1
),

daily as (
    select
        cast(txn.purchased_at as date)                      as revenue_date,
        txn.store,
        txn.billing_period,
        count(*)                                            as transactions,
        sum(txn.price_usd)                                  as tracked_revenue,
        sum(coalesce(r.refund_amount_usd, 0))               as refunded_revenue,
        sum(txn.commission_usd)                             as commission,
        sum(txn.price_usd)
          - sum(coalesce(r.refund_amount_usd, 0))
          - sum(txn.commission_usd)                         as realized_revenue
    from txn
    left join refunds_at_purchase_date r
        on r.transaction_id = txn.transaction_id
    group by 1, 2, 3
)

select
    *,
    realized_revenue / nullif(tracked_revenue, 0) as realized_rate,
    -- FALSE means refunds are still landing and realized_revenue WILL fall.
    {{ is_settled('revenue_date') }}              as is_settled
from daily
