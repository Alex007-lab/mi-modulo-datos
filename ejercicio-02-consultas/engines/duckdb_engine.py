"""
duckdb_engine.py — Las 8 queries implementadas con DuckDB.

DuckDB lee el archivo Parquet directamente mediante la función read_parquet().
NO se carga el archivo en pandas primero — DuckDB opera sobre el archivo en disco.

Cada función recibe la ruta al archivo Parquet y retorna un DataFrame de pandas
para que el benchmark pueda comparar resultados entre engines.
"""

from pathlib import Path

import duckdb
import pandas as pd


def _con() -> duckdb.DuckDBPyConnection:
    """Crea una conexión in-memory a DuckDB."""
    return duckdb.connect()


def q1_transactions_by_country(parquet_path: Path) -> pd.DataFrame:
    """Q1: Conteo total de transacciones por country_code, mayor a menor."""
    sql = f"""
        SELECT
            country_code,
            COUNT(*) AS total_transactions
        FROM read_parquet('{parquet_path}')
        GROUP BY country_code
        ORDER BY total_transactions DESC
    """
    return _con().execute(sql).df()


def q2_amount_stats_by_category(parquet_path: Path) -> pd.DataFrame:
    """Q2: Monto promedio, mínimo y máximo agrupado por category."""
    sql = f"""
        SELECT
            category,
            AVG(amount)  AS avg_amount,
            MIN(amount)  AS min_amount,
            MAX(amount)  AS max_amount
        FROM read_parquet('{parquet_path}')
        GROUP BY category
        ORDER BY category
    """
    return _con().execute(sql).df()


def q3_top10_users_by_amount(parquet_path: Path) -> pd.DataFrame:
    """Q3: Top 10 user_id por suma de amount, con conteo de transacciones."""
    sql = f"""
        SELECT
            user_id,
            SUM(amount)  AS total_amount,
            COUNT(*)     AS transaction_count
        FROM read_parquet('{parquet_path}')
        GROUP BY user_id
        ORDER BY total_amount DESC
        LIMIT 10
    """
    return _con().execute(sql).df()


def q4_failed_by_hour(parquet_path: Path) -> pd.DataFrame:
    """Q4: Transacciones con status='failed' agrupadas por hora del día (0-23)."""
    sql = f"""
        SELECT
            HOUR(timestamp) AS hour,
            COUNT(*)        AS failed_count
        FROM read_parquet('{parquet_path}')
        WHERE status = 'failed'
        GROUP BY hour
        ORDER BY hour
    """
    return _con().execute(sql).df()


def q5_high_amount_mx_co(parquet_path: Path) -> pd.DataFrame:
    """Q5: Transacciones con amount > 500 en MX o CO, últimos 30 días del dataset."""
    sql = f"""
        WITH max_date AS (
            SELECT MAX(timestamp) AS max_ts
            FROM read_parquet('{parquet_path}')
        )
        SELECT
            t.transaction_id,
            t.timestamp,
            t.user_id,
            t.amount,
            t.country_code
        FROM read_parquet('{parquet_path}') t, max_date
        WHERE t.amount > 500
          AND t.country_code IN ('MX', 'CO')
          AND t.timestamp >= max_date.max_ts - INTERVAL '30 days'
        ORDER BY t.timestamp
    """
    return _con().execute(sql).df()


def q6_top_category_by_country(parquet_path: Path) -> pd.DataFrame:
    """Q6: Por cada country_code, la category con más transacciones y su monto promedio."""
    sql = f"""
        WITH category_stats AS (
            SELECT
                country_code,
                category,
                COUNT(*)    AS transaction_count,
                AVG(amount) AS avg_amount
            FROM read_parquet('{parquet_path}')
            GROUP BY country_code, category
        ),
        ranked AS (
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY country_code
                    ORDER BY transaction_count DESC
                ) AS rn
            FROM category_stats
        )
        SELECT country_code, category, transaction_count, avg_amount
        FROM ranked
        WHERE rn = 1
        ORDER BY country_code
    """
    return _con().execute(sql).df()


def q7_users_with_many_failures(parquet_path: Path) -> pd.DataFrame:
    """Q7: Usuarios con más de 5 transacciones fallidas — user_id y conteo."""
    sql = f"""
        SELECT
            user_id,
            COUNT(*) AS failed_count
        FROM read_parquet('{parquet_path}')
        WHERE status = 'failed'
        GROUP BY user_id
        HAVING COUNT(*) > 5
        ORDER BY failed_count DESC
    """
    return _con().execute(sql).df()


def q8_daily_avg_by_category(parquet_path: Path) -> pd.DataFrame:
    """Q8: Monto promedio diario por category (un valor por día por categoría)."""
    sql = f"""
        SELECT
            CAST(timestamp AS DATE) AS date,
            category,
            AVG(amount) AS avg_amount
        FROM read_parquet('{parquet_path}')
        GROUP BY date, category
        ORDER BY date, category
    """
    return _con().execute(sql).df()


# ─── EXPLAIN ANALYZE para Q3, Q5 y Q6 ───────────────────────────────────────

def explain_q3(parquet_path: Path) -> str:
    sql = f"""
        EXPLAIN ANALYZE
        SELECT
            user_id,
            SUM(amount)  AS total_amount,
            COUNT(*)     AS transaction_count
        FROM read_parquet('{parquet_path}')
        GROUP BY user_id
        ORDER BY total_amount DESC
        LIMIT 10
    """
    rows = _con().execute(sql).fetchall()
    return "\n".join(r[1] for r in rows)


def explain_q5(parquet_path: Path) -> str:
    sql = f"""
        EXPLAIN ANALYZE
        WITH max_date AS (
            SELECT MAX(timestamp) AS max_ts
            FROM read_parquet('{parquet_path}')
        )
        SELECT
            t.transaction_id,
            t.timestamp,
            t.user_id,
            t.amount,
            t.country_code
        FROM read_parquet('{parquet_path}') t, max_date
        WHERE t.amount > 500
          AND t.country_code IN ('MX', 'CO')
          AND t.timestamp >= max_date.max_ts - INTERVAL '30 days'
        ORDER BY t.timestamp
    """
    rows = _con().execute(sql).fetchall()
    return "\n".join(r[1] for r in rows)


def explain_q6(parquet_path: Path) -> str:
    sql = f"""
        EXPLAIN ANALYZE
        WITH category_stats AS (
            SELECT
                country_code,
                category,
                COUNT(*)    AS transaction_count,
                AVG(amount) AS avg_amount
            FROM read_parquet('{parquet_path}')
            GROUP BY country_code, category
        ),
        ranked AS (
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY country_code
                    ORDER BY transaction_count DESC
                ) AS rn
            FROM category_stats
        )
        SELECT country_code, category, transaction_count, avg_amount
        FROM ranked
        WHERE rn = 1
        ORDER BY country_code
    """
    rows = _con().execute(sql).fetchall()
    return "\n".join(r[1] for r in rows)
