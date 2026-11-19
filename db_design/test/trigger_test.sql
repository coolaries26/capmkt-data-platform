-- 1. future date should fail
INSERT INTO audit.ingestion_log (dataset, trade_date, source_url) VALUES ('test', current_date, 'x');
INSERT INTO raw.bhavcopy_cm (load_id, trade_date, symbol, series)
VALUES (currval(pg_get_serial_sequence('audit.ingestion_log','load_id')), current_date + 5, 'abc ', ' eq');
-- 2. a valid row should be normalised to ABC / EQ with a row_hash filled in
INSERT INTO raw.bhavcopy_cm (load_id, trade_date, symbol, series)
VALUES (currval(pg_get_serial_sequence('audit.ingestion_log','load_id')), current_date - 1, 'abc ', ' eq');
SELECT symbol, series, row_hash FROM raw.bhavcopy_cm;
-- 3. UPDATE should be blocked
UPDATE raw.bhavcopy_cm SET series = 'BE';
-- clean up
DELETE FROM raw.bhavcopy_cm; DELETE FROM audit.ingestion_log WHERE dataset = 'test';
