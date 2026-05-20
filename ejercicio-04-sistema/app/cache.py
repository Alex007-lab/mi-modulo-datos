"""
cache.py — Cache en memoria con TTL configurable por endpoint.

El cache es un diccionario en memoria: clave → (valor, timestamp_expiry).
No usa Redis ni ninguna dependencia externa — es suficiente para un
proceso single-instance y permite demostrar el impacto cold vs warm
en los benchmarks de latencia.

El hit rate se acumula desde que arranca el servidor y se expone
en el endpoint /health.
"""

import time
from typing import Any, Optional


class TTLCache:
    """
    Cache en memoria con TTL por entrada.

    Uso:
        cache = TTLCache(default_ttl=60)
        cache.set("key", value, ttl=30)   # TTL específico
        cache.set("key", value)            # usa default_ttl
        result = cache.get("key")          # None si expiró o no existe
    """

    def __init__(self, default_ttl: int = 60):
        self._store:   dict[str, tuple[Any, float]] = {}
        self._default_ttl = default_ttl
        self._hits   = 0
        self._misses = 0

    def get(self, key: str) -> Optional[Any]:
        entry = self._store.get(key)
        if entry is None:
            self._misses += 1
            return None
        value, expiry = entry
        if time.monotonic() > expiry:
            del self._store[key]
            self._misses += 1
            return None
        self._hits += 1
        return value

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        ttl = ttl if ttl is not None else self._default_ttl
        self._store[key] = (value, time.monotonic() + ttl)

    def invalidate(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()

    # ─── Estadísticas para /health ────────────────────────────────────────────

    @property
    def hits(self) -> int:
        return self._hits

    @property
    def misses(self) -> int:
        return self._misses

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        return round(self._hits / total, 4) if total > 0 else 0.0

    def reset_stats(self) -> None:
        self._hits   = 0
        self._misses = 0


# TTLs por endpoint (segundos) — configurables aquí sin tocar main.py
CACHE_TTL = {
    "summary":      300,   # 5 minutos — datos históricos, cambian poco
    "top_merchants": 300,   # 5 minutos — mismo razonamiento
}

# Instancia global — se inicializa en el lifespan de FastAPI
cache: TTLCache = TTLCache(default_ttl=300)
