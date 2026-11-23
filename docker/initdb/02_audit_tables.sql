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
