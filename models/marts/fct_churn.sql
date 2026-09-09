{{ config(materialized='table') }}

-- Voluntary and involuntary churn kept separate. Blending them hides a
-- payments problem inside a retention problem. See DEFINITIONS.md section 6.

select
    p.period_id,
    p.subscriber_id,
    s.app_user_id,
    p.product_id,
    p.store,
    p.started_at,
    p.ended_at,
    cast(p.ended_at as date) as churn_date,
    p.status,
    p.churn_type,
    p.is_trial,
    -- Still in retry: not churned yet, and ~40% of these recover.
    p.status = 'billing_retry' and p.churn_type is null as is_recoverable
from {{ ref('stg_subscription_periods') }} p
left join {{ ref('stg_subscribers') }} s on s.subscriber_id = p.subscriber_id
where {{ production_only('p') }}
  and p.churn_type is not null
