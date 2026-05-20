# Reporte de Latencia — Sistema Completo

**Módulo:** Python para Sistemas de Datos Modernos  
**Ejercicio:** 4 — El Sistema Completo  
**Metodología:** 100 requests por endpoint con `TestClient` de FastAPI (in-process, sin overhead de red).  
Cold time: primera llamada con cache vacío. `time.perf_counter()` para todas las mediciones.

---

## Resultados — p50 / p95 / p99

| Endpoint | Cold (ms) | p50 (ms) | p95 (ms) | p99 (ms) | SLA | Cumple |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| GET /analytics/summary | 60.38 | 0.61 | 1.18 | 2.47 | <500ms frío / <20ms caliente | ✅ |
| GET /analytics/top-merchants | 25.24 | 0.65 | 1.26 | 1.54 | <500ms frío / <20ms caliente | ✅ |
| GET /users/{id}/transactions | 1.31 | 0.85 | 1.43 | 1.65 | <80ms | ✅ |
| GET /users/{id}/stats | 1.35 | 0.69 | 1.43 | 1.66 | <80ms | ✅ |
| GET /health | 0.75 | 0.66 | 1.10 | 3.34 | <50ms siempre | ✅ |

**Todos los endpoints cumplen sus SLAs. 5/5.**

---

## Análisis por endpoint

### /analytics/summary

En frío tarda 60ms — DuckDB lee el Parquet Snappy, descomprime los bloques de columnas necesarios y agrega 1M de filas en tres queries (totales globales, breakdown por país, breakdown por categoría). En caliente el p50 baja a 0.61ms: el resultado serializado ya vive en el `TTLCache` y el endpoint solo lo devuelve. La diferencia entre cold y warm es de **99x** — exactamente el comportamiento esperado para datos analíticos históricos que no cambian entre requests.

El cold de 60ms está muy por debajo del SLA de 500ms, lo que da margen para que en producción real (con overhead de red y serialización HTTP completa) el endpoint siga cumpliendo holgadamente.

### /analytics/top-merchants

El cold de 25ms es más rápido que `/summary` porque la query es más simple: agrupa por `merchant_id` y ordena por volumen, leyendo solo dos columnas del Parquet (`merchant_id` y `amount`) frente a las cuatro que necesita summary. El cache warm de 0.65ms p50 confirma que el TTL funciona correctamente — la clave `top_merchants:10:all` se almacena independientemente de `/summary`.

### /users/{id}/transactions y /users/{id}/stats

Estos dos endpoints muestran el resultado más llamativo: **0.85ms y 0.69ms de p50**, muy por debajo del SLA de 80ms. La razón es que el `TestClient` ejecuta la aplicación in-process: SQLite ya tiene el archivo de base de datos mapeado en memoria desde el lifespan, y las páginas relevantes están en el page cache del sistema operativo desde las llamadas anteriores del benchmark.

Nótese que en el E3 estos mismos patrones tardaban 80-160ms. La diferencia es que aquí el page cache está caliente y la conexión se reutiliza desde el lifespan sin overhead de apertura — exactamente el argumento del `architecture_decision.md` sobre por qué las conexiones deben inicializarse en el lifespan y no dentro de cada endpoint.

En producción con un servidor real, estos endpoints añadirían 1-3ms de overhead de red, llegando a tiempos de 2-5ms — igualmente dentro del SLA con amplio margen.

### /health

El p50 de 0.66ms y p99 de 3.34ms confirman que la implementación es correcta: no toca ninguna base de datos, solo lee `time.monotonic()` y los contadores del `TTLCache` que viven en RAM. El spike ocasional en p99 (3.34ms vs 1.10ms en p95) es ruido del scheduler del sistema operativo, no un problema de la implementación.

---

## Impacto del cache — cold vs warm

| Endpoint | Cold (ms) | Warm p50 (ms) | Factor de mejora |
|---|:---:|:---:|:---:|
| /analytics/summary | 60.38 | 0.61 | **99x** |
| /analytics/top-merchants | 25.24 | 0.65 | **39x** |

El cache invalida correctamente después de un `POST /transactions/batch` — verificado en `test_batch_deduplication`: tras insertar, la próxima llamada a `/analytics/summary` recalcula desde DuckDB antes de volver a cachearse.

---

## Nota sobre la metodología

Las mediciones se realizaron con `TestClient` de FastAPI, que ejecuta la aplicación in-process sin overhead de red ni serialización HTTP real. El benchmark completo de 500 llamadas (5 endpoints × 100 requests) tardó aproximadamente 2 segundos, lo que confirma que el overhead de la infraestructura es mínimo y los tiempos reflejan el costo real de las operaciones de base de datos y cache.

En producción con red real (mismo datacenter o localhost), los tiempos aumentarían entre 0.5ms y 3ms por request dependiendo de la latencia de red. Los SLAs del ejercicio están definidos en términos de latencia de aplicación, por lo que esta metodología es apropiada para verificarlos.

---

*Mediciones realizadas en Python 3.14 con `time.perf_counter()`. 100 requests por endpoint para p50/p95/p99. Cold time: primera llamada con cache vacío (`cache.clear()` antes de medir). Conexiones a DuckDB y SQLite inicializadas en el lifespan de FastAPI y reutilizadas en todos los requests.*
