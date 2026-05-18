"""
ingest.py — Ingesta del dataset de transacciones en SQLite.

Uso:
    uv run python ingest.py --csv ../ejercicio-01-formatos/data/transactions_1m.csv
    uv run python ingest.py --csv data/transactions_1m.csv --chunk-size 50000 --wal
    uv run python ingest.py --csv data/transactions_1m.csv --chunk-size 10000 --no-wal

La ingesta usa transacciones explícitas: un BEGIN/COMMIT por chunk.
Esto es significativamente más rápido que autocommit (un commit por fila)
porque SQLite sincroniza el disco en cada commit.
"""

import argparse
import json
import sqlite3
import time
from pathlib import Path

import pandas as pd

PROJECT_DIR = Path(__file__).parent
DB_PATH     = PROJECT_DIR / "data" / "transactions.db"
SCHEMA_PATH = PROJECT_DIR / "schema.sql"
RESULTS_DIR = PROJECT_DIR / "results"


# ─── Helpers ─────────────────────────────────────────────────────────────────

def get_connection(db_path: Path, wal: bool) -> sqlite3.Connection:
    """
    Abre (o crea) la base de datos y configura el modo de journaling.
    isolation_level=None activa el modo autocommit de Python —
    manejamos las transacciones manualmente con BEGIN/COMMIT explícitos.
    """
    db_path.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(db_path, isolation_level=None)
    con.execute("PRAGMA synchronous = NORMAL")   # balance entre seguridad y velocidad
    con.execute("PRAGMA cache_size = -64000")    # 64MB de cache en memoria
    if wal:
        con.execute("PRAGMA journal_mode = WAL")
    else:
        con.execute("PRAGMA journal_mode = DELETE")
    return con


def apply_schema(con: sqlite3.Connection) -> None:
    """Crea la tabla e índices leyendo schema.sql."""
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    con.executescript(schema)


def ingest_chunk(con: sqlite3.Connection, chunk: pd.DataFrame) -> None:
    """
    Inserta un chunk de filas dentro de una transacción explícita.
    OR IGNORE descarta duplicados por transaction_id sin error.
    """
    rows = [
        (
            row.transaction_id,
            str(row.timestamp),   # ISO 8601 como TEXT
            int(row.user_id),
            int(row.merchant_id),
            float(row.amount),
            row.category,
            row.country_code,
            row.status,
        )
        for row in chunk.itertuples(index=False)
    ]
    con.execute("BEGIN")
    con.executemany(
        """
        INSERT OR IGNORE INTO transactions
            (transaction_id, timestamp, user_id, merchant_id,
             amount, category, country_code, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    con.execute("COMMIT")


# ─── Runner principal ─────────────────────────────────────────────────────────

def run_ingest(csv_path: Path, chunk_size: int, wal: bool, db_path: Path) -> dict:
    """
    Lee el CSV en chunks y los inserta en SQLite.
    Retorna un dict con métricas de la ingesta.
    """
    mode = "WAL" if wal else "DELETE"
    print(f"\nIngesta — modo: {mode} | chunk-size: {chunk_size:,}")
    print(f"Fuente: {csv_path}")
    print(f"Destino: {db_path}\n")

    # Eliminar DB anterior si existe
    if db_path.exists():
        db_path.unlink()

    con = get_connection(db_path, wal)
    apply_schema(con)

    total_rows   = 0
    chunk_times  = []
    t_start      = time.perf_counter()

    reader = pd.read_csv(csv_path, chunksize=chunk_size)
    for i, chunk in enumerate(reader):
        t0 = time.perf_counter()
        ingest_chunk(con, chunk)
        chunk_times.append(time.perf_counter() - t0)
        total_rows += len(chunk)

        if (i + 1) % 5 == 0:
            elapsed = time.perf_counter() - t_start
            rate = total_rows / elapsed
            print(f"  chunk {i+1:>4} | {total_rows:>10,} filas | {elapsed:.1f}s | {rate:,.0f} filas/s")

    total_time = time.perf_counter() - t_start
    con.close()

    db_size_mb = db_path.stat().st_size / (1024 ** 2)

    result = {
        "mode":         mode,
        "chunk_size":   chunk_size,
        "total_rows":   total_rows,
        "total_time_s": round(total_time, 3),
        "rows_per_sec": round(total_rows / total_time),
        "db_size_mb":   round(db_size_mb, 2),
        "avg_chunk_s":  round(sum(chunk_times) / len(chunk_times), 4),
        "max_chunk_s":  round(max(chunk_times), 4),
    }

    print(f"\n{'─'*50}")
    print(f"Total filas:   {total_rows:,}")
    print(f"Tiempo total:  {total_time:.2f}s")
    print(f"Throughput:    {result['rows_per_sec']:,} filas/s")
    print(f"Tamaño DB:     {db_size_mb:.1f} MB")
    print(f"{'─'*50}")

    if total_time > 180:
        print("⚠️  ADVERTENCIA: La ingesta superó los 3 minutos.")
    else:
        print(f"✅ Ingesta completada en {total_time:.1f}s (límite: 180s)")

    return result


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Ingesta de transacciones CSV en SQLite.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python ingest.py --csv ../ejercicio-01-formatos/data/transactions_1m.csv --wal
  python ingest.py --csv data/transactions_1m.csv --chunk-size 50000 --no-wal
        """,
    )
    parser.add_argument(
        "--csv", type=Path, required=True,
        help="Ruta al archivo CSV de transacciones.",
    )
    parser.add_argument(
        "--chunk-size", type=int, default=25000,
        help="Filas por chunk / transacción (default: 25000).",
    )
    parser.add_argument(
        "--db", type=Path, default=DB_PATH,
        help=f"Ruta de salida para la base de datos (default: {DB_PATH}).",
    )

    # --wal / --no-wal mutuamente excluyentes, default: WAL
    wal_group = parser.add_mutually_exclusive_group()
    wal_group.add_argument("--wal",    dest="wal", action="store_true",  default=True,
                           help="Usar WAL mode (default).")
    wal_group.add_argument("--no-wal", dest="wal", action="store_false",
                           help="Usar DELETE mode (journaling clásico).")

    args = parser.parse_args()

    if not args.csv.exists():
        # Intentar encontrar el CSV de 1M automáticamente
        candidates = list(Path("../ejercicio-01-formatos/data").glob("*1m*.csv"))
        if not candidates:
            candidates = list(Path(".").glob("**/*1m*.csv"))
        if candidates:
            args.csv = candidates[0]
            print(f"CSV no especificado. Usando: {args.csv}")
        else:
            print(f"ERROR: No se encontró el CSV en {args.csv}")
            raise SystemExit(1)

    RESULTS_DIR.mkdir(exist_ok=True)
    result = run_ingest(args.csv, args.chunk_size, args.wal, args.db)

    # Guardar resultado
    mode_label = "wal" if args.wal else "no_wal"
    out = RESULTS_DIR / f"ingest_{mode_label}_chunk{args.chunk_size}.json"
    with open(out, "w") as f:
        json.dump(result, f, indent=2)
    print(f"Resultado guardado en: {out}")


if __name__ == "__main__":
    main()
