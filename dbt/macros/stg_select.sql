{% macro stg_select(dataset) %}
  {%- if execute -%}
    {%- set q -%}
      select target_col, coalesce(transform, '') as transform
      from {{ ref('meta_columns') }}
      where dataset = '{{ dataset }}' and in_staging = true
      order by ordinal
    {%- endset -%}
    {%- set rows = run_query(q) -%}
    {%- for r in rows.rows %}
      {% if r['transform'] != '' %}{{ r['transform'] }}{% else %}{{ r['target_col'] }}{% endif %} as {{ r['target_col'] }}{{ "," if not loop.last }}
    {%- endfor %}
  {%- else -%}
    1 as placeholder
  {%- endif -%}
{% endmacro %}
