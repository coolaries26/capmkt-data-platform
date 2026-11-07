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
