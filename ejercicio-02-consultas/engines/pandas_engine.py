"""
pandas_engine.py — Las 8 queries implementadas con pandas.

Cada función recibe un DataFrame ya cargado y retorna un DataFrame resultado.
La firma es idéntica en los tres engines para facilitar la comparación.
"""

import pandas as pd


def q1_transactions_by_country(df: pd.DataFrame) -> pd.DataFrame:
    """Q1: Conteo total de transacciones por country_code, mayor a menor."""
    return (
        df.groupby("country_code", as_index=False)
        .size()
        .rename(columns={"size": "total_transactions"})
        .sort_values("total_transactions", ascending=False)
        .reset_index(drop=True)
    )


def q2_amount_stats_by_category(df: pd.DataFrame) -> pd.DataFrame:
    """Q2: Monto promedio, mínimo y máximo agrupado por category."""
    return (
        df.groupby("category", as_index=False)
        .agg(
            avg_amount=("amount", "mean"),
            min_amount=("amount", "min"),
            max_amount=("amount", "max"),
        )
        .sort_values("category")
        .reset_index(drop=True)
    )


def q3_top10_users_by_amount(df: pd.DataFrame) -> pd.DataFrame:
    """Q3: Top 10 user_id por suma de amount, con conteo de transacciones."""
    return (
        df.groupby("user_id", as_index=False)
        .agg(
            total_amount=("amount", "sum"),
            transaction_count=("amount", "count"),
        )
        .sort_values("total_amount", ascending=False)
        .head(10)
        .reset_index(drop=True)
    )


def q4_failed_by_hour(df: pd.DataFrame) -> pd.DataFrame:
    """Q4: Transacciones con status='failed' agrupadas por hora del día (0-23)."""
    failed = df[df["status"] == "failed"].copy()
    failed["hour"] = pd.to_datetime(failed["timestamp"]).dt.hour
    return (
        failed.groupby("hour", as_index=False)
        .size()
        .rename(columns={"size": "failed_count"})
        .sort_values("hour")
        .reset_index(drop=True)
    )


def q5_high_amount_mx_co(df: pd.DataFrame) -> pd.DataFrame:
    """Q5: Transacciones con amount > 500 en MX o CO, últimos 30 días del dataset."""
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    max_date = df["timestamp"].max()
    cutoff = max_date - pd.Timedelta(days=30)
    mask = (
        (df["amount"] > 500)
        & (df["country_code"].isin(["MX", "CO"]))
        & (df["timestamp"] >= cutoff)
    )
    return (
        df[mask][["transaction_id", "timestamp", "user_id", "amount", "country_code"]]
        .sort_values("timestamp")
        .reset_index(drop=True)
    )


def q6_top_category_by_country(df: pd.DataFrame) -> pd.DataFrame:
    """Q6: Por cada country_code, la category con más transacciones y su monto promedio."""
    agg = (
        df.groupby(["country_code", "category"], as_index=False)
        .agg(
            transaction_count=("amount", "count"),
            avg_amount=("amount", "mean"),
        )
    )
    # Quedarse con la categoría de mayor conteo por país
    idx = agg.groupby("country_code")["transaction_count"].idxmax()
    return (
        agg.loc[idx]
        .sort_values("country_code")
        .reset_index(drop=True)
    )


def q7_users_with_many_failures(df: pd.DataFrame) -> pd.DataFrame:
    """Q7: Usuarios con más de 5 transacciones fallidas — user_id y conteo."""
    failed = df[df["status"] == "failed"]
    counts = (
        failed.groupby("user_id", as_index=False)
        .size()
        .rename(columns={"size": "failed_count"})
    )
    return (
        counts[counts["failed_count"] > 5]
        .sort_values("failed_count", ascending=False)
        .reset_index(drop=True)
    )


def q8_daily_avg_by_category(df: pd.DataFrame) -> pd.DataFrame:
    """Q8: Monto promedio diario por category (un valor por día por categoría)."""
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["date"] = df["timestamp"].dt.date
    return (
        df.groupby(["date", "category"], as_index=False)
        .agg(avg_amount=("amount", "mean"))
        .sort_values(["date", "category"])
        .reset_index(drop=True)
    )
