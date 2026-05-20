# Ejercicio 4 — El Sistema Completo

## Requisitos

- Python 3.11+
- uv instalado
- Dataset del E1: archivo Parquet de 1M transacciones
- Base SQLite del E3: `transactions.db` con 1M registros

## Instalación

```bash
cd mi-modulo-datos
uv sync
```

## Variables de entorno

| Variable | Default | Descripción |
|---|---|---|
| `PARQUET_PATH` | `../ejercicio-01-formatos/data/transactions_1m_parquet_snappy.parquet` | Parquet del E1 |
| `SQLITE_PATH` | `../ejercicio-03-sqlite/data/transactions.db` | Base SQLite del E3 |
| `CACHE_TTL_SUMMARY` | `300` | TTL en segundos para /analytics/summary |
| `CACHE_TTL_MERCHANTS` | `300` | TTL en segundos para /analytics/top-merchants |

## Cómo arrancar el servidor

```bash
cd ejercicio-04-sistema
uv run uvicorn app.main:app --reload --port 8000
```

O con variables de entorno explícitas:

```bash
PARQUET_PATH=../ejercicio-01-formatos/data/transactions_1m_parquet_snappy.parquet \
SQLITE_PATH=../ejercicio-03-sqlite/data/transactions.db \
uv run uvicorn app.main:app --port 8000
```

El servidor arranca en http://localhost:8000  
Documentación interactiva: http://localhost:8000/docs

## Correr los tests

```bash
cd ejercicio-04-sistema
uv run pytest tests/test_api.py -v
```

## Endpoints disponibles

```
GET  /health
GET  /analytics/summary
GET  /analytics/top-merchants?limit=10&country=MX
GET  /users/{user_id}/transactions?page=1&page_size=20
GET  /users/{user_id}/stats
POST /transactions/batch
```

## Diagrama de arquitectura

```
                    ┌─────────────────────────────────┐
                    │         FastAPI (main.py)        │
                    │                                  │
                    │  lifespan: abre conexiones       │
                    │  app.state.db    → DatabaseConns │
                    │  app.state.cache → TTLCache      │
                    └──────────────┬──────────────────┘
                                   │
              ┌────────────────────┼───────────────────┐
              │                    │                   │
              ▼                    ▼                   ▼
   ┌─────────────────┐  ┌──────────────────┐  ┌──────────────┐
   │  DuckDB (OLAP)  │  │  SQLite (OLTP)   │  │  TTLCache    │
   │                 │  │                  │  │  (memoria)   │
   │  Parquet Snappy │  │  transactions.db │  │              │
   │  (E1, estático) │  │  (E3, mutable)   │  │  summary     │
   │                 │  │                  │  │  top_merch.  │
   └────────┬────────┘  └────────┬─────────┘  └──────┬───────┘
            │                    │                    │
            ▼                    ▼                    ▼
   /analytics/summary     /users/{id}/          /health
   /analytics/top-merch.  transactions          (hit rate)
                          /users/{id}/stats
                          /transactions/batch
```

## Estructura de archivos

```
ejercicio-04-sistema/
├── app/
│   ├── __init__.py
│   ├── main.py              ← FastAPI, lifespan, 6 endpoints
│   ├── db.py                ← conexiones DuckDB y SQLite
│   ├── cache.py             ← TTLCache con estadísticas
│   └── models.py            ← modelos Pydantic
├── tests/
│   └── test_api.py          ← 14 tests
├── benchmarks/
│   └── latency_report.md    ← p50/p95/p99 cold vs warm
├── architecture_decision.md
└── README.md
```
