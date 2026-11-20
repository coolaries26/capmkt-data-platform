# Capital Markets Data Platform

A container-first data platform for Indian equity market data (NSE end-of-day files).
Python and dbt on Postgres, then Snowflake. Packaged with Docker, run on Kubernetes,
provisioned on AWS with Terraform, orchestrated with Airflow, shipped with Jenkins.

**Owner:** Alok Srivastava | **Python:** 3.11 | **Package manager:** uv | **Roadmap start:** 19 Nov 2026

> **Honest status:** this is a personal learning project built to practise production-style
> data operations. It uses free public data and is not a claim of production experience.
> The roadmap below is the source of truth for what is done and what is not. Tick boxes only
> when the deliverable exists in the repo.

---

## 1. What this project demonstrates

| Skill | Where to look in this repo | Phase |
| ----- | -------------------------- | ----- |
| Docker | `Dockerfile`, `docker-compose.yml`, `.dockerignore` (multi-stage, non-root, healthchecks, image scan) | 1 |
| Kubernetes | `k8s/`, `charts/capmkt/` (StatefulSet, CronJob, Secrets, probes, Helm) and `docs/lab/debug-log.md` | 1 |
| Core data engineering | `src/capmkt_data_platform/`, `config/datasets.yml`, `dbt/` (idempotent loads, audit trail, metadata-driven dbt) | 2 |
| AWS | `terraform/aws/` (S3, IAM, ECR, ECS or EKS, Secrets Manager, CloudWatch) | 3 |
| Snowflake beyond a POC | `terraform/snowflake/`, `dbt/profiles.yml` (RBAC, warehouses, cost control, stages, CI environment) | 4 |
| Airflow, Jenkins, CI/CD | `airflow/`, `Jenkinsfile`, `.github/workflows/` | 5 |
| Capital-markets depth, scraping, provider onboarding | `dbt/models/marts/`, `src/.../ingest/`, a second dataset added through YAML only | 6 |

---

## 2. Architecture

### 2.1 Target architecture (end of Phase 5)

```
 SOURCES                  LANDING                 WAREHOUSE                    SERVING
 NSE archives ──┐
 Web scraping ──┼──►  S3 raw bucket  ──►  Snowflake RAW  ──►  dbt  ──►  Snowflake marts ──► Streamlit
 Vendor files ──┘     (immutable,           (COPY INTO via     (stg → int → core,
                       checksummed)          external stage)    recon, monitoring)
                          ▲                                          ▲
                          │                                          │
  Airflow (on Kubernetes) ┴── KubernetesPodOperator ── runs the pipeline image (ECR)

  Jenkins: lint → test → build image → scan → push → helm upgrade
  Terraform: S3, IAM, ECR, ECS/EKS, Secrets Manager, Snowflake roles and warehouses
```

### 2.2 Local architecture (Phases 1 and 2)

```
 NSE archives (HTTP, zip/csv)
        │
        ▼
 pipeline image (Docker)  ──►  Postgres 16 (compose, or StatefulSet on kind)
   ingest │ dbt │ dq                │ raw → stg → int → core / recon / monitoring
        ▲                           ▼
 K8s CronJob (19:30 IST, Mon-Fri)  Streamlit dashboard (Deployment + Service)
```

### 2.3 Layers

| Layer        | Schema                        | Built by              | Purpose                                         |
| ------------ | ----------------------------- | --------------------- | ----------------------------------------------- |
| Landing/raw  | `raw`                         | Python loader (COPY)  | Exact source data plus load metadata, immutable |
| Audit        | `audit`                       | Python and triggers   | Every file download and load attempt            |
| Reference    | `ref`                         | Python and seeds      | Trading calendar                                |
| Staging      | `stg`                         | dbt (metadata-driven) | Typed, cleaned, renamed                         |
| Intermediate | `int`                         | dbt                   | Business-logic building blocks                  |
| Marts        | `core`, `recon`, `monitoring` | dbt                   | Facts, dimensions, reconciliation, health       |
| Snapshots    | `snapshots`                   | dbt                   | SCD Type 2 security master                      |
| DQ           | `dq`                          | dbt `store_failures`  | Failed-row evidence                             |

### 2.4 Design principles

1. **Container-first.** Nothing is installed on the host except Docker, kubectl and git. If it
   runs in compose it runs on Kubernetes, with the same image.
2. **Metadata-driven.** `config/datasets.yml` is the single source of truth for URLs, column
   mappings, types, keys and DQ rules. Adding a dataset is a YAML change plus a sync, not new SQL.
3. **Idempotent loads.** Reloading a trade date deletes and re-inserts that date in one transaction.
4. **Raw is immutable and auditable.** A trigger blocks UPDATE on raw tables. Every load has a
   `load_id`, a file checksum and row counts.
5. **Secrets never enter git or images.** Configuration comes from the environment, Kubernetes
   Secrets, then AWS Secrets Manager.
6. **Same models, two warehouses.** Postgres for fast local development, Snowflake as the target.
   Dialect differences are handled with `adapter.dispatch`, not forks.

---

## 3. Roadmap

Target windows are approximate. Shift them if a phase runs long, and record the change in
section 11. Phases 1 to 3 close the gaps that matter most, so they come first.

### Phase 0: Hygiene (Wed 18 Nov)

- [ ] Stop tracking `.env` and `logs/`; rotate the database password; commit `.env.example` only
- [ ] Move the original long plan to `docs/design_plan.md`; commit this README
- [ ] Add `Makefile`, `.dockerignore`, and `docs/daily_log/` (template in the lab guide)

### Phase 1: Containers and Kubernetes (Weeks 1-2, 19 Nov to 2 Dec)

Guide: [`docs/lab/docker-k8s-lab.md`](docs/lab/docker-k8s-lab.md) (ten days, ten deliverables)

- [ ] Docker Engine in WSL; Postgres in compose with healthcheck, named volume and DDL on first start
- [ ] Multi-stage Dockerfile (uv, non-root numeric UID, `.dockerignore`, layer caching understood)
- [ ] Compose stack: `postgres`, `app` (profile `tools`), `streamlit`; `depends_on: service_healthy`
- [ ] Image scanned with Trivy; tagged by semver and git SHA; built in GitHub Actions; pushed to GHCR
- [ ] kind cluster (1 control plane, 2 workers); Deployments, rollouts and rollbacks understood
- [ ] Postgres StatefulSet with PVC, Secret, ConfigMap and probes; data survives pod deletion
- [ ] Ingest as a Job, then a CronJob (timezone, concurrencyPolicy, backoff, deadlines, limits, securityContext)
- [ ] Streamlit Deployment and Service; six-fault debugging drill written up in `docs/lab/debug-log.md`
- [ ] Helm chart `charts/capmkt` with `values.yaml`; install, upgrade and rollback demonstrated

**Done when:** `make kind-up && helm install capmkt charts/capmkt -n capmkt --create-namespace`
brings up the whole stack from an empty machine, and you can explain every line of it.

### Phase 2: Core pipeline, container-first (Weeks 3-4, 3 to 16 Dec)

- [ ] NSE client (headers, cookie warm-up, tenacity retries, 404 treated as `NO_FILE`)
- [ ] Metadata-driven parser; COPY loader; delete-and-insert per date; audit rows; `backfill` command
- [ ] `sync_metadata_to_seeds.py`; metadata-driven staging macro; `metadata_dq` generic test
- [ ] `fct_daily_prices` incremental model with late-arrival lookback; standard dbt tests
- [ ] Pipeline runs as Kubernetes Jobs and a CronJob; pytest and ruff green in CI

### Phase 3: AWS (Weeks 5-6, 17 to 30 Dec)

- [ ] Billing alarm and monthly budget **before** creating anything else
- [ ] Terraform with remote state: S3 raw and curated buckets (versioning, lifecycle), ECR, IAM roles with least privilege
- [ ] GitHub Actions authenticates to AWS with OIDC (no long-lived keys)
- [ ] Ingest writes immutable raw files to S3 and records the checksum in `audit.ingestion_log`
- [ ] Pipeline image runs on ECS Fargate via an EventBridge schedule (EKS as an optional short-lived exercise)
- [ ] Secrets Manager or SSM for credentials; CloudWatch logs and an alarm on failed runs; teardown script

### Phase 4: Snowflake, production style (Weeks 7-8, 31 Dec to 13 Jan)

- [ ] Role hierarchy (`RAW_LOADER`, `TRANSFORMER`, `ANALYST`), per-purpose warehouses with auto-suspend, resource monitor
- [ ] Storage integration, external stage on S3, `COPY INTO` raw tables, load history checked
- [ ] `dbt-snowflake` target; Postgres-specific SQL ported with `adapter.dispatch`; incremental models use merge
- [ ] Zero-copy clone for dev; a CI schema per pull request; time-travel recovery demonstrated
- [ ] One mart built with streams and tasks or a dynamic table; a masking policy on one column
- [ ] `docs/snowflake_design.md`: RBAC model, cost controls, and what you would change at scale

### Phase 5: Orchestration and CI/CD (Weeks 9-10, 14 to 27 Jan)

- [ ] Airflow on Kubernetes (official Helm chart) running the pipeline with `KubernetesPodOperator`
- [ ] `capmkt_daily` DAG: trading-day check, ingest, snapshot, dbt build, DQ summary; retries and failure alerts
- [ ] Jenkins in Docker with a `Jenkinsfile`: lint, test, build, scan, push, `helm upgrade`
- [ ] GitHub Actions kept for pull-request checks (ruff, pytest, `dbt parse`, sqlfluff, image build)

### Phase 6: Capital-markets depth and onboarding (Weeks 11-12, 28 Jan to 10 Feb)

- [ ] SCD2 security master, corporate-action adjustment, simulated trades with injected breaks, reconciliation
- [ ] DQ summary and ingestion-health mart; Streamlit pages for health, prices (raw vs adjusted) and breaks
- [ ] Second dataset onboarded through `datasets.yml` only; one web-scraping source (polite, rate-limited, terms checked)
- [ ] Architecture doc, interview notes, CI badge, tag `v1.0.0`

---

## 4. Technology

| Concern | Phases 1-2 (local) | Target |
| ------- | ------------------ | ------ |
| Language and packaging | Python 3.11, uv | same |
| Containers | Docker Engine in WSL2, compose | same, images in ECR or GHCR |
| Orchestration of containers | kind (Kubernetes in Docker), Helm | EKS or ECS |
| Workflow scheduling | Kubernetes CronJob | Airflow 3.1.x on Kubernetes |
| Warehouse | PostgreSQL 16 | Snowflake |
| Transformation | dbt-core 1.11 and dbt-postgres | dbt-snowflake |
| Infrastructure as code | k8s manifests, Helm | Terraform |
| CI/CD | GitHub Actions | GitHub Actions plus Jenkins |
| Observability | `kubectl logs`, audit tables | CloudWatch, Snowflake query history |
| Dashboard | Streamlit | Streamlit |

Exact versions are recorded in `uv.lock`, image tags, and `Chart.yaml`. Verify tool versions
against current release notes when you reach each phase.

---

## 5. Repository layout

```
capmkt-data-platform/
├── README.md
├── Makefile                        # make db-up | build | health | kind-up | k8s-apply | helm-up
├── Dockerfile                      # multi-stage, non-root (Phase 1)
├── docker-compose.yml              # postgres, app (profile tools), streamlit
├── .dockerignore
├── pyproject.toml  uv.lock  .python-version
├── .env.example                    # committed; the real .env is git-ignored
├── .github/workflows/ci.yml
├── Jenkinsfile                     # Phase 5
├── config/datasets.yml             # metadata: single source of truth
├── db_design/                      # DDL source files
├── docker/initdb/                  # DDL copied here; runs on first Postgres start
├── src/capmkt_data_platform/       # cli.py, ingest/, quality/, sim/
├── dbt/                            # models, macros, seeds, snapshots, profiles.yml
├── dashboards/streamlit_app.py
├── k8s/                            # kind-config.yaml, base/ manifests (Phase 1)
├── charts/capmkt/                  # Helm chart (Phase 1)
├── terraform/                      # aws/ (Phase 3), snowflake/ (Phase 4)
├── airflow/                        # dags/, values.yaml (Phase 5)
├── scripts/
├── test/
└── docs/
    ├── design_plan.md              # original detailed Phase 2 design (Docker notes superseded)
    ├── lab/docker-k8s-lab.md       # the ten-day lab
    ├── lab/debug-log.md            # symptom, command, cause, fix
    ├── architecture.md
    ├── interview_notes.md
    └── daily_log/
```

---

## 6. Quick start

Requires Docker, git and make. Commands marked (Phase 1) work once that lab day is done.

```bash
cp .env.example .env              # set a password; .env is git-ignored
make db-up                        # Postgres 16 in compose (Phase 1, day 2)
make build                        # build the pipeline image (Phase 1, day 3)
make health                       # connectivity and schema check from a container (Phase 1, day 4)
docker compose up -d streamlit    # dashboard on http://localhost:8501 (Phase 1, day 5)

make kind-up                      # local Kubernetes cluster (Phase 1, day 6)
make helm-up                      # deploy the whole stack with Helm (Phase 1, day 10)
```

---

## 9. dbt Design

### 9.1 `dbt_project.yml` (key parts)
```yaml
name: capmkt
version: "1.0.0"
profile: capmkt
model-paths: ["models"]
seed-paths: ["seeds"]
macro-paths: ["macros"]
snapshot-paths: ["snapshots"]

models:
  capmkt:
    staging:      {+materialized: view,  +schema: stg}
    intermediate: {+materialized: view,  +schema: int}
    marts:
      core:       {+materialized: table, +schema: core}
      recon:      {+materialized: table, +schema: recon}
      monitoring: {+materialized: table, +schema: monitoring}
seeds:
  capmkt:
    +schema: ref
```

### 9.2 `profiles.yml`
```yaml
capmkt:
  target: dev
  outputs:
    dev:
      type: postgres
      host: "{{ env_var('PGHOST', 'localhost') }}"
      port: "{{ env_var('PGPORT', '5432') | as_number }}"
      user: "{{ env_var('PGUSER') }}"
      password: "{{ env_var('PGPASSWORD') }}"
      dbname: "{{ env_var('PGDATABASE') }}"
      schema: public
      threads: 4
```

### 9.3 Model catalogue
| Model | Layer | Materialization | What it does |
|---|---|---|---|
| `stg_bhavcopy_cm` | staging | view | `{{ stg_select('bhavcopy_cm') }}` from `raw.bhavcopy_cm` |
| `stg_trading_calendar` | staging | view | typed calendar |
| `stg_sim_trades` | staging | view | typed trades |
| `int_security_latest` | intermediate | view | latest row per `isin + series` with surrogate `security_key` (dbt_utils) |
| `int_adjustment_factors` | intermediate | view | cumulative corporate-action factor per symbol and date |
| `snap_security_master` | snapshot | SCD2 | tracks symbol, series, name changes |
| `dim_security` | core | table | current and historical security attributes from the snapshot |
| `dim_date` | core | table | calendar attributes joined to trading calendar |
| `fct_daily_prices` | core | **incremental** | one row per `trade_date + security_key`, daily return, turnover |
| `fct_daily_prices_adj` | core | table | prices adjusted for splits and bonuses |
| `fct_positions` | core | table | cumulative quantity per account and ISIN from trades |
| `recon_trade_breaks` | recon | table | trades that fail checks against market data |
| `recon_summary` | recon | table | breaks by type and date |
| `mart_market_summary` | monitoring | table | advances, declines, turnover, top movers per day |
| `mart_ingestion_health` | monitoring | table | latest load status per date from `audit.ingestion_log` |

### 9.4 Key patterns

**Snapshot (SCD2), `snapshots/snap_security_master.yml`:**
```yaml
snapshots:
  - name: snap_security_master
    relation: ref('int_security_latest')
    config:
      schema: snapshots
      unique_key: security_key
      strategy: check
      check_cols: [symbol, series, instrument_name]
```

**Incremental fact with late-arrival lookback, `fct_daily_prices.sql`:**
```sql
{{ config(
    materialized='incremental',
    incremental_strategy='delete+insert',
    unique_key=['trade_date', 'security_key'],
    on_schema_change='append_new_columns'
) }}

select
    s.trade_date,
    {{ dbt_utils.generate_surrogate_key(['s.isin', 's.series']) }} as security_key,
    s.isin, s.symbol, s.series,
    s.open_price, s.high_price, s.low_price, s.close_price, s.prev_close_price,
    s.total_traded_qty, s.total_traded_value,
    case when s.prev_close_price > 0
         then round((s.close_price / s.prev_close_price - 1) * 100, 4) end as day_return_pct
from {{ ref('stg_bhavcopy_cm') }} s
{% if is_incremental() %}
where s.trade_date >= (select coalesce(max(trade_date), date '1900-01-01') - interval '3 days' from {{ this }})
{% endif %}
```
Use the same surrogate key expression in `int_security_latest`, so keys match.

**Corporate-action adjustment (`corporate_actions.csv` seed):** `symbol, ex_date, action_type, price_factor`
- Split, face value 10 to 5: factor `0.5`.
- Bonus x:y (x new for y held): factor `y / (x + y)`, for example 1:1 gives `0.5`.

```sql
-- int_adjustment_factors.sql (idea)
select p.symbol, p.trade_date,
       coalesce(exp(sum(ln(ca.price_factor))), 1) as cum_factor
from {{ ref('fct_daily_prices') }} p
left join {{ ref('corporate_actions') }} ca
       on ca.symbol = p.symbol and ca.ex_date > p.trade_date
group by 1, 2
```
`fct_daily_prices_adj.close_adj = close_price * cum_factor`. Prices **before** the ex-date are scaled down, so the series is continuous.

**Reconciliation (`recon_trade_breaks.sql`, idea):**
```sql
select t.*, p.low_price, p.high_price,
  case
    when p.isin is null                              then 'UNKNOWN_ISIN_OR_NO_PRICE'
    when t.quantity <= 0                             then 'INVALID_QUANTITY'
    when t.price < p.low_price or t.price > p.high_price then 'PRICE_OUTSIDE_DAY_RANGE'
    when c.is_trading_day is distinct from true      then 'NON_TRADING_DAY'
  end as break_type
from {{ ref('stg_sim_trades') }} t
left join {{ ref('fct_daily_prices') }} p
       on p.trade_date = t.trade_date and p.isin = t.isin and p.series = 'EQ'
left join {{ ref('stg_trading_calendar') }} c on c.cal_date = t.trade_date
where /* any break_type is not null */
```
`generate_trades.py` should deliberately inject about 2% bad trades (price outside range, wrong ISIN, zero quantity, holiday dates) so the recon has something to find.

**Standard tests:** `unique` and `not_null` on keys, `relationships` from facts to dims, `accepted_values` on `series`, `dbt_utils.expression_is_true` for price sanity, `dbt_utils.recency` on `fct_daily_prices`, plus the metadata-driven test above.

### 9.5 PySpark: is it required?
**No.** About 3,000 rows per day (a couple of million rows over two years) is trivial for Postgres plus dbt. Using Spark here would be tech for show. I include it as an **optional Day 18 exercise** so you can discuss when Spark starts to make sense:
- Export `fct_daily_prices` to Parquet (`pandas` + `pyarrow`).
- In PySpark (local mode), compute 20-day moving average and rolling volatility with window functions.
- Compare results to the same calculation in dbt SQL, and compare run times.
- Requires Java 17, `pyspark>=4.0,<5`. Keep it in `spark/`, not in the core pipeline.

---

## 10. Airflow on WSL (Day 11 to 13)

### 10.1 Install (separate environment)
```bash
mkdir -p ~/airflow-env && cd ~/airflow-env
uv venv --python 3.11 && source .venv/bin/activate
export AIRFLOW_HOME=~/airflow
AIRFLOW_VERSION=3.1.X          # replace X with the newest 3.1 patch on PyPI
uv pip install "apache-airflow[postgres]==${AIRFLOW_VERSION}" \
  --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-3.11.txt"
airflow version
```
Add to `~/.bashrc` (adjust the user and path):
```bash
export AIRFLOW_HOME=~/airflow
export AIRFLOW__CORE__LOAD_EXAMPLES=False
export AIRFLOW__CORE__DAGS_FOLDER=$HOME/projects/capmkt-data-platform/airflow/dags
export AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=postgresql+psycopg2://capmkt:change_me@localhost:5432/airflow_meta
```
Run: `airflow db migrate`, then `airflow standalone` (prints the admin password, UI on `http://localhost:8080`, reachable from Windows browser). Use a separate terminal tab for it.

### 10.2 DAG `airflow/dags/capmkt_daily.py` (starter, Airflow 3 style)
```python
from datetime import timedelta
import pendulum
from airflow.sdk import DAG
from airflow.providers.standard.operators.bash import BashOperator

PROJECT = "/home/<linux-user>/projects/capmkt-data-platform"
ENV = f"cd {PROJECT} && set -a && source .env && set +a && "
PY = f"{PROJECT}/.venv/bin/python"
DBT = f"{PROJECT}/.venv/bin/dbt"
DS = "{{ ds }}"

with DAG(
    dag_id="capmkt_daily",
    schedule="30 19 * * 1-5",
    start_date=pendulum.datetime(2026, 11, 9, tz="Asia/Kolkata"),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 3, "retry_delay": timedelta(minutes=15)},
    tags=["capmkt"],
) as dag:
    # exit code 99 = "not a trading day" → BashOperator marks the task skipped, downstream skipped
    is_trading_day = BashOperator(
        task_id="is_trading_day",
        bash_command=ENV + f"{PY} -m capmkt.cli is-trading-day --date {DS}",
    )
    ingest = BashOperator(
        task_id="ingest_bhavcopy",
        bash_command=ENV
        + f"{PY} -m capmkt.cli ingest --dataset bhavcopy_cm --date {DS}",
    )
    snapshot = BashOperator(
        task_id="dbt_snapshot", bash_command=ENV + f"{DBT} snapshot --project-dir dbt"
    )
    build = BashOperator(
        task_id="dbt_build", bash_command=ENV + f"{DBT} build --project-dir dbt"
    )
    dq = BashOperator(
        task_id="dq_summary",
        bash_command=ENV + f"{PY} -m capmkt.cli dq-summary --date {DS}",
    )

    is_trading_day >> ingest >> snapshot >> build >> dq
```
**Check on Day 12:** Airflow 3 changed date semantics for cron schedules. Confirm what `{{ ds }}` renders for a scheduled run and a manual run using `airflow dags test capmkt_daily 2026-11-09`, and adjust if needed.

---

## 8. Engineering workflow

Branch per day, pull request, squash merge, even working alone.

```bash
git switch main && git pull
git switch -c feature/lNN-short-topic          # lab days: l01, l02 ...
git add <files> && git commit -m "feat(docker): multi-stage image"   # feat fix docs test chore refactor
git push -u origin feature/lNN-short-topic     # open a PR, squash merge, delete the branch
git tag -a v0.N.0 -m "Phase N complete" && git push origin v0.N.0
```

A day is done when the deliverable works, tests pass, the daily log in `docs/daily_log/` is
written, the PR is merged, and `main` is pulled.

---

## 9. Security notes

- `.env`, `data/`, `logs/`, credentials, Terraform state and `*.tfvars` are never committed.
- Images run as a non-root numeric UID, with no secrets baked in; scanned with Trivy before push.
- Kubernetes Secrets are created from the environment, not from YAML in git.
  `k8s/base/secret.example.yaml` shows the shape only.
- AWS access from CI uses OIDC. Snowflake roles are least-privilege and separated by purpose.

---

## 10. Progress tracker

| Day | Date | Status | PR | Notes |
|---|---|---|---|---|
| D1 | 9 Nov | Done | cabcbdf| WSL and tooling|
| D2 | 10 Nov | Done | 2796deb| uv project scaffold|
| D3 | 11 Nov | Done | d2d6778| PostgreSQL and DDL|
| D4 | 12 Nov | Done | 279e871| Download and inspect|
| D5 | 13 Nov | Done | 21da754| Parser and loader|
| D6 to D20 | | In Progress | l01|install docker on wsl |

| Phase | Window | Status | Tag | Notes |
| ----- | ------ | ------ | --- | ----- |
| 0 Hygiene | 18 Nov | Done |  | installed docker on WSL |
| 1 Containers and Kubernetes | 19 Nov to 2 Dec | Started | v0.2.0 | v0.1.0 at lab day 5 |
| 2 Core pipeline | 3 to 16 Dec | not started | v0.3.0 | |
| 3 AWS | 17 to 30 Dec | not started | v0.4.0 | |
| 4 Snowflake | 31 Dec to 13 Jan | not started | v0.5.0 | |
| 5 Orchestration and CI/CD | 14 to 27 Jan | not started | v0.6.0 | |
| 6 Depth and onboarding | 28 Jan to 10 Feb | not started | v1.0.0 | |

## 11. Weekly plan revisions

| Date | Change | Reason |
| ---- | ------ | ------ |
| 18 Nov 2026 | Roadmap rewritten: Docker and Kubernetes moved first, AWS and Snowflake added, Postgres-only design superseded | Interview feedback: gaps in containers, AWS and production Snowflake |
