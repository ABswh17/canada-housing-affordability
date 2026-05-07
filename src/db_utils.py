"""
Database utility functions for the Canada Housing Affordability project.
Handles connection management and common DB operations.
"""

import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import pandas as pd

# 加载 .env 文件中的环境变量
load_dotenv()


def get_engine():
    """
    创建并返回 SQLAlchemy engine。
    Engine 是连接池，比每次新建 connection 高效得多。
    """
    db_host = os.getenv("DB_HOST")
    db_port = os.getenv("DB_PORT")
    db_name = os.getenv("DB_NAME")
    db_user = os.getenv("DB_USER")
    db_password = os.getenv("DB_PASSWORD")

    # PostgreSQL 连接字符串格式
    connection_string = (
        f"postgresql+psycopg2://{db_user}:{db_password}"
        f"@{db_host}:{db_port}/{db_name}"
    )

    engine = create_engine(connection_string)
    return engine


def execute_sql_file(filepath: str):
    """
    读取并执行一个 .sql 文件。
    用于跑建表脚本等 DDL 语句。
    """
    engine = get_engine()
    with open(filepath, 'r', encoding='utf-8') as f:
        sql_content = f.read()

    # 用 with 上下文管理器自动提交事务
    with engine.begin() as conn:
        conn.execute(text(sql_content))

    print(f"✓ Executed: {filepath}")


def query_to_df(sql: str) -> pd.DataFrame:
    """
    执行 SELECT 查询并返回 DataFrame。
    这是你之后做分析时最常用的函数。
    """
    engine = get_engine()
    return pd.read_sql(sql, engine)


def df_to_table(df: pd.DataFrame, table_name: str, if_exists: str = "replace"):
    """
    把 DataFrame 写入数据库表。
    if_exists: 'replace'（覆盖）, 'append'（追加）, 'fail'（已存在则报错）
    """
    engine = get_engine()
    df.to_sql(table_name, engine, if_exists=if_exists, index=False)
    print(f"✓ Wrote {len(df)} rows to {table_name}")


if __name__ == "__main__":
    # 测试连接
    try:
        engine = get_engine()
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version();"))
            version = result.fetchone()[0]
            print(f"✓ Connected to PostgreSQL")
            print(f"  Version: {version}")
    except Exception as e:
        print(f"✗ Connection failed: {e}")