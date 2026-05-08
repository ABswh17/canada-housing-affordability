-- ============================================================
-- Canada Housing Affordability - Star Schema
-- Description: Initial schema for rent and demographic data
-- ============================================================

-- 删除已存在的表（方便重跑），注意删除顺序：先删 fact 再删 dim
DROP TABLE IF EXISTS fact_rent CASCADE;
DROP TABLE IF EXISTS dim_city CASCADE;
DROP TABLE IF EXISTS dim_time CASCADE;
DROP TABLE IF EXISTS dim_property_type CASCADE;


-- ============================================================
-- DIMENSION TABLE: dim_city
-- These info can be used for single city info
-- ============================================================
CREATE TABLE dim_city (
    city_id        SERIAL PRIMARY KEY,
    city_name      VARCHAR(100) NOT NULL,
    province       VARCHAR(50)  NOT NULL,
    province_code  VARCHAR(2)   NOT NULL,
    population     INTEGER,
    latitude       DECIMAL(9, 6),
    longitude      DECIMAL(9, 6),

    -- the below will make sure the unique of city + province
    UNIQUE (city_name, province_code)
    );


-- ============================================================
-- DIMENSION TABLE: dim_time
-- These will represent the date info(mostly for the month)
-- ============================================================
CREATE TABLE dim_time (
    time_id           SERIAL PRIMARY KEY,
    year              INTEGER  NOT NULL,
    month             INTEGER  NOT NULL CHECK (month BETWEEN 1 AND 12),
    quarter           INTEGER  NOT NULL CHECK (quarter BETWEEN 1 AND 4),
    year_month_label  VARCHAR(7) NOT NULL,    -- eg: '2023-01', '2023-02'

    UNIQUE (year, month)
    );


-- ============================================================
-- DIMENSION TABLE: dim_property_type
-- These are used for the housing info
-- ============================================================
CREATE TABLE dim_property_type (
    property_type_id  SERIAL PRIMARY KEY,
    type_name         VARCHAR(50)  NOT NULL UNIQUE,
    description       VARCHAR(200)
    );


-- ============================================================
-- FACT TABLE: fact_rent
-- These are for the rent info
-- ============================================================
CREATE TABLE fact_rent (
    rent_id            SERIAL PRIMARY KEY,
    city_id            INTEGER NOT NULL REFERENCES dim_city(city_id),
    time_id            INTEGER NOT NULL REFERENCES dim_time(time_id),
    property_type_id   INTEGER NOT NULL REFERENCES dim_property_type(property_type_id),
    avg_rent_cad       DECIMAL(10, 2),
    vacancy_rate       DECIMAL(5, 2),
    data_source        VARCHAR(100)  NOT NULL, -- like 'CMHC', 'StatCan'
    loaded_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- One city only allows to have one record per month
    UNIQUE (city_id, time_id, property_type_id)
    );


-- ============================================================
-- INDEXES: I use them to improve the querying efficiency
-- ============================================================
CREATE INDEX idx_fact_rent_city ON fact_rent(city_id);
CREATE INDEX idx_fact_rent_time ON fact_rent(time_id);
CREATE INDEX idx_fact_rent_city_time ON fact_rent(city_id, time_id);


