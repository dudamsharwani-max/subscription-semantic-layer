{#
  The always-filters from semantic/DEFINITIONS.md, in one place.

  Every metric in this project excludes sandbox transactions and internal
  test accounts. Defining it once here is the difference between a rule
  and a convention people forget.
#}

{% macro production_only(alias='') %}
    {%- set p = alias ~ '.' if alias else '' -%}
    {{ p }}environment = 'production'
    and {{ p }}subscriber_id not in (select subscriber_id from {{ ref('stg_test_accounts') }})
{% endmacro %}


{% macro is_settled(date_column) %}
    {#- True when a period is old enough that refunds have finished landing. -#}
    {{ date_column }} < current_date - interval '{{ var("refund_settlement_days") }} days'
{% endmacro %}
