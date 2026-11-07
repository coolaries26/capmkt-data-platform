{% test metadata_dq(model, dataset) %}
  {%- if execute -%}
    {%- set rules = run_query(
        "select rule_name, rule_expr from " ~ ref('meta_dq_rules') ~
        " where dataset = '" ~ dataset ~ "' and severity = 'error'") -%}
    {%- if rules.rows | length == 0 -%}
      select * from {{ model }} where 1 = 0
    {%- else -%}
      {%- for r in rules.rows %}
      select '{{ r['rule_name'] }}' as failed_rule, t.*
      from {{ model }} t
      where not coalesce(({{ r['rule_expr'] }}), false)
      {{ "union all" if not loop.last }}
      {%- endfor %}
    {%- endif -%}
  {%- else -%}
    select 1 where false
  {%- endif -%}
{% endtest %}
