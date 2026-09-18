-- DuckDB analytical model. Sales stay in the partitioned object-store layout;
-- these tables hold the governed dimensions and dashboard-friendly facts.
CREATE OR REPLACE TABLE dim_store AS
SELECT * FROM postgres_scan('host=localhost port=5432 dbname=annapurna user=annapurna password=annapurna', 'public', 'stores');

CREATE OR REPLACE TABLE dim_category AS
SELECT * FROM postgres_scan('host=localhost port=5432 dbname=annapurna user=annapurna password=annapurna', 'public', 'product_categories');

CREATE OR REPLACE TABLE dim_product AS
SELECT * FROM postgres_scan('host=localhost port=5432 dbname=annapurna user=annapurna password=annapurna', 'public', 'products');

CREATE OR REPLACE TABLE fact_sales_line AS
SELECT
    bill_no,
    line_no,
    store_id,
    strptime(CAST(business_date AS VARCHAR), '%Y%m%d')::DATE AS business_date,
    product_code,
    CAST(qty AS DECIMAL(18,3)) AS qty,
    CAST(unit_price AS DECIMAL(18,2)) AS unit_price,
    line_type,
    CAST(qty AS DECIMAL(18,3)) * CAST(unit_price AS DECIMAL(18,2)) AS revenue_inr
FROM read_csv_auto('object_store/raw/sales/store_id=*/year=*/month=*/sales.csv', union_by_name=true);

CREATE OR REPLACE TABLE fact_revenue AS
SELECT
    f.bill_no,
    f.line_no,
    f.store_id,
    f.business_date,
    p.product_sk,
    p.category_id,
    f.line_type,
    f.revenue_inr
FROM fact_sales_line f
JOIN dim_product p
  ON p.product_code = f.product_code
 AND f.business_date >= p.valid_from
 AND f.business_date < p.valid_to + INTERVAL 1 DAY
WHERE f.line_type IN ('SALE', 'RETURN', 'DISCOUNT', 'VOID');

CREATE OR REPLACE TABLE agg_revenue_month_store_category AS
SELECT
    date_trunc('month', business_date)::DATE AS month_start,
    store_id,
    category_id,
    SUM(revenue_inr) AS revenue_inr,
    COUNT(*) AS revenue_lines
FROM fact_revenue
GROUP BY 1, 2, 3;

    CREATE OR REPLACE TABLE agg_revenue_day_store_category AS
    SELECT
        business_date,
        dayname(business_date) AS day_of_week,
        store_id,
        category_id,
        SUM(revenue_inr) AS revenue_inr,
        COUNT(*) AS revenue_lines
    FROM fact_revenue
    GROUP BY 1, 2, 3, 4;