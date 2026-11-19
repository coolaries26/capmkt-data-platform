# Capital Markets Data Platform (NSE End-of-Day Pipeline)

A portfolio project that ingests NSE equity end-of-day data into PostgreSQL, models it with a **metadata-driven dbt** project, orchestrates it with **Airflow (on WSL)**, and adds corporate-action adjustment, trade reconciliation, data-quality monitoring and a Streamlit dashboard.

**Owner:** Alok Srivastava | **Python:** 3.11 | **Package manager:** uv | **Planned start:** Mon 9 Nov 2026 | **Effort:** ~3 hrs/day, 20 working days

> Status: Week 0 (plan). Update the *Weekly Plan Revisions* section at the end of every week.

---

## 1. Scope and Architecture

```
NSE archives (HTTP, zip/csv)
        │  Airflow DAG: capmkt_daily (Mon-Fri evening IST)
        ▼
[ is_trading_day ] → [ ingest ] → [ dbt snapshot ] → [ dbt build ] → [ dq summary ]
                          │                │                │
                          ▼                ▼                ▼
                   raw.bhavcopy_cm     snapshots.*      stg → int → core / recon / monitoring
                   audit.ingestion_log                  dq.* (failed rows)
                                                              │
                                                              ▼
                                                     Streamlit dashboard
```

| Layer | Schema | Built by | Purpose |
|---|---|---|---|
| Landing/raw | `raw` | Python loader (COPY) | Exact source data plus load metadata, immutable |
| Audit | `audit` | Python + triggers | Every file download and load attempt |
| Reference | `ref` | Python / seeds | Trading calendar |
| Staging | `stg` | dbt (metadata-driven) | Typed, cleaned, renamed |
| Intermediate | `int` | dbt | Business logic building blocks |
| Marts | `core`, `recon`, `monitoring` | dbt | Facts, dimensions, reconciliation, health |
| Snapshots | `snapshots` | dbt | SCD Type 2 security master |
| DQ | `dq` | dbt `store_failures` | Failed-row evidence |

### Design principles
1. **Metadata-driven:** `config/datasets.yml` is the single source of truth for URLs, column mappings, types, keys and DQ rules. Python reads it directly. dbt reads it through generated seeds.
2. **Idempotent loads:** reloading a trade date deletes and re-inserts that date in one transaction.
3. **Raw is immutable:** a trigger blocks UPDATE on raw tables.
4. **Everything is auditable:** every load has a `load_id`, file checksum and row counts.

---

## 2. Data Sources

All free, public, no login. Use for personal learning only. **Do not commit data files or redistribute them** (check NSE's terms of use). `data/` is git-ignored.

| Dataset | URL pattern | Notes |
|---|---|---|
| **CM UDiFF Bhavcopy (primary)** | `https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{YYYYMMDD}_F_0000.csv.zip` | Daily zip containing one CSV, includes ISIN. Available from about July 2024 (older dates use a different format, so start your backfill from 2025-01-01). |
| Securities bhavcopy with delivery (optional) | `https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{DDMMYYYY}.csv` | Has delivery quantity, **no ISIN**. Optional extension. |
| NSE report catalogue | `https://www.nseindia.com/all-reports` | Browse here if a URL changes. NSE has changed bhavcopy locations before. |
| Exchange holidays | `https://www.nseindia.com/resources/exchange-communication-holidays` | Load the yearly list into `ref.trading_calendar` (manually or via script). |
| Corporate actions | NSE corporate actions page | Hand-pick 5 to 10 real splits/bonuses into a dbt seed. Do not scrape on Day 1. |

**Practical notes (verify on Day 4):**
- NSE rejects bare `requests` calls. Send a browser-like `User-Agent`, `Referer`, and make one warm-up GET to `https://www.nseindia.com` to obtain cookies.
- Files appear in the evening after market close. Schedule the DAG for about 19:30 IST and retry.
- Weekends and exchange holidays return 404 (or 403). Treat as `NO_FILE`, not as an error.
- Be polite: sleep 1 to 2 seconds between requests when backfilling.
- Expect about 2,500 to 3,000 rows per day. Six months is roughly 350k rows, so Postgres is more than enough.
- Column names are UDiFF style (for example `TradDt`, `TckrSymb`, `SctySrs`, `ClsPric`, `TtlTradgVol`). **Inspect the real header on Day 4 and correct `datasets.yml` accordingly.** I have not seen today's file, so treat my column list as a starting point.

---

## 3. Assumptions (correct me if any are wrong)

- Windows 10 22H2 or Windows 11, 16 GB RAM (8 GB minimum), 30 GB free disk, virtualization enabled in BIOS.
- Everything runs **inside WSL2 Ubuntu 24.04**, including Postgres, uv, dbt and Airflow. Repo lives in `~/projects`, never in `/mnt/c` (slow file I/O).
- Public GitHub repo (no secrets, no data committed).
- Postgres 16 from Ubuntu apt. No Docker (keeps the learning focus on the tools).
- Airflow and the project use **separate virtual environments** (dependency conflicts between Airflow's constraint file and dbt are common). Airflow calls the project venv through `BashOperator`.

---

## 4. Prerequisites and Versions

I verified the dbt and Airflow lines below against current release notes. Everything else is a range, and **`uv.lock` becomes the exact record** after Day 2. Commit it.

### 4.1 System (WSL Ubuntu 24.04)
| Item | Version | Install |
|---|---|---|
| WSL | 2 (latest, `wsl --update`) | PowerShell as admin |
| Ubuntu | 24.04 LTS | `wsl --install -d Ubuntu-24.04` |
| PostgreSQL | 16 (Ubuntu default) | `sudo apt install postgresql postgresql-contrib libpq-dev` |
| git | latest apt | `sudo apt install git` |
| build tools | n/a | `sudo apt install build-essential curl unzip` |
| uv | latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Python | 3.11 (via uv, not apt) | `uv python install 3.11` |
| Java 17 (**only for optional PySpark**) | OpenJDK 17 | `sudo apt install openjdk-17-jdk` |

### 4.2 Project environment (`~/projects/capmkt-data-platform/.venv`)
| Package | Spec | Why |
|---|---|---|
| dbt-core | `>=1.11,<1.12` | Verified: 1.11.x is the stable line; 1.12.0 appeared Aug 2026, upgrade later as a stretch |
| dbt-postgres | `>=1.10,<1.11` | Verified pairing with core 1.11 in dbt's compatible release (June 2026) |
| requests | `>=2.32` | HTTP download |
| tenacity | `>=9` | retries |
| pandas | `>=2.2` | parse and cast |
| numpy | `>=1.26` | numeric helpers |
| SQLAlchemy | `>=2.0,<2.1` | engine and metadata |
| psycopg[binary] | `>=3.2` | fast COPY loading |
| pydantic-settings | `>=2.4` | typed config from `.env` |
| PyYAML | `>=6` | read `datasets.yml` |
| typer | `>=0.12` | CLI (`python -m capmkt.cli ...`) |
| streamlit | `>=1.40` | dashboard |
| plotly | `>=5.24` | charts |
| **dev:** pytest, pytest-cov, ruff, pre-commit, sqlfluff + sqlfluff-templater-dbt | latest | quality gates |
| **optional:** pyspark `>=4.0,<5`, pyarrow `>=17` | needs Java 17 | Day 18 only |

dbt packages (`dbt/packages.yml`): `dbt-labs/dbt_utils` `>=1.3.0,<2.0.0`.

### 4.3 Airflow environment (`~/airflow-env/.venv`, separate)
| Package | Spec |
|---|---|
| apache-airflow | **3.1.x**. Pick the newest 3.1.x patch shown on PyPI on Day 11 (I saw 3.1.7 listed as stable; a newer one may exist). Supports Python 3.11. |
| extras | `[postgres]` |
| constraint file | `https://raw.githubusercontent.com/apache/airflow/constraints-<AIRFLOW_VERSION>/constraints-3.11.txt` |

Always install Airflow **with its constraint file**. Specify both the Airflow version and the Python version in the URL.

---

## 5. Folder Structure

```
capmkt-data-platform/
├── README.md
├── pyproject.toml              # uv-managed
├── uv.lock                     # commit this
├── .python-version             # 3.11
├── .env.example                # copy to .env (git-ignored)
├── .gitignore
├── .pre-commit-config.yaml
├── Makefile                    # make db / ingest / dbt / test shortcuts
├── .github/workflows/ci.yml
├── config/
│   └── datasets.yml            # metadata: single source of truth
├── sql/
│   ├── 00_roles_databases.sql
│   ├── 01_schemas.sql
│   ├── 02_audit_tables.sql
│   ├── 03_raw_tables.sql       # partitioned raw table, sim_trades
│   ├── 04_ref_tables.sql
│   ├── 05_triggers.sql
│   └── 06_grants.sql
├── src/capmkt/
│   ├── settings.py             # pydantic-settings
│   ├── db.py                   # engine + psycopg connection helpers
│   ├── metadata.py             # loads datasets.yml
│   ├── cli.py                  # typer: ingest, backfill, is-trading-day, load-calendar, dq-summary
│   ├── ingest/
│   │   ├── nse_client.py       # session, headers, retries
│   │   ├── parser.py           # zip/csv → typed DataFrame using metadata
│   │   ├── loader.py           # COPY + delete/insert per date + audit log
│   │   ├── calendar.py         # trading calendar helpers
│   │   └── backfill.py
│   ├── sim/generate_trades.py  # synthetic trades with injected breaks
│   └── quality/dq_summary.py
├── scripts/
│   └── sync_metadata_to_seeds.py   # datasets.yml → dbt seeds
├── dbt/
│   ├── dbt_project.yml
│   ├── profiles.yml            # uses env vars, no secrets
│   ├── packages.yml
│   ├── macros/
│   │   ├── generate_schema_name.sql
│   │   ├── stg_select.sql          # metadata-driven select list
│   │   └── metadata_dq.sql         # metadata-driven generic test
│   ├── seeds/
│   │   ├── meta_columns.csv        # generated
│   │   ├── meta_dq_rules.csv       # generated
│   │   └── corporate_actions.csv   # hand-maintained
│   ├── snapshots/snap_security_master.yml
│   └── models/
│       ├── staging/    (_sources.yml, _stg.yml, stg_bhavcopy_cm, stg_trading_calendar, stg_sim_trades)
│       ├── intermediate/ (int_security_latest, int_adjustment_factors)
│       └── marts/
│           ├── core/        (dim_security, dim_date, fct_daily_prices, fct_daily_prices_adj, fct_positions)
│           ├── recon/       (recon_trade_breaks, recon_summary)
│           └── monitoring/  (mart_market_summary, mart_ingestion_health)
├── airflow/dags/capmkt_daily.py
├── dashboards/streamlit_app.py
├── spark/                      # optional Day 18
├── tests/                      # pytest for parser, loader, calendar
├── docs/
│   ├── architecture.md
│   ├── interview_notes.md
│   └── daily_log/              # one short file per day
└── data/                       # git-ignored landing area
```

---

## 6. WSL and Tooling Setup (Day 1 and 2)

### 6.1 Install WSL (PowerShell as Administrator)
```powershell
wsl --install -d Ubuntu-24.04
# reboot when asked, then create your Linux username/password
wsl --update
wsl -l -v          # VERSION column must show 2
```
Create `C:\Users\<you>\.wslconfig` to stop WSL eating all RAM:
```ini
[wsl2]
memory=6GB
processors=4
swap=2GB
```
Then `wsl --shutdown` and reopen Ubuntu.

If `wsl --install` fails: enable *Virtualization* in BIOS, and enable Windows features *Virtual Machine Platform* and *Windows Subsystem for Linux*.

### 6.2 Inside Ubuntu
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y build-essential curl git unzip postgresql postgresql-contrib libpq-dev

# enable systemd (needed for postgres service management)
printf "[boot]\nsystemd=true\n" | sudo tee /etc/wsl.conf
# then in PowerShell: wsl --shutdown   and reopen Ubuntu

git config --global user.name  "Alok Srivastava"
git config --global user.email "you@example.com"
git config --global init.defaultBranch main
ssh-keygen -t ed25519 -C "you@example.com"      # add ~/.ssh/id_ed25519.pub to GitHub → Settings → SSH keys
ssh -T git@github.com
```

### 6.3 VS Code
1. Install VS Code on Windows, then the **WSL** extension (`ms-vscode-remote.remote-wsl`).
2. In Ubuntu: `mkdir -p ~/projects && cd ~/projects && code .`
3. Install these extensions **in the WSL window**: Python, Pylance, Ruff, Even Better TOML, YAML, GitLens, PostgreSQL (or SQLTools), and *dbt Power User*.

### 6.4 uv project scaffold (Python 3.11)
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh && source ~/.bashrc
uv python install 3.11
cd ~/projects
git clone git@github.com:<your-user>/capmkt-data-platform.git && cd capmkt-data-platform
uv init --package --python 3.11 .          # src layout, creates pyproject.toml
uv python pin 3.11
uv add "requests>=2.32" "tenacity>=9" "pandas>=2.2" "numpy>=1.26" "SQLAlchemy>=2.0,<2.1" \
       "psycopg[binary]>=3.2" "pydantic-settings>=2.4" "PyYAML>=6" "typer>=0.12" \
       "dbt-core>=1.11,<1.12" "dbt-postgres>=1.10,<1.11" "streamlit>=1.40" "plotly>=5.24"
uv add --dev pytest pytest-cov ruff pre-commit sqlfluff sqlfluff-templater-dbt
uv sync
uv run python --version     # must print 3.11.x
uv run dbt --version
```
VS Code: `Ctrl+Shift+P → Python: Select Interpreter → .venv/bin/python`.

`.env.example`:
```
PGHOST=localhost
PGPORT=5432
PGDATABASE=capmkt
PGUSER=capmkt
PGPASSWORD=change_me
DBT_PROFILES_DIR=./dbt
DATA_DIR=./data
```
`.gitignore` must include: `.venv/`, `.env`, `data/`, `dbt/target/`, `dbt/dbt_packages/`, `dbt/logs/`, `__pycache__/`, `*.zip`, `*.parquet`.

---

## 7. Database Design

Run as the postgres superuser once: `sudo -u postgres psql -f sql/00_roles_databases.sql`, then the rest as `capmkt`.

### 7.1 `00_roles_databases.sql`
```sql
CREATE ROLE capmkt WITH LOGIN PASSWORD 'change_me';
CREATE DATABASE capmkt       OWNER capmkt;
CREATE DATABASE airflow_meta OWNER capmkt;   -- Airflow's own metadata DB
```

### 7.2 `01_schemas.sql` (connect to `capmkt`)
```sql
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS audit;
CREATE SCHEMA IF NOT EXISTS ref;
CREATE SCHEMA IF NOT EXISTS stg;
CREATE SCHEMA IF NOT EXISTS int;
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS recon;
CREATE SCHEMA IF NOT EXISTS monitoring;
CREATE SCHEMA IF NOT EXISTS snapshots;
CREATE SCHEMA IF NOT EXISTS dq;
```

### 7.3 `02_audit_tables.sql`
```sql
CREATE TABLE audit.ingestion_log (
    load_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dataset        text        NOT NULL,
    trade_date     date        NOT NULL,
    source_url     text        NOT NULL,
    http_status    int,
    file_name      text,
    file_sha256    char(64),
    rows_in_file   int,
    rows_loaded    int,
    status         text        NOT NULL DEFAULT 'STARTED'
                   CHECK (status IN ('STARTED','SUCCESS','NO_FILE','FAILED','SUPERSEDED')),
    error_message  text,
    started_at     timestamptz NOT NULL DEFAULT now(),
    finished_at    timestamptz,
    updated_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_ingestion_log_ds_date ON audit.ingestion_log (dataset, trade_date, started_at DESC);
-- only one live SUCCESS per dataset/date; reloads mark the old one SUPERSEDED
CREATE UNIQUE INDEX ux_ingestion_one_success
    ON audit.ingestion_log (dataset, trade_date) WHERE status = 'SUCCESS';
```

### 7.4 `03_raw_tables.sql`
```sql
CREATE TABLE raw.bhavcopy_cm (
    load_id             bigint        NOT NULL REFERENCES audit.ingestion_log(load_id),
    trade_date          date          NOT NULL,
    business_date       date,
    segment             text,
    source              text,
    instrument_type     text,
    instrument_id       text,
    isin                text,
    symbol              text          NOT NULL,
    series              text          NOT NULL,
    instrument_name     text,
    open_price          numeric(14,4),
    high_price          numeric(14,4),
    low_price           numeric(14,4),
    close_price         numeric(14,4),
    last_price          numeric(14,4),
    prev_close_price    numeric(14,4),
    settlement_price    numeric(14,4),
    total_traded_qty    bigint,
    total_traded_value  numeric(20,2),
    total_trades        bigint,
    session_id          text,
    remarks             text,
    row_hash            char(32),
    loaded_at           timestamptz   NOT NULL DEFAULT now(),
    PRIMARY KEY (trade_date, symbol, series)   -- verify uniqueness on Day 4; add instrument_id if needed
) PARTITION BY RANGE (trade_date);

CREATE TABLE raw.bhavcopy_cm_2024 PARTITION OF raw.bhavcopy_cm FOR VALUES FROM ('2024-01-01') TO ('2025-01-01');
CREATE TABLE raw.bhavcopy_cm_2025 PARTITION OF raw.bhavcopy_cm FOR VALUES FROM ('2025-01-01') TO ('2026-01-01');
CREATE TABLE raw.bhavcopy_cm_2026 PARTITION OF raw.bhavcopy_cm FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');
CREATE TABLE raw.bhavcopy_cm_2027 PARTITION OF raw.bhavcopy_cm FOR VALUES FROM ('2027-01-01') TO ('2028-01-01');
CREATE TABLE raw.bhavcopy_cm_default PARTITION OF raw.bhavcopy_cm DEFAULT;

-- indexes (created on the parent, propagate to partitions)
CREATE INDEX ix_bhav_isin_date   ON raw.bhavcopy_cm (isin, trade_date);
CREATE INDEX ix_bhav_symbol_date ON raw.bhavcopy_cm (symbol, trade_date DESC);
CREATE INDEX ix_bhav_load_id     ON raw.bhavcopy_cm (load_id);
CREATE INDEX brin_bhav_loaded_at ON raw.bhavcopy_cm USING brin (loaded_at);

-- synthetic trades for the reconciliation exercise (deliberately NOT strict)
CREATE TABLE raw.sim_trades (
    trade_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    generated_batch text   NOT NULL,
    trade_date      date   NOT NULL,
    account_id      text   NOT NULL,
    isin            text   NOT NULL,
    side            char(1) NOT NULL CHECK (side IN ('B','S')),
    quantity        bigint NOT NULL,
    price           numeric(14,4) NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_simtrades_isin_date ON raw.sim_trades (isin, trade_date);
```

### 7.5 `04_ref_tables.sql`
```sql
CREATE TABLE ref.trading_calendar (
    cal_date        date PRIMARY KEY,
    is_trading_day  boolean NOT NULL,
    holiday_desc    text,
    source          text,
    created_at      timestamptz NOT NULL DEFAULT now()
);
-- populate: all dates of the year; weekends false; NSE holidays false with description
```

### 7.6 `05_triggers.sql`
```sql
-- 1) keep updated_at fresh on the audit log
CREATE OR REPLACE FUNCTION audit.set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at := now(); RETURN NEW; END $$;

CREATE TRIGGER trg_ingestion_log_updated
BEFORE UPDATE ON audit.ingestion_log
FOR EACH ROW EXECUTE FUNCTION audit.set_updated_at();

-- 2) normalise keys, block future dates, compute a row hash for change detection
CREATE OR REPLACE FUNCTION raw.bhavcopy_before_insert() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.symbol := upper(btrim(NEW.symbol));
    NEW.series := upper(btrim(NEW.series));
    NEW.isin   := upper(nullif(btrim(NEW.isin), ''));
    IF NEW.trade_date > current_date THEN
        RAISE EXCEPTION 'trade_date % is in the future', NEW.trade_date;
    END IF;
    NEW.row_hash := md5(concat_ws('|', NEW.trade_date, NEW.symbol, NEW.series, NEW.isin,
                        NEW.open_price, NEW.high_price, NEW.low_price, NEW.close_price,
                        NEW.total_traded_qty, NEW.total_traded_value));
    RETURN NEW;
END $$;

CREATE TRIGGER trg_bhavcopy_before_insert
BEFORE INSERT ON raw.bhavcopy_cm
FOR EACH ROW EXECUTE FUNCTION raw.bhavcopy_before_insert();

-- 3) raw is immutable: reloads must be DELETE + INSERT, never UPDATE
CREATE OR REPLACE FUNCTION raw.block_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'raw.% is immutable. Reload via delete+insert.', TG_TABLE_NAME; END $$;

CREATE TRIGGER trg_bhavcopy_block_update
BEFORE UPDATE ON raw.bhavcopy_cm
FOR EACH ROW EXECUTE FUNCTION raw.block_update();
```
Interview talking point: row-level triggers cost some speed during COPY of large files. Measure it on Day 10 and discuss the trade-off (move logic into Python or into dbt staging if it hurts).

### 7.7 `06_grants.sql`
Run as the postgres superuser while connected to `capmkt`. Because `capmkt` owns the database, it can already create schemas. Making it the owner of each schema keeps things simple:
```sql
ALTER SCHEMA raw        OWNER TO capmkt;
ALTER SCHEMA audit      OWNER TO capmkt;
ALTER SCHEMA ref        OWNER TO capmkt;
ALTER SCHEMA stg        OWNER TO capmkt;
ALTER SCHEMA int        OWNER TO capmkt;
ALTER SCHEMA core       OWNER TO capmkt;
ALTER SCHEMA recon      OWNER TO capmkt;
ALTER SCHEMA monitoring OWNER TO capmkt;
ALTER SCHEMA snapshots  OWNER TO capmkt;
ALTER SCHEMA dq         OWNER TO capmkt;
```
(Not needed at all if you run files 01 to 05 as `capmkt`, since it then owns everything it creates. In a real platform you would split loader, dbt and read-only dashboard roles.)

---

## 8. Metadata-Driven Design

### 8.1 `config/datasets.yml` (starter)
```yaml
datasets:
  bhavcopy_cm:
    description: NSE Capital Market UDiFF bhavcopy
    url_template: "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{yyyymmdd}_F_0000.csv.zip"
    file_format: zip_csv
    target_table: raw.bhavcopy_cm
    natural_key: [trade_date, symbol, series]
    columns:     # VERIFY every source name against the real header on Day 4
      - {source: TradDt,       target: trade_date,         type: date,    in_staging: true, transform: ""}
      - {source: BizDt,        target: business_date,      type: date,    in_staging: true, transform: ""}
      - {source: Sgmt,         target: segment,            type: text,    in_staging: true, transform: ""}
      - {source: FinInstrmTp,  target: instrument_type,    type: text,    in_staging: true, transform: ""}
      - {source: FinInstrmId,  target: instrument_id,      type: text,    in_staging: true, transform: ""}
      - {source: ISIN,         target: isin,               type: text,    in_staging: true, transform: ""}
      - {source: TckrSymb,     target: symbol,             type: text,    in_staging: true, transform: ""}
      - {source: SctySrs,      target: series,             type: text,    in_staging: true, transform: ""}
      - {source: FinInstrmNm,  target: instrument_name,    type: text,    in_staging: true, transform: "nullif(btrim(instrument_name), '')"}
      - {source: OpnPric,      target: open_price,         type: numeric, in_staging: true, transform: ""}
      - {source: HghPric,      target: high_price,         type: numeric, in_staging: true, transform: ""}
      - {source: LwPric,       target: low_price,          type: numeric, in_staging: true, transform: ""}
      - {source: ClsPric,      target: close_price,        type: numeric, in_staging: true, transform: ""}
      - {source: LastPric,     target: last_price,         type: numeric, in_staging: true, transform: ""}
      - {source: PrvsClsgPric, target: prev_close_price,   type: numeric, in_staging: true, transform: ""}
      - {source: TtlTradgVol,  target: total_traded_qty,   type: bigint,  in_staging: true, transform: ""}
      - {source: TtlTrfVal,    target: total_traded_value, type: numeric, in_staging: true, transform: ""}
      - {source: TtlNbOfTxsExctd, target: total_trades,    type: bigint,  in_staging: true, transform: ""}
    dq_rules:
      - {name: high_ge_low,        expr: "high_price >= low_price",                         severity: error}
      - {name: close_within_range, expr: "close_price between low_price and high_price",    severity: error}
      - {name: positive_close,     expr: "close_price > 0",                                 severity: error}
      - {name: non_negative_qty,   expr: "total_traded_qty >= 0",                           severity: error}
      - {name: isin_format,        expr: "isin is null or isin ~ '^[A-Z]{2}[A-Z0-9]{9}[0-9]$'", severity: warn}
```

### 8.2 Flow
`datasets.yml` → `scripts/sync_metadata_to_seeds.py` → `dbt/seeds/meta_columns.csv` and `meta_dq_rules.csv` → `dbt seed` → macros read the seeds with `run_query`.

Seed columns: `meta_columns(dataset, ordinal, target_col, data_type, in_staging, transform)` and `meta_dq_rules(dataset, rule_name, rule_expr, severity)`.

Adding a new dataset or rule should need **a YAML change and a sync, not new SQL**. That is the point of the exercise.

### 8.3 `dbt/macros/generate_schema_name.sql`
Use schema names exactly as configured (otherwise dbt prefixes them with the target schema):
```jinja
{% macro generate_schema_name(custom_schema_name, node) -%}
    {{ custom_schema_name | trim if custom_schema_name is not none else target.schema }}
{%- endmacro %}
```

### 8.4 `dbt/macros/stg_select.sql`
```jinja
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
```

### 8.5 `dbt/macros/metadata_dq.sql` (generic test returning failing rows)
```jinja
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
```
Usage in `_stg.yml` (dbt 1.10+ nests test arguments under `arguments:`; if your version complains, use the flat form):
```yaml
models:
  - name: stg_bhavcopy_cm
    data_tests:
      - metadata_dq:
          arguments: {dataset: bhavcopy_cm}
          config: {store_failures: true, schema: dq}
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

## 11. Git Workflow (every day, no exceptions)

Branch per day, pull request, squash merge. Even solo, this builds the habit interviewers ask about.

```bash
# start of day
git switch main && git pull
git switch -c feature/dayNN-short-topic

# during the day: small, meaningful commits
git add <files>
git commit -m "feat(ingest): add NSE client with retries"      # types: feat, fix, docs, test, chore, refactor

# end of day
uv run ruff check . && uv run pytest -q                          # must pass
git push -u origin feature/dayNN-short-topic
gh pr create --fill          # or open the PR on GitHub
# merge on GitHub using "Squash and merge", then:
git switch main && git pull
git branch -d feature/dayNN-short-topic

# end of each week: tag a release
git tag -a v0.N.0 -m "Week N complete" && git push origin v0.N.0
```
Also save a short `docs/daily_log/YYYY-MM-DD.md` (done, blocked, learned, tomorrow) in each day's branch.

Never commit: `.env`, `data/`, passwords, downloaded NSE files.

---

## 12. Daily Plan (about 3 hours/day)

Weekends are buffer for catch-up. **Definition of done for every day:** deliverable works, tests pass, daily log written, PR merged, `main` pulled.

### Week 1: Foundations and Ingestion (9 to 13 Nov)
| Day | Goal | Tasks | Deliverable |
|---|---|---|---|
| **D1 Mon 9 Nov** | WSL and tooling | Section 6.1 to 6.3. Create GitHub repo, clone via SSH, first commit with README and `.gitignore`. | `wsl -l -v` shows v2, VS Code opens in WSL, first push done. Branch `feature/day01-wsl-setup` |
| **D2 Tue 10 Nov** | uv project scaffold | Section 6.4. Folder structure, `pyproject.toml`, ruff, pytest, pre-commit, `.env`. `uv.lock` committed. | `uv run python --version` is 3.11, `uv run dbt --version` works, one passing dummy test |
| **D3 Wed 11 Nov** | PostgreSQL and DDL | Start Postgres, create roles/DBs, run all `sql/*.sql`. Test each trigger by hand (future date, UPDATE, normalisation). | All schemas, tables, partitions, indexes, 3 triggers exist. Screenshot or `\d+` output in daily log |
| **D4 Thu 12 Nov** | Download and inspect | Manually download one day's zip with the browser, inspect the real header. Implement `nse_client.py` (headers, warm-up, retry, 404 handling). Finalise `datasets.yml` against the real header. Check the primary-key uniqueness assumption in pandas. | Client downloads a known trading day, `datasets.yml` matches reality, notes on any surprises |
| **D5 Fri 13 Nov** | Parser and loader | `parser.py` (metadata-driven rename and cast), `loader.py` (COPY into temp/direct, delete+insert per date in one transaction, supersede old SUCCESS, write audit row). CLI `ingest --date`. pytest for parser using a tiny fixture file. Load 5 consecutive days, then re-run one day to prove idempotency. | Row counts match file counts, re-run keeps counts unchanged. **Tag v0.1.0** |

### Week 2: dbt and Modelling (16 to 20 Nov)
| Day | Goal | Tasks | Deliverable |
|---|---|---|---|
| **D6 Mon** | dbt bootstrap | `dbt init` equivalent folder, `profiles.yml`, `packages.yml`, `dbt deps`, `dbt debug`. Sources file. Write `sync_metadata_to_seeds.py`, `dbt seed`. | `dbt debug` all green, seeds loaded to `ref` |
| **D7 Tue** | Metadata-driven staging | `generate_schema_name`, `stg_select` macro, `stg_bhavcopy_cm`, `stg_trading_calendar`. Load the trading calendar for 2025 to 2026. | `dbt run -s staging` succeeds, staging columns come from metadata |
| **D8 Wed** | Dimensions and SCD2 | `int_security_latest`, snapshot, `dim_security`, `dim_date`. Run the snapshot on two different loaded days. | Snapshot table with `dbt_valid_from/to`, test with a changed name |
| **D9 Thu** | Fact and DQ | Incremental `fct_daily_prices`. `metadata_dq` test, standard tests. Break the data on purpose and see the test catch it. | `dbt build` passes, failing-row table appears in `dq` schema when you inject bad data |
| **D10 Fri** | Backfill and tuning | `backfill` CLI (date range, polite sleep, skips existing). Backfill 2025-07-01 to today. Run `EXPLAIN ANALYZE` on typical queries, adjust indexes, measure trigger cost. Full-refresh vs incremental timing. **Tag v0.2.0** | Backfill complete, tuning notes in `docs/` |

### Week 3: Orchestration, Corporate Actions, Reconciliation (23 to 27 Nov)
| Day | Goal | Tasks | Deliverable |
|---|---|---|---|
| **D11 Mon** | Airflow install | Section 10.1. Pick the version, install with constraints, `airflow standalone`, hello-world DAG. | UI reachable at localhost:8080 from Windows |
| **D12 Tue** | Ingest DAG | `is-trading-day` CLI (exit 99), DAG tasks 1 and 2, retries. Verify date semantics with `airflow dags test`. Manual trigger for a past date. | Green run, skipped run on a weekend |
| **D13 Wed** | Full DAG | Add snapshot, dbt build, dq-summary. Failure test (stop Postgres, see retry). Document how to rerun a failed date. | End-to-end green DAG run |
| **D14 Thu** | Corporate actions | Real splits/bonuses seed, `int_adjustment_factors`, `fct_daily_prices_adj`. Pick one real split, check the adjusted series has no price cliff. | Chart (or query) showing a continuous adjusted series |
| **D15 Fri** | Reconciliation | `generate_trades.py`, `fct_positions`, `recon_trade_breaks`, `recon_summary`. Confirm injected breaks are found. **Tag v0.3.0** | Recon summary matches the number of injected breaks |

### Week 4: Quality, Dashboard, Polish (30 Nov to 4 Dec)
| Day | Goal | Tasks | Deliverable |
|---|---|---|---|
| **D16 Mon** | DQ framework | `dq_summary.py` (counts by rule and date from `dq` schema), `mart_ingestion_health`, freshness check. | One query that answers "is today's data healthy?" |
| **D17 Tue** | Dashboard | Streamlit app: ingestion health, market summary, price chart (raw vs adjusted), recon breaks. | Dashboard runs locally, screenshots saved |
| **D18 Wed** | Optional PySpark | Java 17, parquet export, moving average and volatility in Spark vs SQL. Skip if behind, nothing depends on it. | `spark/` notebook or script with comparison notes |
| **D19 Thu** | CI and docs | GitHub Actions (ruff, pytest, `dbt parse`, sqlfluff). `dbt docs generate`. `docs/architecture.md` with the diagram. | Green CI badge in README |
| **D20 Fri** | Finish and publish | README final pass, `docs/interview_notes.md`, LinkedIn post, resume wording. **Tag v1.0.0** | Public repo, post live |

**Resume wording (honest):** "Built an end-to-end NSE capital-markets data pipeline (Airflow, dbt, PostgreSQL) covering ingestion, SCD2 security master, corporate-action adjustment and trade reconciliation as a personal project." Do not list capital markets as work experience.

---

## 13. Daily Progress Review Loop

At the end of each day, paste this into the chat (plus the PR link if the repo is public, or the relevant command output):

```
Day: NN
Done:
Not done / blocked:
Key outputs (row counts, dbt build summary, errors):
PR link or commit hash:
Time spent:
Question for tomorrow:
```
I will give feedback on: correctness of what you built, code and SQL quality, whether the Git steps were followed, what to fix before moving on, and a plan for the next day (adjusted if you are ahead or behind).

**Weekly:** at the end of each Friday I will update the *Weekly Plan Revisions* table below and send you the refreshed README.

---

## 14. Troubleshooting Quick List

| Symptom | Likely cause and fix |
|---|---|
| `403` or empty response from NSE | Missing headers or cookie warm-up. Send `User-Agent` and `Referer`, hit the home page first, slow down. |
| `404` for a date | Holiday, weekend, or file not yet published. Log `NO_FILE`, retry later if it is a trading day. |
| Zip has an unexpected CSV name | Read the first entry in the zip, do not hardcode the name. |
| `psql: connection refused` in WSL | `sudo systemctl start postgresql` (or `sudo service postgresql start` without systemd). |
| Airflow cannot reach Postgres | Check `SQL_ALCHEMY_CONN`, run `airflow db migrate`, confirm the user can log in with `psql`. |
| dbt `relation does not exist` | Run order: load raw data first, then `dbt seed`, `dbt snapshot`, `dbt build`. |
| Slow file access | Repo is under `/mnt/c`. Move it to `~/projects`. |
| Airflow and dbt dependency clash | They must stay in separate venvs. Never `pip install` Airflow into the project venv. |

---

## 15. Interview Talking Points (collect as you go)
- Why partition the raw table, and why a BRIN index on `loaded_at`.
- Idempotency strategy: delete+insert per date vs `ON CONFLICT`, and why UPDATE is blocked on raw.
- Trigger cost vs transparency trade-off.
- Late-arriving data and the 3-day incremental lookback.
- SCD2 with dbt snapshot (`check` strategy) vs hand-built.
- How metadata-driven design reduces code changes when a new dataset arrives.
- Why Airflow and dbt live in separate environments.
- When Spark would make sense, and why it does not here.
- Reconciliation as a data-quality pattern (the same idea as your IBM Siebel-to-Sugar CRM work).

---

## 16. Weekly Plan Revisions

| Week | Date updated | Change | Reason |
|---|---|---|---|
| Week 0 | 6 Nov 2026 | Initial plan created | n/a |
| Week 1 | | | |
| Week 2 | | | |
| Week 3 | | | |
| Week 4 | | | |

## 17. Progress Tracker

| Day | Date | Status | PR | Notes |
|---|---|---|---|---|
| D1 | 9 Nov | not started | | |
| D2 | 10 Nov | not started | | |
| D3 | 11 Nov | not started | | |
| D4 | 12 Nov | not started | | |
| D5 | 13 Nov | not started | | |
| D6 to D20 | | not started | | |
