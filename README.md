# Módulo — Python para Sistemas de Datos Modernos

## Requisitos

- Python 3.11+
- uv (`curl -Lsf https://astral.sh/uv/install.sh | sh`)

## Instalación

```bash
git clone <url-del-repo>
cd mi-modulo-datos
uv sync
```

---

## Ejercicio 1 — Formatos Bajo la Lupa

Benchmark de formatos de almacenamiento: CSV, JSON Lines y Parquet (sin compresión, Snappy, Gzip) sobre 100k, 500k y 1M registros.

```bash
cd ejercicio-01-formatos

# Generar datos
uv run python generate_data.py --size 1m

# Correr benchmark completo
uv run python benchmark_cli.py --size 1m --formats csv parquet_none parquet_snappy parquet_gzip
```

Resultados en `ejercicio-01-formatos/results/`.

---

## Ejercicio 2 — El Motor de Consultas

Benchmark de 8 queries en 3 engines (pandas, DuckDB, Polars) sobre el Parquet de 1M del E1.

```bash
cd ejercicio-02-consultas

uv run python benchmark.py --parquet ../ejercicio-01-formatos/data/transactions_1m_parquet_snappy.parquet
```

Resultados en `ejercicio-02-consultas/results/`.

---

## Ejercicio 3 — La Capa Transaccional

Base de datos SQLite optimizada para consultas transaccionales por usuario, con benchmark de 5 patrones de acceso comparados contra DuckDB.

```bash
cd ejercicio-03-sqlite

# Generar la base desde cero (comando único)
uv run python ingest.py \
  --csv ../ejercicio-01-formatos/data/transactions_1m_csv.csv \
  --chunk-size 25000 --wal

# Correr benchmark de patrones
uv run python benchmark_queries.py
```

Resultados en `ejercicio-03-sqlite/results/`.

---

## Ejercicio 4 — El Sistema Completo

API FastAPI con 6 endpoints, arquitectura dual DuckDB (analytics) + SQLite (transaccional), cache con TTL y suite de tests.

```bash
cd ejercicio-04-sistema

# Correr tests
uv run pytest tests/test_api.py -v

# Arrancar el servidor
uv run uvicorn app.main:app --port 8000
```

Documentación interactiva: http://localhost:8000/docs  
Reporte de latencia: `ejercicio-04-sistema/benchmarks/latency_report.md`

### Variables de entorno (opcionales)

| Variable | Default |
|---|---|
| `PARQUET_PATH` | `../ejercicio-01-formatos/data/transactions_1m_parquet_snappy.parquet` |
| `SQLITE_PATH` | `../ejercicio-03-sqlite/data/transactions.db` |
| `CACHE_TTL_SUMMARY` | `300` |
| `CACHE_TTL_MERCHANTS` | `300` |

---

## Archivos que NO se suben al repo

```
*/data/          ← .csv, .parquet, .db
*.csv
*.parquet
*.jsonl
*.db
ejercicio-04-sistema/benchmarks/results.json
```
