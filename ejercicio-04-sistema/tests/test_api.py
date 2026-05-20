"""
test_api.py — Suite de tests para la API de transacciones.

Cubre:
  - Happy path de cada endpoint (6 endpoints)
  - Usuario inexistente (404)
  - Batch con schema inválido (422)
  - Paginación fuera de rango
  - Validación de SLA de latencia

Uso:
    uv run pytest tests/test_api.py -v
"""

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Configurar rutas antes de importar la app
import os
PROJECT_DIR = Path(__file__).parent.parent

# Buscar Parquet y SQLite disponibles
def _find_parquet() -> str:
    candidates = list((PROJECT_DIR.parent / "ejercicio-01-formatos" / "data").glob("*1m*snappy*.parquet"))
    if not candidates:
        candidates = list((PROJECT_DIR.parent / "ejercicio-01-formatos" / "data").glob("*1m*.parquet"))
    if candidates:
        return str(candidates[0])
    raise FileNotFoundError("No se encontró el Parquet de 1M. Genera el dataset del E1 primero.")

def _find_sqlite() -> str:
    path = PROJECT_DIR.parent / "ejercicio-03-sqlite" / "data" / "transactions.db"
    if path.exists():
        return str(path)
    raise FileNotFoundError("No se encontró transactions.db. Corre ingest.py del E3 primero.")

os.environ.setdefault("PARQUET_PATH", _find_parquet())
os.environ.setdefault("SQLITE_PATH",  _find_sqlite())

from app.main import app


# ─── Fixture ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    """Cliente de test reutilizado en todos los tests del módulo."""
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def valid_user_id(client) -> int:
    """Obtiene un user_id real de la base para usar en los tests."""
    import sqlite3
    db_path = os.environ["SQLITE_PATH"]
    con = sqlite3.connect(db_path)
    user_id = con.execute(
        "SELECT user_id FROM transactions GROUP BY user_id ORDER BY COUNT(*) DESC LIMIT 1"
    ).fetchone()[0]
    con.close()
    return user_id


# ─── Test 1: /health — happy path ────────────────────────────────────────────

def test_health_returns_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["uptime_seconds"] >= 0
    assert "cache_hit_rate" in data


# ─── Test 2: /analytics/summary — happy path ─────────────────────────────────

def test_analytics_summary_structure(client):
    resp = client.get("/analytics/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_transactions"] > 0
    assert data["total_amount"] > 0
    assert len(data["by_country"]) > 0
    assert len(data["by_category"]) > 0
    # Verificar que los campos de breakdown están presentes
    country = data["by_country"][0]
    assert "country_code" in country
    assert "total_transactions" in country


# ─── Test 3: /analytics/summary — cache warm ────────────────────────────────

def test_analytics_summary_cache(client):
    """Segunda llamada debe ser significativamente más rápida (cache warm)."""
    # Cold
    t0 = time.perf_counter()
    client.get("/analytics/summary")
    cold_ms = (time.perf_counter() - t0) * 1000

    # Warm
    t0 = time.perf_counter()
    client.get("/analytics/summary")
    warm_ms = (time.perf_counter() - t0) * 1000

    assert warm_ms < cold_ms, f"Cache no funcionó: cold={cold_ms:.1f}ms warm={warm_ms:.1f}ms"
    assert warm_ms < 20, f"Cache warm debería ser <20ms, fue {warm_ms:.1f}ms"


# ─── Test 4: /analytics/top-merchants — happy path ───────────────────────────

def test_top_merchants_default(client):
    resp = client.get("/analytics/top-merchants")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["merchants"]) == 10   # limit por defecto
    assert data["merchants"][0]["total_amount"] >= data["merchants"][-1]["total_amount"]


def test_top_merchants_with_limit_and_country(client):
    resp = client.get("/analytics/top-merchants?limit=5&country=MX")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["merchants"]) <= 5
    assert data["country"] == "MX"


# ─── Test 5: /users/{user_id}/transactions — happy path ──────────────────────

def test_user_transactions_happy_path(client, valid_user_id):
    resp = client.get(f"/users/{valid_user_id}/transactions")
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == valid_user_id
    assert isinstance(data["transactions"], list)
    assert len(data["transactions"]) > 0


# ─── Test 6: /users/{user_id}/transactions — usuario inexistente (404) ────────

def test_user_transactions_not_found(client):
    resp = client.get("/users/999999999/transactions")
    assert resp.status_code == 404


# ─── Test 7: /users/{user_id}/transactions — paginación fuera de rango ────────

def test_user_transactions_page_out_of_range(client, valid_user_id):
    resp = client.get(f"/users/{valid_user_id}/transactions?page=99999&page_size=100")
    # Página muy alta devuelve lista vacía (no es error, es comportamiento esperado)
    assert resp.status_code == 200
    data = resp.json()
    assert data["transactions"] == []


# ─── Test 8: /users/{user_id}/stats — happy path ─────────────────────────────

def test_user_stats_happy_path(client, valid_user_id):
    resp = client.get(f"/users/{valid_user_id}/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == valid_user_id
    assert data["total_amount"] > 0
    assert data["transaction_count"] > 0
    assert data["top_category"] != ""
    assert len(data["country_code"]) == 2


# ─── Test 9: /users/{user_id}/stats — usuario inexistente (404) ───────────────

def test_user_stats_not_found(client):
    resp = client.get("/users/999999999/stats")
    assert resp.status_code == 404


# ─── Test 10: POST /transactions/batch — happy path ──────────────────────────

def test_batch_insert_happy_path(client):
    payload = {
        "transactions": [
            {
                "transaction_id": "test-batch-001",
                "timestamp":      "2026-01-15T10:00:00",
                "user_id":        1,
                "merchant_id":    1,
                "amount":         99.99,
                "category":       "Food",
                "country_code":   "MX",
                "status":         "completed",
            }
        ]
    }
    resp = client.post("/transactions/batch", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["inserted"] == 1
    assert data["duplicates"] == 0
    assert data["total_received"] == 1


# ─── Test 11: POST /transactions/batch — deduplicación ───────────────────────

def test_batch_deduplication(client):
    """Insertar el mismo transaction_id dos veces debe reportar duplicado."""
    payload = {
        "transactions": [
            {
                "transaction_id": "test-dedup-001",
                "timestamp":      "2026-01-15T11:00:00",
                "user_id":        2,
                "merchant_id":    2,
                "amount":         50.00,
                "category":       "Travel",
                "country_code":   "CO",
                "status":         "completed",
            }
        ]
    }
    # Primera inserción
    resp1 = client.post("/transactions/batch", json=payload)
    assert resp1.json()["inserted"] == 1

    # Segunda inserción del mismo ID
    resp2 = client.post("/transactions/batch", json=payload)
    assert resp2.json()["inserted"] == 0
    assert resp2.json()["duplicates"] == 1


# ─── Test 12: POST /transactions/batch — schema inválido (422) ────────────────

def test_batch_invalid_schema(client):
    payload = {
        "transactions": [
            {
                "transaction_id": "test-invalid-001",
                "timestamp":      "2026-01-15T12:00:00",
                "user_id":        1,
                "merchant_id":    1,
                "amount":         -100.0,   # amount negativo — inválido
                "category":       "Food",
                "country_code":   "MX",
                "status":         "completed",
            }
        ]
    }
    resp = client.post("/transactions/batch", json=payload)
    assert resp.status_code == 422


def test_batch_invalid_status(client):
    payload = {
        "transactions": [
            {
                "transaction_id": "test-invalid-002",
                "timestamp":      "2026-01-15T12:00:00",
                "user_id":        1,
                "merchant_id":    1,
                "amount":         100.0,
                "category":       "Food",
                "country_code":   "MX",
                "status":         "unknown_status",  # status inválido
            }
        ]
    }
    resp = client.post("/transactions/batch", json=payload)
    assert resp.status_code == 422


# ─── Test 13: SLA de latencia — /health siempre < 50ms ───────────────────────

def test_health_sla(client):
    """El endpoint /health debe responder siempre en menos de 50ms."""
    times = []
    for _ in range(10):
        t0 = time.perf_counter()
        client.get("/health")
        times.append((time.perf_counter() - t0) * 1000)
    p95 = sorted(times)[int(len(times) * 0.95)]
    assert p95 < 50, f"p95 de /health fue {p95:.1f}ms, debería ser <50ms"


# ─── Test 14: SLA de latencia — /analytics/summary warm < 20ms ───────────────

def test_summary_warm_sla(client):
    """Cache warm debe responder en menos de 20ms."""
    client.get("/analytics/summary")  # asegurar que está en cache
    t0 = time.perf_counter()
    resp = client.get("/analytics/summary")
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert resp.status_code == 200
    assert elapsed_ms < 20, f"Summary warm fue {elapsed_ms:.1f}ms, debería ser <20ms"
