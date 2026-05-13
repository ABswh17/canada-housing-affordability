"""
data_pipeline.py
================
End-to-end ETL pipeline for Canada Housing Affordability project.

Sources:
- Statistics Canada WDS API (Table 34-10-0133-01: CMHC average rents)
- Bank of Canada Valet API (V39079: Policy Interest Rate)

Target: PostgreSQL star schema + materialized analytical dataset

Run:
    python src/data_pipeline.py
"""

import os
import sys
import time
import requests
import pandas as pd
from sqlalchemy import text

# Add project root to path so we can import db_utils
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.db_utils import get_engine, query_to_df

# ============================================================
# CONFIGURATION
# ============================================================
STATCAN_BASE_URL = "https://www150.statcan.gc.ca/t1/wds/rest"
STATCAN_TABLE_PID = 34100133

BOC_URL = "https://www.bankofcanada.ca/valet/observations/V39079/json"
BOC_START_DATE = "2005-01-01"
BOC_END_DATE = "2025-12-31"

TARGET_CITIES = {
    184: ('Vancouver', 'British Columbia', 'BC', 662248, 49.2827, -123.1207, 1),
    125: ('Toronto', 'Ontario', 'ON', 2794356, 43.6532, -79.3832, 0),
    46: ('Montréal', 'Quebec', 'QC', 1762949, 45.5017, -73.5673, 0),
    106: ('Ottawa', 'Ontario', 'ON', 1017449, 45.4215, -75.6972, 0),
    146: ('Calgary', 'Alberta', 'AB', 1306784, 51.0447, -114.0719, 0),
}

STRUCTURE_ID = 3
UNIT_TYPES = {
    1: 'Bachelor',
    2: '1-Bedroom',
    3: '2-Bedroom',
    4: '3-Bedroom',
}

N_PERIODS = 20


# ============================================================
# EXTRACT
# ============================================================
def fetch_statcan_rents() -> pd.DataFrame:
    """Fetch rent data from Statistics Canada API for all target cities/units."""
    print("→ Fetching Statistics Canada rent data...")
    headers = {"Content-Type": "application/json"}
    url = f"{STATCAN_BASE_URL}/getDataFromCubePidCoordAndLatestNPeriods"
    records = []

    for geo_id, (city, prov, code, pop, lat, lon, treat) in TARGET_CITIES.items():
        for unit_id, unit_name in UNIT_TYPES.items():
            coordinate = f"{geo_id}.{STRUCTURE_ID}.{unit_id}.0.0.0.0.0.0.0"
            payload = [{
                "productId": STATCAN_TABLE_PID,
                "coordinate": coordinate,
                "latestN": N_PERIODS
            }]
            r = requests.post(url, json=payload, headers=headers, timeout=30)
            if r.status_code != 200:
                continue
            data = r.json()
            if data[0].get('status') != 'SUCCESS':
                continue
            for dp in data[0].get('object', {}).get('vectorDataPoint', []):
                records.append({
                    'city_name': city,
                    'province': prov,
                    'province_code': code,
                    'population': pop,
                    'latitude': lat,
                    'longitude': lon,
                    'treatment_group': treat,
                    'unit_type': unit_name,
                    'reference_period': dp.get('refPer'),
                    'avg_rent_cad': dp.get('value'),
                })
            time.sleep(0.3)

    df = pd.DataFrame(records)
    print(f"  ✓ Retrieved {len(df)} rent records")
    return df


def fetch_boc_rates() -> pd.DataFrame:
    """Fetch policy interest rate from Bank of Canada Valet API."""
    print("→ Fetching Bank of Canada policy rates...")
    r = requests.get(BOC_URL, params={
        "start_date": BOC_START_DATE,
        "end_date": BOC_END_DATE
    }, timeout=30)
    r.raise_for_status()
    observations = r.json()['observations']
    df = pd.DataFrame([
        {'date': o['d'], 'policy_rate': float(o['V39079']['v'])}
        for o in observations
    ])
    df['date'] = pd.to_datetime(df['date'])
    print(f"  ✓ Retrieved {len(df)} rate observations")
    return df


# ============================================================
# TRANSFORM
# ============================================================
def transform_rents(df: pd.DataFrame) -> pd.DataFrame:
    """Clean and enrich rent data."""
    print("→ Transforming rent data...")
    df['reference_period'] = pd.to_datetime(df['reference_period'])
    df['year'] = df['reference_period'].dt.year.astype(int)
    df['month'] = 1
    print(f"  ✓ Enriched {len(df)} rows with year/month")
    return df


def aggregate_annual_rates(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate daily BoC rates to annual averages."""
    print("→ Aggregating annual policy rates...")
    df['year'] = df['date'].dt.year
    annual = df.groupby('year')['policy_rate'].mean().round(2).reset_index()
    annual.columns = ['year', 'avg_policy_rate']
    print(f"  ✓ Aggregated to {len(annual)} annual records")
    return annual


def build_dim_tables(df_rents: pd.DataFrame) -> tuple:
    """Build three dimension tables from enriched rent data."""
    print("→ Building dimension tables...")

    dim_city = df_rents[[
        'city_name', 'province', 'province_code',
        'population', 'latitude', 'longitude', 'treatment_group'
    ]].drop_duplicates().reset_index(drop=True)

    dim_time = df_rents[['year', 'month']].drop_duplicates().reset_index(drop=True)
    dim_time['quarter'] = ((dim_time['month'] - 1) // 3) + 1
    dim_time['year_month_label'] = (
            dim_time['year'].astype(str) + '-' +
            dim_time['month'].astype(str).str.zfill(2)
    )
    dim_time = dim_time.sort_values(['year', 'month']).reset_index(drop=True)

    dim_property_type = pd.DataFrame({
        'type_name': ['Bachelor', '1-Bedroom', '2-Bedroom', '3-Bedroom'],
        'description': [
            'Studio apartment with no separate bedroom',
            'Apartment with one separate bedroom',
            'Apartment with two separate bedrooms',
            'Apartment with three or more bedrooms',
        ]
    })

    print(f"  ✓ dim_city: {len(dim_city)} rows")
    print(f"  ✓ dim_time: {len(dim_time)} rows")
    print(f"  ✓ dim_property_type: {len(dim_property_type)} rows")
    return dim_city, dim_time, dim_property_type


# ============================================================
# LOAD
# ============================================================
def load_dim_tables(engine, dim_city, dim_time, dim_property_type):
    """Truncate and load all dimension tables."""
    print("→ Loading dimension tables to PostgreSQL...")
    with engine.begin() as conn:
        conn.execute(text(
            "TRUNCATE TABLE fact_rent, dim_city, dim_time, dim_property_type "
            "RESTART IDENTITY CASCADE;"
        ))
    dim_city.to_sql('dim_city', engine, if_exists='append', index=False)
    dim_time.to_sql('dim_time', engine, if_exists='append', index=False)
    dim_property_type.to_sql('dim_property_type', engine, if_exists='append', index=False)
    print("  ✓ Dimension tables loaded")


def load_fact_rent(engine, df_rents):
    """Build and load fact_rent table using surrogate key lookup."""
    print("→ Building and loading fact_rent...")

    city_map = query_to_df("SELECT city_id, city_name FROM dim_city")
    time_map = query_to_df("SELECT time_id, year, month FROM dim_time")
    prop_map = query_to_df("SELECT property_type_id, type_name FROM dim_property_type")

    # Ensure dtype consistency before merge
    df_rents['year'] = df_rents['year'].astype(int)
    df_rents['month'] = df_rents['month'].astype(int)
    time_map['year'] = time_map['year'].astype(int)
    time_map['month'] = time_map['month'].astype(int)

    fact = (df_rents.copy()
            .merge(city_map, on='city_name', how='left')
            .merge(time_map, on=['year', 'month'], how='left')
            .merge(prop_map, left_on='unit_type', right_on='type_name', how='left'))

    fact['vacancy_rate'] = None
    fact['data_source'] = 'StatCan_34100133'

    fact_final = fact[[
        'city_id', 'time_id', 'property_type_id',
        'avg_rent_cad', 'vacancy_rate', 'data_source'
    ]].copy()

    fact_final.to_sql('fact_rent', engine, if_exists='append', index=False)
    print(f"  ✓ Loaded {len(fact_final)} rows to fact_rent")


def build_analytical_dataset(engine, df_annual_rates):
    """Build denormalized analytical dataset for downstream analysis."""
    print("→ Building analytical_dataset...")
    fact_with_year = query_to_df("""
        SELECT f.rent_id, f.city_id, f.time_id, f.property_type_id,
               f.avg_rent_cad, t.year
        FROM fact_rent f
        JOIN dim_time t ON f.time_id = t.time_id
    """)
    analytical = fact_with_year.merge(df_annual_rates, on='year', how='left')
    analytical.to_sql('analytical_dataset', engine, if_exists='replace', index=False)
    print(f"  ✓ Saved {len(analytical)} rows to analytical_dataset")


# ============================================================
# MAIN
# ============================================================
def main():
    print("=" * 60)
    print("Canada Housing Affordability - ETL Pipeline")
    print("=" * 60)

    engine = get_engine()

    # Extract
    df_rents_raw = fetch_statcan_rents()
    df_boc_raw = fetch_boc_rates()

    # Transform
    df_rents = transform_rents(df_rents_raw)
    df_annual_rates = aggregate_annual_rates(df_boc_raw)
    dim_city, dim_time, dim_property_type = build_dim_tables(df_rents)

    # Load
    load_dim_tables(engine, dim_city, dim_time, dim_property_type)
    load_fact_rent(engine, df_rents)
    build_analytical_dataset(engine, df_annual_rates)

    print("\n" + "=" * 60)
    print("✓ ETL pipeline complete")
    print("=" * 60)


if __name__ == "__main__":
    main()