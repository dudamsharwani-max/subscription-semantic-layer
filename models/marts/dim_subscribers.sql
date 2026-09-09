{{ config(materialized='table') }}

-- Subscriber grain, with the human (app_user_id) attached so that anything
-- human-shaped can dedupe correctly. ~6% of subscriber_ids in this dataset
-- belong to a human who already holds another. See DEFINITIONS.md section 7.

with identity as (
    select
        app_user_id,
        count(distinct subscriber_id) as subscriber_identities
    from {{ ref('stg_subscribers') }}
    group by 1
)

select
    s.subscriber_id,
    s.app_user_id,
    s.first_seen_at,
    s.country,
    s.store,
    s.attribution_channel,
    i.subscriber_identities,
    i.subscriber_identities > 1 as is_cross_platform,
    s.subscriber_id in (select subscriber_id from {{ ref('stg_test_accounts') }})
        as is_test_account
from {{ ref('stg_subscribers') }} s
left join identity i on i.app_user_id = s.app_user_id
