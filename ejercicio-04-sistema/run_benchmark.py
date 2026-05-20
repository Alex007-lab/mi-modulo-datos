import os, time, json
from pathlib import Path

os.environ.setdefault("PARQUET_PATH", str(list(Path("..").glob(
    "ejercicio-01-formatos/data/*1m*snappy*.parquet"))[0]))
os.environ.setdefault("SQLITE_PATH",
    str(Path("../ejercicio-03-sqlite/data/transactions.db")))

from fastapi.testclient import TestClient
import sqlite3

con = sqlite3.connect(os.environ["SQLITE_PATH"])
valid_user = con.execute(
    "SELECT user_id FROM transactions GROUP BY user_id ORDER BY COUNT(*) DESC LIMIT 1"
).fetchone()[0]
con.close()

from app.main import app

ENDPOINTS = [
    ("GET /analytics/summary",        "get", "/analytics/summary"),
    ("GET /analytics/top-merchants",   "get", "/analytics/top-merchants?limit=10"),
    ("GET /users/{id}/transactions",   "get", f"/users/{valid_user}/transactions"),
    ("GET /users/{id}/stats",          "get", f"/users/{valid_user}/stats"),
    ("GET /health",                    "get", "/health"),
]

N = 100
results = {}

with TestClient(app) as client:
    for name, method, path in ENDPOINTS:
        fn = getattr(client, method)

        if "analytics" in path:
            client.app.state.cache.clear()

        cold_t = time.perf_counter()
        fn(path)
        cold_ms = (time.perf_counter() - cold_t) * 1000

        times = []
        for _ in range(N):
            t0 = time.perf_counter()
            fn(path)
            times.append((time.perf_counter() - t0) * 1000)

        times.sort()
        results[name] = {
            "cold_ms": round(cold_ms, 2),
            "p50":     round(times[int(N*0.50)], 2),
            "p95":     round(times[int(N*0.95)], 2),
            "p99":     round(times[int(N*0.99)], 2),
        }
        print(f"{name:<40} cold={cold_ms:6.1f}ms  "
              f"p50={times[int(N*0.50)]:5.1f}ms  "
              f"p95={times[int(N*0.95)]:5.1f}ms  "
              f"p99={times[int(N*0.99)]:5.1f}ms")

Path("benchmarks").mkdir(exist_ok=True)
with open("benchmarks/results.json", "w") as f:
    json.dump(results, f, indent=2)
print("\nGuardado en benchmarks/results.json")
