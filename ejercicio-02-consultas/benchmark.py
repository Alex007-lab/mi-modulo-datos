"""
benchmark.py — Ejecuta las 8 queries en los 3 engines, valida equivalencia
               y mide tiempo de ejecución y pico de memoria.

Uso:
    python benchmark.py --parquet ../ejercicio-01-formatos/data/transactions_1m.parquet
    python benchmark.py --parquet data/transactions_1m.parquet --output results/
"""

import argparse
import json
import sys
import time
import tracemalloc
from pathlib import Path

import pandas as pd
import numpy as np

PROJECT_DIR = Path(__file__).parent
sys.path.insert(0, str(PROJECT_DIR))

from engines import pandas_engine as pe
from engines import duckdb_engine as de
from engines import polars_engine as pole

RESULTS_DIR = PROJECT_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)

# ─── Definición de queries ────────────────────────────────────────────────────

QUERIES = {
    "Q1": "Conteo por country_code",
    "Q2": "Stats de amount por category",
    "Q3": "Top 10 users por amount",
    "Q4": "Transacciones fallidas por hora",
    "Q5": "Amount>500 en MX/CO últimos 30 días",
    "Q6": "Top category por country_code",
    "Q7": "Usuarios con >5 fallos",
    "Q8": "Promedio diario por category",
}

# Mapeo query → función por engine
PANDAS_FNS = {
    "Q1": pe.q1_transactions_by_country,
    "Q2": pe.q2_amount_stats_by_category,
    "Q3": pe.q3_top10_users_by_amount,
    "Q4": pe.q4_failed_by_hour,
    "Q5": pe.q5_high_amount_mx_co,
    "Q6": pe.q6_top_category_by_country,
    "Q7": pe.q7_users_with_many_failures,
    "Q8": pe.q8_daily_avg_by_category,
}

DUCKDB_FNS = {
    "Q1": de.q1_transactions_by_country,
    "Q2": de.q2_amount_stats_by_category,
    "Q3": de.q3_top10_users_by_amount,
    "Q4": de.q4_failed_by_hour,
    "Q5": de.q5_high_amount_mx_co,
    "Q6": de.q6_top_category_by_country,
    "Q7": de.q7_users_with_many_failures,
    "Q8": de.q8_daily_avg_by_category,
}

POLARS_FNS = {
    "Q1": pole.q1_transactions_by_country,
    "Q2": pole.q2_amount_stats_by_category,
    "Q3": pole.q3_top10_users_by_amount,
    "Q4": pole.q4_failed_by_hour,
    "Q5": pole.q5_high_amount_mx_co,
    "Q6": pole.q6_top_category_by_country,
    "Q7": pole.q7_users_with_many_failures,
    "Q8": pole.q8_daily_avg_by_category,
}


# ─── Medición ─────────────────────────────────────────────────────────────────

def measure(fn, *args) -> tuple[pd.DataFrame, float, float]:
    """
    Ejecuta fn(*args), retorna (resultado, tiempo_s, peak_mb).
    Usa tracemalloc para el pico de RAM.
    """
    tracemalloc.start()
    t0 = time.perf_counter()
    result = fn(*args)
    elapsed = time.perf_counter() - t0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return result, round(elapsed, 4), round(peak / 1024**2, 2)


# ─── Validación de equivalencia ───────────────────────────────────────────────

def normalize(df: pd.DataFrame) -> pd.DataFrame:
    """
    Prepara un DataFrame para comparación:
    - Ordena columnas alfabéticamente
    - Ordena filas por todas las columnas
    - Redondea floats a 2 decimales
    - Resetea el índice
    """
    df = df.copy()
    # Redondear floats
    float_cols = df.select_dtypes(include="float").columns
    df[float_cols] = df[float_cols].round(2)
    # Convertir fechas a string para comparar
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].astype(str)
        elif hasattr(df[col], "dt"):
            df[col] = df[col].astype(str)
    # Convertir columnas object a string limpio
    obj_cols = df.select_dtypes(include="object").columns
    df[obj_cols] = df[obj_cols].astype(str)
    # Ordenar columnas y filas
    df = df[sorted(df.columns)]
    df = df.sort_values(by=list(df.columns)).reset_index(drop=True)
    return df


def validate_equivalence(
    qid: str,
    pandas_result: pd.DataFrame,
    duckdb_result: pd.DataFrame,
    polars_result: pd.DataFrame,
) -> dict:
    """
    Valida que los tres engines producen resultados numéricamente equivalentes.
    Retorna un dict con el resultado de la validación.
    """
    try:
        p = normalize(pandas_result)
        d = normalize(duckdb_result)
        po = normalize(polars_result)

        pd_match = p.equals(d)
        pp_match = p.equals(po)

        # Si las formas difieren, comparar con tolerancia numérica
        if not pd_match and p.shape == d.shape:
            num_cols = p.select_dtypes(include="number").columns
            pd_match = all(
                np.allclose(p[c], d[c], atol=0.01, rtol=1e-3)
                for c in num_cols if c in d.columns
            )
        if not pp_match and p.shape == po.shape:
            num_cols = p.select_dtypes(include="number").columns
            pp_match = all(
                np.allclose(p[c], po[c], atol=0.01, rtol=1e-3)
                for c in num_cols if c in po.columns
            )

        status = "OK" if (pd_match and pp_match) else "MISMATCH"
        return {
            "status": status,
            "pandas_vs_duckdb": pd_match,
            "pandas_vs_polars": pp_match,
            "rows_pandas": len(pandas_result),
            "rows_duckdb": len(duckdb_result),
            "rows_polars": len(polars_result),
        }
    except Exception as e:
        return {"status": f"ERROR: {e}", "pandas_vs_duckdb": False, "pandas_vs_polars": False}


# ─── Runner principal ─────────────────────────────────────────────────────────

def run_benchmark(parquet_path: Path, output_dir: Path) -> list[dict]:
    print(f"\nCargando dataset pandas desde {parquet_path}...")
    df_pandas = pd.read_parquet(parquet_path)
    print(f"Dataset: {len(df_pandas):,} filas × {len(df_pandas.columns)} columnas\n")

    results = []

    for qid, description in QUERIES.items():
        print(f"{'─'*60}")
        print(f"{qid} — {description}")

        # pandas (recibe DataFrame)
        print(f"  pandas  ...", end=" ", flush=True)
        p_result, p_time, p_mem = measure(PANDAS_FNS[qid], df_pandas)
        print(f"{p_time:.4f}s | {p_mem:.1f} MB")

        # duckdb (recibe ruta al parquet)
        print(f"  duckdb  ...", end=" ", flush=True)
        d_result, d_time, d_mem = measure(DUCKDB_FNS[qid], parquet_path)
        print(f"{d_time:.4f}s | {d_mem:.1f} MB")

        # polars (recibe ruta al parquet)
        print(f"  polars  ...", end=" ", flush=True)
        po_result, po_time, po_mem = measure(POLARS_FNS[qid], parquet_path)
        print(f"{po_time:.4f}s | {po_mem:.1f} MB")

        # validación
        validation = validate_equivalence(qid, p_result, d_result, po_result)
        status_icon = "✅" if validation["status"] == "OK" else "❌"
        print(f"  Equivalencia: {status_icon} {validation['status']}")

        results.append({
            "query_id":    qid,
            "description": description,
            "pandas":  {"time_s": p_time,  "peak_mb": p_mem},
            "duckdb":  {"time_s": d_time,  "peak_mb": d_mem},
            "polars":  {"time_s": po_time, "peak_mb": po_mem},
            "validation":  validation,
            "winner": min(
                [("pandas", p_time), ("duckdb", d_time), ("polars", po_time)],
                key=lambda x: x[1]
            )[0],
        })

    # EXPLAIN ANALYZE para Q3, Q5, Q6
    print(f"\n{'─'*60}")
    print("Generando EXPLAIN ANALYZE para Q3, Q5, Q6...")
    explains = {
        "Q3": de.explain_q3(parquet_path),
        "Q5": de.explain_q5(parquet_path),
        "Q6": de.explain_q6(parquet_path),
    }

    # Guardar resultados
    output_path = output_dir / "benchmark_results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({"queries": results, "explain_analyze": explains}, f, indent=2, ensure_ascii=False)
    print(f"\nResultados guardados en: {output_path}")

    # Tabla resumen
    print(f"\n{'═'*72}")
    print(f"{'Query':<6} {'Descripción':<35} {'Pandas(s)':>10} {'DuckDB(s)':>10} {'Polars(s)':>10} {'Ganador':<8}")
    print(f"{'─'*72}")
    for r in results:
        print(
            f"{r['query_id']:<6} "
            f"{r['description'][:34]:<35} "
            f"{r['pandas']['time_s']:>10.4f} "
            f"{r['duckdb']['time_s']:>10.4f} "
            f"{r['polars']['time_s']:>10.4f} "
            f"{r['winner']:<8}"
        )
    print(f"{'═'*72}")

    return results


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Benchmark de query engines.")
    parser.add_argument(
        "--parquet",
        type=Path,
        default=PROJECT_DIR.parent / "ejercicio-01-formatos" / "data" / "transactions_1m.parquet_snappy.parquet",
        help="Ruta al archivo Parquet de 1M transacciones.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=RESULTS_DIR,
        help="Carpeta donde guardar los resultados JSON.",
    )
    args = parser.parse_args()

    if not args.parquet.exists():
        # Intentar encontrar cualquier parquet de 1m disponible
        candidates = list((PROJECT_DIR.parent / "ejercicio-01-formatos" / "data").glob("*1m*.parquet"))
        if candidates:
            args.parquet = candidates[0]
            print(f"Usando: {args.parquet}")
        else:
            print(f"ERROR: No se encontró el archivo Parquet en {args.parquet}")
            print("Genera primero el dataset con: python ../ejercicio-01-formatos/generate_data.py --size 1m")
            print("Y corre el benchmark de formatos para generar el Parquet.")
            sys.exit(1)

    args.output.mkdir(exist_ok=True)
    run_benchmark(args.parquet, args.output)


if __name__ == "__main__":
    main()
