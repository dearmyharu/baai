-- One-time additive migration for an existing Supabase/PostgreSQL promotion table.
-- Safe to re-run. Keeps legacy discount_pct and 2026-10 sample promotions intact.

ALTER TABLE promotion ADD COLUMN IF NOT EXISTS discount_type text;
ALTER TABLE promotion ADD COLUMN IF NOT EXISTS discount_value numeric;
ALTER TABLE promotion ADD COLUMN IF NOT EXISTS minimum_order_amount numeric DEFAULT 0;
ALTER TABLE promotion ADD COLUMN IF NOT EXISTS maximum_discount_amount numeric DEFAULT 0;
ALTER TABLE promotion ADD COLUMN IF NOT EXISTS shipping_threshold numeric;
ALTER TABLE promotion ADD COLUMN IF NOT EXISTS order_response_low_pct numeric;
ALTER TABLE promotion ADD COLUMN IF NOT EXISTS order_response_mode_pct numeric;
ALTER TABLE promotion ADD COLUMN IF NOT EXISTS order_response_high_pct numeric;

COMMENT ON COLUMN promotion.discount_type IS 'rate, fixed or none (Growth Lab policy)';
COMMENT ON COLUMN promotion.discount_value IS 'Percentage for price/rate coupons; KRW for fixed coupons/shipping threshold';
COMMENT ON COLUMN promotion.shipping_threshold IS 'KRW threshold applied to selected-category net item subtotal';
