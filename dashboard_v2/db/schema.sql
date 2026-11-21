-- ver.2 데이터 테이블 (Supabase/PostgreSQL). CSV 파일 이름 = 테이블 이름, 열 이름도 같음.
-- 순서대로 실행: 참조되는 테이블을 먼저 만든다.

CREATE TABLE IF NOT EXISTS customer (
    customer_id        text PRIMARY KEY,
    signup_date        date NOT NULL,
    signup_channel     text,
    birth_year         integer,
    gender             text,
    region             text,
    membership_grade   text,
    account_status     text,
    marketing_consent  boolean
);

CREATE TABLE IF NOT EXISTS customer_initial_snapshot (
    customer_id               text PRIMARY KEY REFERENCES customer(customer_id),
    snapshot_date             date,
    prior_order_count         integer,
    first_purchase_date       date,
    last_purchase_date        date,
    prior_visit_count         integer,
    last_visit_date           date,
    initial_membership_grade  text,
    initial_account_status    text
);

CREATE TABLE IF NOT EXISTS customer_prior_monthly_sales (
    customer_id                text REFERENCES customer(customer_id),
    sales_month                date,
    completed_purchase_amount  bigint,
    PRIMARY KEY (customer_id, sales_month)
);

CREATE TABLE IF NOT EXISTS customer_grade_history (
    grade_history_id  text PRIMARY KEY,
    customer_id       text REFERENCES customer(customer_id),
    membership_grade  text,
    effective_from    timestamp,
    effective_to      timestamp
);

CREATE TABLE IF NOT EXISTS product (
    product_id      text PRIMARY KEY,
    product_name    text,
    brand           text,
    category        text,
    cost_price      integer,
    product_status  text,
    launch_date     date
);

CREATE TABLE IF NOT EXISTS product_price_history (
    price_history_id  text PRIMARY KEY,
    product_id        text REFERENCES product(product_id),
    list_price        integer,
    sale_price        integer,
    effective_from    timestamp,
    effective_to      timestamp
);

CREATE TABLE IF NOT EXISTS curation_theme (
    theme_id    text PRIMARY KEY,
    theme_name  text,
    start_date  date,
    end_date    date,
    placement   text
);

CREATE TABLE IF NOT EXISTS curation_product (
    theme_id      text REFERENCES curation_theme(theme_id),
    product_id    text REFERENCES product(product_id),
    display_rank  integer,
    PRIMARY KEY (theme_id, product_id)
);

CREATE TABLE IF NOT EXISTS coupon (
    coupon_id                text PRIMARY KEY,
    coupon_name              text,
    discount_type            text,
    discount_value           numeric,
    minimum_order_amount     integer,
    maximum_discount_amount  numeric,
    start_date               timestamp,
    end_date                 timestamp,
    eligibility_type         text
);

CREATE TABLE IF NOT EXISTS orders (
    order_id                text PRIMARY KEY,
    customer_id             text REFERENCES customer(customer_id),
    order_time              timestamp,
    order_status            text,
    items_amount            integer,
    coupon_discount_amount  integer,
    shipping_fee            integer,
    total_amount            integer,
    payment_method          text
);

CREATE TABLE IF NOT EXISTS order_items (
    order_item_id              text PRIMARY KEY,
    order_id                   text REFERENCES orders(order_id),
    product_id                 text REFERENCES product(product_id),
    quantity                   integer,
    list_unit_price            integer,
    sale_unit_price            integer,
    product_discount_amount    integer,
    sales_amount               integer,
    allocated_coupon_discount  integer
);

CREATE TABLE IF NOT EXISTS order_coupon (
    order_coupon_id  text PRIMARY KEY,
    order_id         text REFERENCES orders(order_id),
    coupon_id        text REFERENCES coupon(coupon_id),
    discount_amount  integer
);

CREATE TABLE IF NOT EXISTS event_log (
    event_id     text PRIMARY KEY,
    customer_id  text REFERENCES customer(customer_id),
    session_id   text,
    event_time   timestamp,
    event_type   text,
    theme_id     text,
    product_id   text,
    page         text,
    position     integer,
    order_id     text
);

-- 실행 계획(프로모션). Growth Lab에서 등록한 계획도 여기에 쌓인다.
CREATE TABLE IF NOT EXISTS promotion (
    promotion_id    text PRIMARY KEY,
    promotion_name  text,
    category        text,
    lever           text,
    discount_pct    numeric,
    discount_type  text,
    discount_value numeric,
    shipping_threshold numeric,
    order_response_low_pct numeric,
    order_response_mode_pct numeric,
    order_response_high_pct numeric,
    start_date      date,
    end_date        date,
    primary_metric  text,
    guard_metric    text,
    stop_rule       text,
    status          text,
    is_simulated    boolean
);

CREATE INDEX IF NOT EXISTS idx_orders_time ON orders(order_time);
CREATE INDEX IF NOT EXISTS idx_items_order ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_event_time ON event_log(event_time);
CREATE INDEX IF NOT EXISTS idx_event_session ON event_log(session_id);

-- Existing installations: CREATE TABLE IF NOT EXISTS does not add columns.
-- Safe to re-run during the Growth Lab upgrade.
ALTER TABLE promotion ADD COLUMN IF NOT EXISTS discount_type text;
ALTER TABLE promotion ADD COLUMN IF NOT EXISTS discount_value numeric;
ALTER TABLE promotion ADD COLUMN IF NOT EXISTS shipping_threshold numeric;
ALTER TABLE promotion ADD COLUMN IF NOT EXISTS order_response_low_pct numeric;
ALTER TABLE promotion ADD COLUMN IF NOT EXISTS order_response_mode_pct numeric;
ALTER TABLE promotion ADD COLUMN IF NOT EXISTS order_response_high_pct numeric;
