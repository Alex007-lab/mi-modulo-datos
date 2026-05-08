"""
storage_benchmark — Funciones de lectura/escritura por formato.

Formatos soportados:
    csv, json, parquet_none, parquet_snappy, parquet_gzip
"""

from .formats import (
    write_csv, read_csv_full, read_csv_selective,
    write_json, read_json_full, read_json_selective,
    write_parquet, read_parquet_full, read_parquet_selective,
)
from .runner import benchmark_format, benchmark_all

__all__ = [
    "write_csv", "read_csv_full", "read_csv_selective",
    "write_json", "read_json_full", "read_json_selective",
    "write_parquet", "read_parquet_full", "read_parquet_selective",
    "benchmark_format", "benchmark_all",
]
