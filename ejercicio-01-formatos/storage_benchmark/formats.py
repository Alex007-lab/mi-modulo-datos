"""
formats.py — Funciones de escritura y lectura para cada formato de almacenamiento.

Cada función recibe/devuelve un DataFrame de pandas.
Las funciones de escritura reciben también la ruta de salida.
Las funciones de lectura selectiva leen solo las columnas: amount, category.
"""

from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

# Columnas para lectura selectiva (fijas para todo el módulo)
SELECTIVE_COLS = ["amount", "category"]


# ─── CSV ──────────────────────────────────────────────────────────────────────

def write_csv(df: pd.DataFrame, path: Path) -> None:
    df.to_csv(path, index=False)


def read_csv_full(path: Path) -> pd.DataFrame:
    return pd.read_csv(path)


def read_csv_selective(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, usecols=SELECTIVE_COLS)


# ─── JSON Lines ───────────────────────────────────────────────────────────────

def write_json(df: pd.DataFrame, path: Path) -> None:
    df.to_json(path, orient="records", lines=True)


def read_json_full(path: Path) -> pd.DataFrame:
    return pd.read_json(path, lines=True)


def read_json_selective(path: Path) -> pd.DataFrame:
    # JSON Lines no soporta proyección nativa: leemos todo y filtramos
    df = pd.read_json(path, lines=True)
    return df[SELECTIVE_COLS]


# ─── Parquet ──────────────────────────────────────────────────────────────────

def write_parquet(df: pd.DataFrame, path: Path, compression: str | None) -> None:
    """
    compression: None, 'snappy' o 'gzip'
    Usamos pyarrow directamente para tener control exacto sobre la compresión.
    """
    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, path, compression=compression)


def read_parquet_full(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path)


def read_parquet_selective(path: Path) -> pd.DataFrame:
    # Parquet soporta proyección de columnas de forma nativa (predicate pushdown)
    return pd.read_parquet(path, columns=SELECTIVE_COLS)
