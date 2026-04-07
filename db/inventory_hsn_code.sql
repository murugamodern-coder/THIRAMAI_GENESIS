-- HSN/SAC for statutory GST invoice line items (aligns with inventory rows).
ALTER TABLE inventory
    ADD COLUMN IF NOT EXISTS hsn_code TEXT;

COMMENT ON COLUMN inventory.hsn_code IS 'Harmonized System of Nomenclature / SAC code for GST invoices (e.g. 1006, 998314).';
