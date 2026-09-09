select
    refund_id,
    transaction_id,
    subscriber_id,
    original_transaction_id,
    cast(refunded_at as timestamp) as refunded_at,
    refund_amount_usd,
    reason,
    cast(is_partial as boolean)    as is_partial
from {{ source('raw', 'refunds') }}
