# Ejercicio 3 — La Capa Transaccional

## Requisitos

- Python 3.11+
- uv instalado (`curl -Lsf https://astral.sh/uv/install.sh | sh`)
- Dataset de 1M transacciones del Ejercicio 1 (CSV y Parquet Snappy)

## Regenerar la base desde cero — comando único

```bash
uv run python ingest.py \
  --csv ../ejercicio-01-formatos/data/transactions_1m_csv.csv \
  --chunk-size 25000 \
  --wal
```

Esto elimina cualquier `.db` existente, crea la base desde cero, aplica el schema con índices y carga 1M de registros en menos de 3 minutos.

## Correr el benchmark completo

```bash
# 1. Ingesta con WAL (recomendado, más rápido)
uv run python ingest.py --csv ../ejercicio-01-formatos/data/transactions_1m_csv.csv --wal

# 2. Ingesta sin WAL (para comparación)
uv run python ingest.py --csv ../ejercicio-01-formatos/data/transactions_1m_csv.csv --no-wal

# 3. Benchmark de los 5 patrones
uv run python benchmark_queries.py
```

## Variables de entorno / rutas configurables

| Argumento | Default | Descripción |
|---|---|---|
| `--csv` | requerido | Ruta al CSV de transacciones |
| `--chunk-size` | 25000 | Filas por transacción SQLite |
| `--wal` / `--no-wal` | `--wal` | Modo de journaling |
| `--db` | `data/transactions.db` | Ruta de salida de la DB |
| `--parquet` | `../ejercicio-01-formatos/data/transactions_1m_parquet_snappy.parquet` | Parquet para DuckDB |

## Diagrama de arquitectura

```
CSV (E1)                    Parquet Snappy (E1)
    │                               │
    ▼                               ▼
ingest.py                   benchmark_queries.py
    │                               │
    │  chunks de 25k filas          │  DuckDB (OLAP)
    │  BEGIN / executemany /        │  read_parquet() directo
    │  COMMIT por chunk             │
    ▼                               │
transactions.db ◄───────────────────┘
    │                               │
    │  PRIMARY KEY (transaction_id) │
    │  idx_user_timestamp           │
    │  idx_country_user             │
    ▼                               ▼
benchmark_queries.py ──► results/benchmark_queries.json
    │
    ├── P1: búsqueda por ID exacto      (<10ms)
    ├── P2: últimas 20 tx por usuario   (<50ms)
    ├── P3: tx por usuario en fechas    (<50ms)
    ├── P4: suma amount último mes      (<50ms)
    └── P5: usuarios activos por país   (<200ms)
```

## Archivos que NO se suben al repo

```
data/           ← .db, .csv, .parquet (en .gitignore)
```

## Archivos que SÍ se suben al repo

```
schema.sql
schema_design.md
ingest.py
benchmark_queries.py
results/ingest_wal_chunk25000.json
results/ingest_no_wal_chunk25000.json
results/benchmark_queries.json
README.md
```
