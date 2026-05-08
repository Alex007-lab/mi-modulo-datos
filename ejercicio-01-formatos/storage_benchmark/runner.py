"""
runner.py — Orquesta las mediciones de benchmark para cada formato.

Métricas por formato:
  - write_avg_s:      promedio de 3 escrituras (segundos)
  - read_full_s:      lectura completa (segundos)
  - read_selective_s: lectura de columnas amount+category (segundos)
  - size_bytes:       tamaño en disco (bytes)
  - peak_memory_mb:   pico de RAM durante lectura completa (MB)
"""

import time
import tracemalloc
from pathlib import Path

import pandas as pd

from .formats import (
    write_csv, read_csv_full, read_csv_selective,
    write_json, read_json_full, read_json_selective,
    write_parquet, read_parquet_full, read_parquet_selective,
)

# ─── Definición de formatos disponibles ──────────────────────────────────────

# Cada entrada: (writer_fn, reader_full_fn, reader_selective_fn, extensión)
FORMAT_REGISTRY: dict[str, tuple] = {
    "csv": (
        lambda df, p: write_csv(df, p),
        read_csv_full,
        read_csv_selective,
        ".csv",
    ),
    "json": (
        lambda df, p: write_json(df, p),
        read_json_full,
        read_json_selective,
        ".jsonl",
    ),
    "parquet_none": (
        lambda df, p: write_parquet(df, p, compression=None),
        read_parquet_full,
        read_parquet_selective,
        ".parquet",
    ),
    "parquet_snappy": (
        lambda df, p: write_parquet(df, p, compression="snappy"),
        read_parquet_full,
        read_parquet_selective,
        ".parquet",
    ),
    "parquet_gzip": (
        lambda df, p: write_parquet(df, p, compression="gzip"),
        read_parquet_full,
        read_parquet_selective,
        ".parquet",
    ),
}

WRITE_REPEATS = 3  # Número de repeticiones para el promedio de escritura


# ─── Mediciones individuales ──────────────────────────────────────────────────

def _measure_write(writer_fn, df: pd.DataFrame, path: Path) -> float:
    """Mide el tiempo de escritura (segundos). Repite WRITE_REPEATS veces."""
    times = []
    for _ in range(WRITE_REPEATS):
        start = time.perf_counter()
        writer_fn(df, path)
        times.append(time.perf_counter() - start)
    return sum(times) / len(times)


def _measure_read(reader_fn, path: Path) -> tuple[float, float]:
    """
    Mide tiempo de lectura y pico de memoria RAM.
    Devuelve (segundos, peak_mb).
    """
    tracemalloc.start()
    start = time.perf_counter()
    reader_fn(path)
    elapsed = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    peak_mb = peak / (1024 ** 2)
    return elapsed, peak_mb


def _measure_read_selective(reader_fn, path: Path) -> float:
    """Mide solo el tiempo de lectura selectiva (sin rastreo de memoria)."""
    start = time.perf_counter()
    reader_fn(path)
    return time.perf_counter() - start


# ─── Benchmark de un formato ─────────────────────────────────────────────────

def benchmark_format(
    fmt: str,
    df: pd.DataFrame,
    data_dir: Path,
    size_label: str,
    verbose: bool = True,
) -> dict:
    """
    Ejecuta el benchmark completo para un formato dado.

    Parámetros:
        fmt:        nombre del formato (clave en FORMAT_REGISTRY)
        df:         DataFrame ya generado (NO se cuenta su creación)
        data_dir:   carpeta donde guardar los archivos temporales
        size_label: '100k', '500k' o '1m' (para nombrar el archivo)
        verbose:    si True, imprime progreso en tiempo real

    Retorna:
        dict con todas las métricas del formato.
    """
    if fmt not in FORMAT_REGISTRY:
        raise ValueError(f"Formato desconocido: '{fmt}'. Opciones: {list(FORMAT_REGISTRY)}")

    writer_fn, reader_full, reader_selective, ext = FORMAT_REGISTRY[fmt]
    path = data_dir / f"transactions_{size_label}_{fmt}{ext}"

    if verbose:
        print(f"  [{fmt}] escribiendo...", end=" ", flush=True)

    write_avg = _measure_write(writer_fn, df, path)

    if verbose:
        print(f"{write_avg:.3f}s | leyendo completo...", end=" ", flush=True)

    read_full, peak_mb = _measure_read(reader_full, path)

    if verbose:
        print(f"{read_full:.3f}s | leyendo selectivo...", end=" ", flush=True)

    read_sel = _measure_read_selective(reader_selective, path)
    size_bytes = path.stat().st_size

    if verbose:
        print(f"{read_sel:.3f}s | {size_bytes / (1024**2):.1f} MB ✓")

    return {
        "format":            fmt,
        "size_label":        size_label,
        "write_avg_s":       round(write_avg, 4),
        "read_full_s":       round(read_full, 4),
        "read_selective_s":  round(read_sel, 4),
        "size_bytes":        size_bytes,
        "size_mb":           round(size_bytes / (1024 ** 2), 2),
        "peak_memory_mb":    round(peak_mb, 2),
    }


# ─── Benchmark de todos los formatos ─────────────────────────────────────────

def benchmark_all(
    formats: list[str],
    df: pd.DataFrame,
    data_dir: Path,
    size_label: str,
) -> list[dict]:
    """
    Ejecuta benchmark_format para cada formato en la lista.
    Si un formato falla (ej: OOM con JSON en 1M), registra el error y continúa.
    Retorna lista de resultados en el mismo orden.
    """
    results = []
    for fmt in formats:
        try:
            result = benchmark_format(fmt, df, data_dir, size_label, verbose=True)
        except MemoryError as e:
            print(f"\n  [{fmt}] ERROR de memoria: {e}")
            result = {
                "format": fmt, "size_label": size_label,
                "error": "MemoryError", "write_avg_s": None,
                "read_full_s": None, "read_selective_s": None,
                "size_bytes": None, "size_mb": None, "peak_memory_mb": None,
            }
        except Exception as e:
            print(f"\n  [{fmt}] ERROR inesperado: {e}")
            result = {
                "format": fmt, "size_label": size_label,
                "error": str(e), "write_avg_s": None,
                "read_full_s": None, "read_selective_s": None,
                "size_bytes": None, "size_mb": None, "peak_memory_mb": None,
            }
        results.append(result)
    return results
