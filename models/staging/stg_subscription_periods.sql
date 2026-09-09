select
    period_id,
    subscriber_id,
    original_transaction_id,
    product_id,
    store,
    environment,
    cast(started_at as timestamp) as started_at,
    cast(ended_at as timestamp)   as ended_at,
    status,
    cast(auto_renew_status as boolean) as auto_renew_status,
    cast(is_trial as boolean)          as is_trial,
    churn_type,
    -- Grace period and billing retry retain product access, so they count as
    -- active here. This is PRODUCT semantics, not FINANCE semantics.
    -- See DEFINITIONS.md section 5.
    status in ('active', 'grace_period', 'billing_retry') as is_entitled
from {{ source('raw', 'subscription_periods') }}
