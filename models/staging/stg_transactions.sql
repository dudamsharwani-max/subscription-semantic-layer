select
    transaction_id,
    original_transaction_id,
    subscriber_id,
    product_id,
    store,
    environment,
    period_type,
    cast(is_renewal as boolean)            as is_renewal,
    cast(purchased_at as timestamp)        as purchased_at,
    cast(expires_at as timestamp)          as expires_at,
    price_usd,
    price_local,
    currency,
    fx_rate_at_purchase,
    store_commission_rate,
    price_usd * store_commission_rate      as commission_usd,
    case
        when product_id like '%annual%' then 'P1Y'
        when product_id like '%weekly%' then 'P1W'
        else 'P1M'
    end                                    as billing_period
from {{ source('raw', 'transactions') }}
