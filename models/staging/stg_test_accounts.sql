-- Internal QA, employee, demo and load-test accounts.
-- Maintained by hand upstream, so it goes stale. Any unexplained jump in
-- subscriber counts should be checked against this table first.
select
    subscriber_id,
    reason
from {{ source('raw', 'test_accounts') }}
