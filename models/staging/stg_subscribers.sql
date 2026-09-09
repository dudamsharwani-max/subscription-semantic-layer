select
    subscriber_id,
    app_user_id,          -- the human. subscriber_id is a store identity.
    cast(first_seen_at as timestamp) as first_seen_at,
    country,
    store,
    attribution_channel
from {{ source('raw', 'subscribers') }}
