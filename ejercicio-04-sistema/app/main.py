"""
main.py — API principal del sistema de transacciones.

Arquitectura dual:
  - DuckDB  → endpoints analíticos (/analytics/*)
  - SQLite  → endpoints transaccionales (/users/*, /transactions/batch)

Las conexiones se abren en el lifespan y se reutilizan en todos los requests.
El cache con TTL cubre los endpoints analíticos.

Variables de entorno:
  PARQUET_PATH   ruta al Parquet de 1M transacciones (E1)
  SQLITE_PATH    ruta a la base SQLite (E3)
  CACHE_TTL_SUMMARY      TTL en segundos para /analytics/summary (default: 300)
  CACHE_TTL_MERCHANTS    TTL en segundos para /analytics/top-merchants (default: 300)
"""

import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request

from .cache import TTLCache, CACHE_TTL
from .db import DatabaseConnections, DEFAULT_PARQUET, DEFAULT_DB
from .models import (
    BatchRequest, BatchResponse,
    HealthResponse,
    SummaryResponse, CountryBreakdown, CategoryBreakdown,
    TopMerchantsResponse, MerchantEntry,
    UserTransactionsResponse, TransactionOut,
    UserStatsResponse,
)

# ─── Startup / shutdown ───────────────────────────────────────────────────────

_start_time: float = 0.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _start_time
    _start_time = time.monotonic()

    parquet_path = Path(os.getenv("PARQUET_PATH", str(DEFAULT_PARQUET)))
    db_path      = Path(os.getenv("SQLITE_PATH",  str(DEFAULT_DB)))

    # Auto-detectar Parquet si la ruta por defecto no existe
    if not parquet_path.exists():
        candidates = list(Path(".").glob("**/*1m*snappy*.parquet"))
        if not candidates:
            candidates = list(Path(".").glob("**/*1m*.parquet"))
        if candidates:
            parquet_path = candidates[0]
            print(f"Parquet detectado: {parquet_path}")
        else:
            raise RuntimeError(f"No se encontró el Parquet en {parquet_path}")

    if not db_path.exists():
        raise RuntimeError(f"No se encontró la base SQLite en {db_path}")

    # Inicializar conexiones
    app.state.db = DatabaseConnections(parquet_path, db_path)
    app.state.db.open()
    print(f"DuckDB conectado → {parquet_path}")
    print(f"SQLite conectado → {db_path}")

    # Inicializar cache
    ttl_summary   = int(os.getenv("CACHE_TTL_SUMMARY",   CACHE_TTL["summary"]))
    ttl_merchants = int(os.getenv("CACHE_TTL_MERCHANTS",  CACHE_TTL["top_merchants"]))
    app.state.cache           = TTLCache(default_ttl=ttl_summary)
    app.state.ttl_summary     = ttl_summary
    app.state.ttl_merchants   = ttl_merchants

    yield

    # Shutdown
    app.state.db.close()
    print("Conexiones cerradas.")


app = FastAPI(
    title="Sistema de Transacciones",
    description="API dual DuckDB (analytics) + SQLite (transaccional)",
    version="1.0.0",
    lifespan=lifespan,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def get_db(request: Request) -> DatabaseConnections:
    return request.app.state.db


def get_cache(request: Request) -> TTLCache:
    return request.app.state.cache


# ─── GET /health ─────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
def health(request: Request):
    """Estado del sistema: uptime, hit rate del cache, conexiones activas."""
    cache = get_cache(request)
    return HealthResponse(
        status         = "ok",
        uptime_seconds = round(time.monotonic() - _start_time, 2),
        cache_hit_rate = cache.hit_rate,
        cache_hits     = cache.hits,
        cache_misses   = cache.misses,
    )


# ─── GET /analytics/summary ──────────────────────────────────────────────────

@app.get("/analytics/summary", response_model=SummaryResponse)
def analytics_summary(request: Request):
    """
    Totales globales: conteo, monto total, promedio,
    breakdown por país y por categoría.

    Backend: DuckDB — query analítica sobre 1M filas, ideal para motor columnar.
    Cache: 5 minutos — los datos históricos no cambian entre requests.
    """
    cache = get_cache(request)
    cached = cache.get("summary")
    if cached:
        return cached

    db  = get_db(request)
    p   = str(db.parquet_path)

    # Query 1: totales globales
    row = db.duck.execute(f"""
        SELECT
            COUNT(*)        AS total_transactions,
            SUM(amount)     AS total_amount,
            AVG(amount)     AS avg_amount
        FROM read_parquet('{p}')
    """).fetchone()

    # Query 2: breakdown por país
    countries = db.duck.execute(f"""
        SELECT
            country_code,
            COUNT(*)    AS total_transactions,
            SUM(amount) AS total_amount
        FROM read_parquet('{p}')
        GROUP BY country_code
        ORDER BY total_transactions DESC
    """).fetchall()

    # Query 3: breakdown por categoría
    categories = db.duck.execute(f"""
        SELECT
            category,
            SUM(amount) AS total_amount,
            AVG(amount) AS avg_amount
        FROM read_parquet('{p}')
        GROUP BY category
        ORDER BY total_amount DESC
    """).fetchall()

    result = SummaryResponse(
        total_transactions = row[0],
        total_amount       = round(row[1], 2),
        avg_amount         = round(row[2], 2),
        by_country  = [CountryBreakdown(
            country_code=r[0],
            total_transactions=r[1],
            total_amount=round(r[2], 2),
        ) for r in countries],
        by_category = [CategoryBreakdown(
            category=r[0],
            total_amount=round(r[1], 2),
            avg_amount=round(r[2], 2),
        ) for r in categories],
    )

    cache.set("summary", result, ttl=request.app.state.ttl_summary)
    return result


# ─── GET /analytics/top-merchants ────────────────────────────────────────────

@app.get("/analytics/top-merchants", response_model=TopMerchantsResponse)
def top_merchants(
    request: Request,
    limit:   int           = Query(default=10, ge=1, le=100),
    country: Optional[str] = Query(default=None, min_length=2, max_length=2),
):
    """
    Top N merchants por volumen de transacciones.
    Filtro opcional por country_code.

    Backend: DuckDB — agregación analítica sobre dataset completo.
    Cache: 5 minutos, clave incluye limit y country para no mezclar resultados.
    """
    cache     = get_cache(request)
    cache_key = f"top_merchants:{limit}:{country or 'all'}"
    cached    = cache.get(cache_key)
    if cached:
        return cached

    db  = get_db(request)
    p   = str(db.parquet_path)
    where = f"WHERE country_code = '{country.upper()}'" if country else ""

    rows = db.duck.execute(f"""
        SELECT
            merchant_id,
            SUM(amount) AS total_amount,
            COUNT(*)    AS total_transactions
        FROM read_parquet('{p}')
        {where}
        GROUP BY merchant_id
        ORDER BY total_amount DESC
        LIMIT {limit}
    """).fetchall()

    result = TopMerchantsResponse(
        merchants=[MerchantEntry(
            merchant_id=r[0],
            total_amount=round(r[1], 2),
            total_transactions=r[2],
        ) for r in rows],
        limit=limit,
        country=country,
    )

    cache.set(cache_key, result, ttl=request.app.state.ttl_merchants)
    return result


# ─── GET /users/{user_id}/transactions ───────────────────────────────────────

@app.get("/users/{user_id}/transactions", response_model=UserTransactionsResponse)
def user_transactions(
    request:   Request,
    user_id:   int,
    page:      int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    """
    Últimas transacciones de un usuario, paginadas.

    Backend: SQLite — lookup por user_id con índice, respuesta < 80ms.
    Sin cache — datos transaccionales que pueden cambiar con cada POST /batch.
    """
    db     = get_db(request)
    offset = (page - 1) * page_size

    rows = db.sqlite.execute("""
        SELECT transaction_id, timestamp, user_id, merchant_id,
               amount, category, country_code, status
        FROM transactions
        WHERE user_id = ?
        ORDER BY timestamp DESC
        LIMIT ? OFFSET ?
    """, (user_id, page_size, offset)).fetchall()

    if not rows and page == 1:
        raise HTTPException(status_code=404, detail=f"Usuario {user_id} no encontrado.")

    return UserTransactionsResponse(
        user_id      = user_id,
        page         = page,
        page_size    = page_size,
        transactions = [TransactionOut(**dict(r)) for r in rows],
    )


# ─── GET /users/{user_id}/stats ──────────────────────────────────────────────

@app.get("/users/{user_id}/stats", response_model=UserStatsResponse)
def user_stats(request: Request, user_id: int):
    """
    Estadísticas del usuario: monto total, conteo, categoría más frecuente y país.

    Backend: SQLite — aggregación sobre las filas de un usuario específico,
    aprovecha idx_user_timestamp para acceso rápido.
    Sin cache — datos transaccionales que pueden actualizarse.
    """
    db = get_db(request)

    row = db.sqlite.execute("""
        SELECT
            SUM(amount)  AS total_amount,
            COUNT(*)     AS transaction_count,
            country_code
        FROM transactions
        WHERE user_id = ?
        GROUP BY country_code
        ORDER BY transaction_count DESC
        LIMIT 1
    """, (user_id,)).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail=f"Usuario {user_id} no encontrado.")

    top_cat = db.sqlite.execute("""
        SELECT category, COUNT(*) AS cnt
        FROM transactions
        WHERE user_id = ?
        GROUP BY category
        ORDER BY cnt DESC
        LIMIT 1
    """, (user_id,)).fetchone()

    return UserStatsResponse(
        user_id           = user_id,
        total_amount      = round(row["total_amount"], 2),
        transaction_count = row["transaction_count"],
        top_category      = top_cat["category"] if top_cat else "N/A",
        country_code      = row["country_code"],
    )


# ─── POST /transactions/batch ─────────────────────────────────────────────────

@app.post("/transactions/batch", response_model=BatchResponse, status_code=201)
def transactions_batch(request: Request, body: BatchRequest):
    """
    Inserta hasta 500 transacciones. Valida schema con Pydantic (HTTP 422 si inválido),
    deduplica por transaction_id, inserta en SQLite.

    Backend: SQLite — escrituras transaccionales con INSERT OR IGNORE para deduplicación.
    Invalida el cache de analytics después de insertar para forzar recálculo.
    """
    db    = get_db(request)
    cache = get_cache(request)

    existing_ids = {
        row[0] for row in db.sqlite.execute(
            f"SELECT transaction_id FROM transactions WHERE transaction_id IN "
            f"({','.join('?' * len(body.transactions))})",
            [t.transaction_id for t in body.transactions],
        ).fetchall()
    }

    to_insert  = [t for t in body.transactions if t.transaction_id not in existing_ids]
    duplicates = len(body.transactions) - len(to_insert)

    if to_insert:
        rows = [
            (
                t.transaction_id,
                t.timestamp.isoformat(sep=" "),
                t.user_id,
                t.merchant_id,
                t.amount,
                t.category,
                t.country_code.upper(),
                t.status,
            )
            for t in to_insert
        ]
        db.sqlite.execute("BEGIN")
        db.sqlite.executemany("""
            INSERT OR IGNORE INTO transactions
                (transaction_id, timestamp, user_id, merchant_id,
                 amount, category, country_code, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
        db.sqlite.execute("COMMIT")

        # Invalidar cache de analytics — los datos cambiaron
        cache.invalidate("summary")

    return BatchResponse(
        inserted       = len(to_insert),
        duplicates     = duplicates,
        invalid        = 0,
        total_received = len(body.transactions),
    )
