CREATE TABLE ref.trading_calendar (
    cal_date        date PRIMARY KEY,
    is_trading_day  boolean NOT NULL,
    holiday_desc    text,
    source          text,
    created_at      timestamptz NOT NULL DEFAULT now()
);
-- populate: all dates of the year; weekends false; NSE holidays false with description
