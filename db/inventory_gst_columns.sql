-- Phase 4: GST on inventory rows (taxable unit_price × qty + GST → bills.total_amount)
ALTER TABLE inventory
    ADD COLUMN IF NOT EXISTS gst_rate_percent NUMERIC(5, 2);
