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
