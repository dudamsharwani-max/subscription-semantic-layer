{{ config(materialized='table') }}

-- Point-in-time entitled subscriber count, per semantic/DEFINITIONS.md #5.
--
-- DEFINITIONAL CHOICE: grace_period AND billing_retry both count as active,
-- because both retain product access. This is PRODUCT semantics. Finance
-- asking for "active subscribers" usually means paying subscribers, which is
-- a different number -- see `paying_subscribers` below. Both are exposed so
-- nobody has to redefine either one privately.

with spine as (
    select unnest(generate_series(
        (select min(cast(started_at as date)) from {{ ref('stg_subscription_periods') }}),
        (select max(cast(started_at as date)) from {{ ref('stg_subscription_periods') }}),
        interval 1 day
    ))::date as as_of_date
),

periods as (
    select * from {{ ref('stg_subscription_periods') }} p
    where {{ production_only('p') }}
),

joined as (
    select
        s.as_of_date,
        p.subscriber_id,
        sub.app_user_id,
        p.store,
        p.status,
        p.is_trial,
        p.is_entitled,
        p.status = 'active' as is_paying
    from spine s
    join periods p
      on  s.as_of_date >= cast(p.started_at as date)
      and s.as_of_date <  cast(p.ended_at as date)
    left join {{ ref('stg_subscribers') }} sub on sub.subscriber_id = p.subscriber_id
    where p.is_entitled
)

select
    as_of_date,
    -- subscriber grain: the store-identity count
    count(distinct subscriber_id)                                       as entitled_subscribers,
    count(distinct subscriber_id) filter (where is_paying)              as paying_subscribers,
    count(distinct subscriber_id) filter (where is_trial)               as trialing_subscribers,
    count(distinct subscriber_id) filter (where status = 'grace_period') as in_grace_period,
    count(distinct subscriber_id) filter (where status = 'billing_retry') as in_billing_retry,
    -- human grain: ~6% lower, and the correct denominator for anything per-person
    count(distinct app_user_id)                                         as entitled_humans
from joined
group by 1
order by 1
