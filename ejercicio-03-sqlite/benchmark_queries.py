"""
benchmark_queries.py — Benchmark de los 5 patrones de acceso.

Mide cada patrón:
  - Con índices (schema normal)
  - Sin índices (drop temporal de índices)
  - Contra DuckDB sobre el Parquet del E1

Captura EXPLAIN QUERY PLAN para cada caso y verifica SLAs.

Uso:
    uv run python benchmark_queries.py
    uv run python benchmark_queries.py --db data/transactions.db --parquet ../ejercicio-01-formatos/data/transactions_1m_parquet_snappy.parquet
"""

import argparse
import json
import sqlite3
import time
import tracemalloc
from pathlib import Path
from statistics import mean

import duckdb
import pandas as pd

PROJECT_DIR = Path(__file__).parent
DB_PATH     = PROJECT_DIR / "data" / "transactions.db"
RESULTS_DIR = PROJECT_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)

REPEATS = 3  # repeticiones por medición, promedio reportado

# SLAs en segundos
SLA = {
    "P1": 0.010,
    "P2": 0.050,
    "P3": 0.050,
    "P4": 0.050,
    "P5": 0.200,
}

PATTERN_DESCRIPTIONS = {
    "P1": "Búsqueda por transaction_id exacto",
    "P2": "Últimas 20 tx de un user_id",
    "P3": "Tx de un user_id en rango de fechas",
    "P4": "Suma de amount de un user_id, último mes",
    "P5": "user_ids de un country_code con > N tx",
}


# ─── Helpers de medición ─────────────────────────────────────────────────────

def measure_sqlite(con: sqlite3.Connection, sql: str, params: tuple = ()) -> tuple[float, float]:
    """
    Ejecuta sql con params REPEATS veces.
    Retorna (tiempo_promedio_s, peak_mb_primera_ejecucion).
    """
    times = []
    peak_mb = 0.0
    for i in range(REPEATS):
        tracemalloc.start()
        t0 = time.perf_counter()
        con.execute(sql, params).fetchall()
        elapsed = time.perf_counter() - t0
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        times.append(elapsed)
        if i == 0:
            peak_mb = peak / (1024 ** 2)
    return round(mean(times), 6), round(peak_mb, 3)


def measure_duckdb(parquet_path: Path, sql: str) -> tuple[float, float]:
    """
    Ejecuta sql en DuckDB REPEATS veces.
    Retorna (tiempo_promedio_s, peak_mb_primera_ejecucion).
    """
    times = []
    peak_mb = 0.0
    con = duckdb.connect()
    for i in range(REPEATS):
        tracemalloc.start()
        t0 = time.perf_counter()
        con.execute(sql).fetchall()
        elapsed = time.perf_counter() - t0
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        times.append(elapsed)
        if i == 0:
            peak_mb = peak / (1024 ** 2)
    con.close()
    return round(mean(times), 6), round(peak_mb, 3)


def get_explain(con: sqlite3.Connection, sql: str, params: tuple = ()) -> str:
    """Retorna el EXPLAIN QUERY PLAN como string legible."""
    rows = con.execute(f"EXPLAIN QUERY PLAN {sql}", params).fetchall()
    return "\n".join(f"{'  ' * r[1]}{r[3]}" for r in rows)


def drop_secondary_indexes(con: sqlite3.Connection) -> None:
    """Elimina los índices secundarios (no el PRIMARY KEY)."""
    con.execute("DROP INDEX IF EXISTS idx_user_timestamp")
    con.execute("DROP INDEX IF EXISTS idx_country_user")


def recreate_indexes(con: sqlite3.Connection) -> None:
    """Recrea los índices secundarios."""
    schema = (PROJECT_DIR / "schema.sql").read_text()
    for stmt in schema.split(";"):
        stmt = stmt.strip()
        if stmt.upper().startswith("CREATE INDEX"):
            con.execute(stmt)


# ─── Obtener valores de ejemplo del dataset ───────────────────────────────────

def get_sample_values(con: sqlite3.Connection) -> dict:
    """Obtiene valores representativos para usar en los benchmarks."""
    tx_id = con.execute(
        "SELECT transaction_id FROM transactions LIMIT 1"
    ).fetchone()[0]

    # user_id con más transacciones (para que el índice sea claramente útil)
    user_id = con.execute(
        "SELECT user_id FROM transactions GROUP BY user_id ORDER BY COUNT(*) DESC LIMIT 1"
    ).fetchone()[0]

    # Timestamps COMPLETOS (con microsegundos) para que BETWEEN use el índice
    dates = con.execute(
        "SELECT MIN(timestamp), MAX(timestamp) FROM transactions WHERE user_id = ?",
        (user_id,)
    ).fetchone()
    date_start = dates[0]   # timestamp completo: 'YYYY-MM-DD HH:MM:SS.ffffff'
    date_end   = dates[1]

    # Cutoff para P4: timestamp completo 30 días antes del máximo global
    max_ts = con.execute("SELECT MAX(timestamp) FROM transactions").fetchone()[0]
    # Calculamos 30 días antes usando SQLite
    cutoff = con.execute(
        "SELECT datetime(?, '-30 days')", (max_ts,)
    ).fetchone()[0]

    country = con.execute(
        "SELECT country_code FROM transactions GROUP BY country_code ORDER BY COUNT(*) DESC LIMIT 1"
    ).fetchone()[0]

    return {
        "transaction_id": tx_id,
        "user_id":        user_id,
        "date_start":     date_start,
        "date_end":       date_end,
        "cutoff_date":    cutoff,
        "country_code":   country,
        "min_tx_count":   5,
    }


# ─── Queries por patrón ───────────────────────────────────────────────────────

def build_queries(v: dict, parquet_path: Path) -> dict:
    """
    Retorna las queries SQLite y DuckDB para cada patrón.
    v = valores de ejemplo obtenidos del dataset real.
    """
    p = str(parquet_path)
    return {
        "P1": {
            "sqlite": (
                "SELECT * FROM transactions WHERE transaction_id = ?",
                (v["transaction_id"],)
            ),
            "duckdb": (
                f"SELECT * FROM read_parquet('{p}') WHERE transaction_id = '{v['transaction_id']}'",
                ()
            ),
        },
        "P2": {
            "sqlite": (
                "SELECT * FROM transactions WHERE user_id = ? ORDER BY timestamp DESC LIMIT 20",
                (v["user_id"],)
            ),
            "duckdb": (
                f"SELECT * FROM read_parquet('{p}') WHERE user_id = {v['user_id']} ORDER BY timestamp DESC LIMIT 20",
                ()
            ),
        },
        "P3": {
            "sqlite": (
                "SELECT * FROM transactions WHERE user_id = ? AND timestamp BETWEEN ? AND ?",
                (v["user_id"], v["date_start"], v["date_end"])
            ),
            "duckdb": (
                f"SELECT * FROM read_parquet('{p}') WHERE user_id = {v['user_id']} AND timestamp BETWEEN '{v['date_start']}' AND '{v['date_end']}'",
                ()
            ),
        },
        "P4": {
            "sqlite": (
                """SELECT SUM(amount) FROM transactions
                   WHERE user_id = ?
                   AND timestamp >= date(?, '-30 days')""",
                (v["user_id"], v["cutoff_date"])
            ),
            "duckdb": (
                f"""SELECT SUM(amount) FROM read_parquet('{p}')
                    WHERE user_id = {v['user_id']}
                    AND timestamp >= (DATE '{v['cutoff_date']}' - INTERVAL '30 days')""",
                ()
            ),
        },
        "P5": {
            "sqlite": (
                """SELECT user_id, COUNT(*) as tx_count
                   FROM transactions
                   WHERE country_code = ?
                   GROUP BY user_id
                   HAVING tx_count > ?
                   ORDER BY tx_count DESC""",
                (v["country_code"], v["min_tx_count"])
            ),
            "duckdb": (
                f"""SELECT user_id, COUNT(*) as tx_count
                    FROM read_parquet('{p}')
                    WHERE country_code = '{v['country_code']}'
                    GROUP BY user_id
                    HAVING tx_count > {v['min_tx_count']}
                    ORDER BY tx_count DESC""",
                ()
            ),
        },
    }


# ─── Runner principal ─────────────────────────────────────────────────────────

def run_benchmark(db_path: Path, parquet_path: Path) -> list[dict]:
    print(f"\nConectando a SQLite: {db_path}")
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA cache_size = -64000")

    print("Obteniendo valores de ejemplo del dataset...")
    v = get_sample_values(con)
    print(f"  user_id: {v['user_id']} | country: {v['country_code']} | tx_id: {v['transaction_id'][:20]}...")

    queries = build_queries(v, parquet_path)
    results = []

    for pid, desc in PATTERN_DESCRIPTIONS.items():
        q = queries[pid]
        sql_sqlite, params = q["sqlite"]
        sql_duckdb, _      = q["duckdb"]

        print(f"\n{'─'*60}")
        print(f"{pid} — {desc}")

        # 1. EXPLAIN con índices
        explain_with = get_explain(con, sql_sqlite, params)

        # 2. Medir CON índices
        t_with, mem_with = measure_sqlite(con, sql_sqlite, params)
        sla_ok = t_with <= SLA[pid]
        sla_icon = "✅" if sla_ok else "❌"
        print(f"  SQLite CON índices:  {t_with*1000:7.2f}ms | {mem_with:.2f}MB {sla_icon} SLA={SLA[pid]*1000:.0f}ms")

        # 3. Drop índices secundarios y medir SIN índices
        drop_secondary_indexes(con)
        explain_without = get_explain(con, sql_sqlite, params)
        t_without, mem_without = measure_sqlite(con, sql_sqlite, params)
        print(f"  SQLite SIN índices:  {t_without*1000:7.2f}ms | {mem_without:.2f}MB")

        # 4. Recrear índices para el siguiente patrón
        recreate_indexes(con)

        # 5. DuckDB
        t_duck, mem_duck = measure_duckdb(parquet_path, sql_duckdb)
        winner = "SQLite" if t_with < t_duck else "DuckDB"
        print(f"  DuckDB (Parquet):    {t_duck*1000:7.2f}ms | {mem_duck:.2f}MB → ganador: {winner}")

        results.append({
            "pattern":        pid,
            "description":    desc,
            "sla_ms":         SLA[pid] * 1000,
            "sqlite_with_idx": {
                "time_ms":    round(t_with * 1000, 3),
                "peak_mb":    mem_with,
                "sla_ok":     sla_ok,
                "explain":    explain_with,
            },
            "sqlite_no_idx": {
                "time_ms":    round(t_without * 1000, 3),
                "peak_mb":    mem_without,
                "explain":    explain_without,
            },
            "duckdb": {
                "time_ms":    round(t_duck * 1000, 3),
                "peak_mb":    mem_duck,
            },
            "winner":         winner,
            "speedup_vs_no_idx": round(t_without / t_with, 1) if t_with > 0 else None,
        })

    con.close()

    # Tabla resumen
    print(f"\n{'═'*70}")
    print(f"{'Patrón':<6} {'SLA(ms)':>8} {'Con idx(ms)':>12} {'Sin idx(ms)':>12} {'DuckDB(ms)':>12} {'Ganador':<8} {'SLA'}")
    print(f"{'─'*70}")
    for r in results:
        sla_icon = "✅" if r["sqlite_with_idx"]["sla_ok"] else "❌"
        print(
            f"{r['pattern']:<6} "
            f"{r['sla_ms']:>8.0f} "
            f"{r['sqlite_with_idx']['time_ms']:>12.2f} "
            f"{r['sqlite_no_idx']['time_ms']:>12.2f} "
            f"{r['duckdb']['time_ms']:>12.2f} "
            f"{r['winner']:<8} "
            f"{sla_icon}"
        )
    print(f"{'═'*70}")

    return results


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Benchmark de patrones de acceso SQLite vs DuckDB.")
    parser.add_argument("--db", type=Path, default=DB_PATH,
                        help=f"Ruta a la base SQLite (default: {DB_PATH})")
    parser.add_argument(
        "--parquet", type=Path,
        default=PROJECT_DIR.parent / "ejercicio-01-formatos" / "data" / "transactions_1m_parquet_snappy.parquet",
        help="Ruta al Parquet de 1M transacciones."
    )
    args = parser.parse_args()

    # Auto-detectar parquet si no existe la ruta por defecto
    if not args.parquet.exists():
        candidates = list((PROJECT_DIR.parent / "ejercicio-01-formatos" / "data").glob("*1m*.parquet"))
        if candidates:
            args.parquet = candidates[0]
            print(f"Usando Parquet: {args.parquet}")
        else:
            print("ERROR: No se encontró el archivo Parquet. Genera el dataset del E1 primero.")
            raise SystemExit(1)

    if not args.db.exists():
        print(f"ERROR: No se encontró la base de datos en {args.db}")
        print("Corre primero: python ingest.py --csv <ruta_csv> --wal")
        raise SystemExit(1)

    results = run_benchmark(args.db, args.parquet)

    out = RESULTS_DIR / "benchmark_queries.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nResultados guardados en: {out}")


if __name__ == "__main__":
    main()
