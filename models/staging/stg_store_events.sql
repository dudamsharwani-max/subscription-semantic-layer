select
    event_id,
    subscriber_id,
    original_transaction_id,
    event_type,
    cast(event_at as timestamp) as event_at,
    product_id,
    store,
    environment
from {{ source('raw', 'store_events') }}
