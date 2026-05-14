"""
polars_engine.py — Las 8 queries implementadas con Polars.

Polars lee el archivo Parquet directamente con pl.read_parquet().
Cada función retorna un DataFrame de pandas para poder comparar
resultados con los otros engines en el benchmark.
"""

from pathlib import Path

import polars as pl
import pandas as pd


def q1_transactions_by_country(parquet_path: Path) -> pd.DataFrame:
    """Q1: Conteo total de transacciones por country_code, mayor a menor."""
    return (
        pl.read_parquet(parquet_path)
        .group_by("country_code")
        .agg(pl.len().alias("total_transactions"))
        .sort("total_transactions", descending=True)
        .to_pandas()
    )


def q2_amount_stats_by_category(parquet_path: Path) -> pd.DataFrame:
    """Q2: Monto promedio, mínimo y máximo agrupado por category."""
    return (
        pl.read_parquet(parquet_path)
        .group_by("category")
        .agg([
            pl.col("amount").mean().alias("avg_amount"),
            pl.col("amount").min().alias("min_amount"),
            pl.col("amount").max().alias("max_amount"),
        ])
        .sort("category")
        .to_pandas()
    )


def q3_top10_users_by_amount(parquet_path: Path) -> pd.DataFrame:
    """Q3: Top 10 user_id por suma de amount, con conteo de transacciones."""
    return (
        pl.read_parquet(parquet_path)
        .group_by("user_id")
        .agg([
            pl.col("amount").sum().alias("total_amount"),
            pl.len().alias("transaction_count"),
        ])
        .sort("total_amount", descending=True)
        .head(10)
        .to_pandas()
    )


def q4_failed_by_hour(parquet_path: Path) -> pd.DataFrame:
    """Q4: Transacciones con status='failed' agrupadas por hora del día (0-23)."""
    return (
        pl.read_parquet(parquet_path)
        .filter(pl.col("status") == "failed")
        .with_columns(pl.col("timestamp").dt.hour().alias("hour"))
        .group_by("hour")
        .agg(pl.len().alias("failed_count"))
        .sort("hour")
        .to_pandas()
    )


def q5_high_amount_mx_co(parquet_path: Path) -> pd.DataFrame:
    """Q5: Transacciones con amount > 500 en MX o CO, últimos 30 días del dataset."""
    df = pl.read_parquet(parquet_path)
    max_date = df["timestamp"].max()
    cutoff = max_date - pl.duration(days=30)
    return (
        df.filter(
            (pl.col("amount") > 500)
            & (pl.col("country_code").is_in(["MX", "CO"]))
            & (pl.col("timestamp") >= cutoff)
        )
        .select(["transaction_id", "timestamp", "user_id", "amount", "country_code"])
        .sort("timestamp")
        .to_pandas()
    )


def q6_top_category_by_country(parquet_path: Path) -> pd.DataFrame:
    """Q6: Por cada country_code, la category con más transacciones y su monto promedio."""
    return (
        pl.read_parquet(parquet_path)
        .group_by(["country_code", "category"])
        .agg([
            pl.len().alias("transaction_count"),
            pl.col("amount").mean().alias("avg_amount"),
        ])
        .sort("transaction_count", descending=True)
        .group_by("country_code")
        .agg([
            pl.col("category").first(),
            pl.col("transaction_count").first(),
            pl.col("avg_amount").first(),
        ])
        .sort("country_code")
        .to_pandas()
    )


def q7_users_with_many_failures(parquet_path: Path) -> pd.DataFrame:
    """Q7: Usuarios con más de 5 transacciones fallidas — user_id y conteo."""
    return (
        pl.read_parquet(parquet_path)
        .filter(pl.col("status") == "failed")
        .group_by("user_id")
        .agg(pl.len().alias("failed_count"))
        .filter(pl.col("failed_count") > 5)
        .sort("failed_count", descending=True)
        .to_pandas()
    )


def q8_daily_avg_by_category(parquet_path: Path) -> pd.DataFrame:
    """Q8: Monto promedio diario por category (un valor por día por categoría)."""
    return (
        pl.read_parquet(parquet_path)
        .with_columns(pl.col("timestamp").dt.date().alias("date"))
        .group_by(["date", "category"])
        .agg(pl.col("amount").mean().alias("avg_amount"))
        .sort(["date", "category"])
        .to_pandas()
    )
