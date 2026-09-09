{{ config(materialized='table') }}

-- One row per trial. Cohorted on trial END date, because a trial cannot
-- convert until it ends -- cohorting on start date permanently understates
-- the current period. See DEFINITIONS.md section 2.

with starts as (
    select
        e.original_transaction_id,
        e.subscriber_id,
        e.product_id,
        e.store,
        e.event_at as trial_started_at
    from {{ ref('stg_store_events') }} e
    where e.event_type = 'trial_start'
      and {{ production_only('e') }}
),

cancels as (
    select original_transaction_id, min(event_at) as cancelled_at
    from {{ ref('stg_store_events') }}
    where event_type = 'trial_cancel'
    group by 1
),

conversions as (
    select original_transaction_id, min(event_at) as converted_at
    from {{ ref('stg_store_events') }}
    where event_type = 'trial_conversion'
    group by 1
),

periods as (
    select original_transaction_id, min(ended_at) as trial_ended_at
    from {{ ref('stg_subscription_periods') }}
    where is_trial
    group by 1
)

select
    s.original_transaction_id,
    s.subscriber_id,
    sub.app_user_id,
    s.product_id,
    s.store,
    s.trial_started_at,
    p.trial_ended_at,
    c.cancelled_at,
    v.converted_at,
    v.converted_at is not null                                  as converted,
    date_diff('minute', s.trial_started_at, c.cancelled_at)     as minutes_to_cancel,
    -- A trial cancelled in under an hour is still a trial start (the ad spend
    -- was real), but it is excluded from the qualified figure.
    coalesce(
        date_diff('minute', s.trial_started_at, c.cancelled_at)
            >= {{ var('qualified_trial_minutes') }},
        true
    )                                                           as is_qualified,
    row_number() over (
        partition by s.subscriber_id order by s.trial_started_at
    )                                                           as trial_sequence
from starts s
left join periods     p on p.original_transaction_id = s.original_transaction_id
left join cancels     c on c.original_transaction_id = s.original_transaction_id
left join conversions v on v.original_transaction_id = s.original_transaction_id
left join {{ ref('stg_subscribers') }} sub on sub.subscriber_id = s.subscriber_id
