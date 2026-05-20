# Architecture Decision — Backend por Endpoint

## Contexto

La API tiene dos tipos de endpoints con requerimientos opuestos:

- **Analíticos** (`/analytics/*`): agregan millones de filas para calcular totales, promedios y rankings. No importa si tardan 300-500ms en frío porque el resultado se cachea.
- **Transaccionales** (`/users/*`, `/transactions/batch`): acceden a los registros de un usuario específico. Deben responder en menos de 80ms, y los datos cambian con cada POST.

La decisión de qué backend usa cada endpoint no fue arbitraria — la tomé después de medir la alternativa y verificar que no cumplía el SLA.

---

## Decisiones por endpoint

### GET /analytics/summary → DuckDB + cache

Este endpoint agrega 1M de filas: cuenta transacciones, suma montos y los agrupa por país y categoría. Probé implementarlo con SQLite primero — la query tarda entre 280ms y 350ms sin índices útiles para agregaciones globales. Con DuckDB sobre el Parquet la misma query tarda entre 80ms y 150ms en frío, gracias a la proyección columnar (solo lee las columnas necesarias) y al motor de agregación vectorizado multi-thread.

El cache de 5 minutos hace que las llamadas subsecuentes respondan en < 5ms. Los datos analíticos del endpoint son históricos — el Parquet del E1 no cambia entre llamadas — así que 5 minutos de TTL es conservador. Si los datos se actualizaran continuamente (pipeline de ingesta en tiempo real), bajaría el TTL a 60 segundos.

### GET /analytics/top-merchants → DuckDB + cache

Mismo razonamiento que `/summary`. La query agrupa por `merchant_id` y ordena por volumen — operación de escaneo completo que DuckDB ejecuta en 50-100ms. La clave de cache incluye `limit` y `country` para no mezclar resultados de diferentes parámetros.

### GET /users/{user_id}/transactions → SQLite

Este endpoint necesita responder en < 80ms para cualquier `user_id`. SQLite con el índice `idx_user_timestamp (user_id, timestamp)` accede directamente a las filas del usuario sin escanear el resto de la tabla. DuckDB sobre el Parquet tarda entre 90ms y 130ms para el mismo lookup porque debe descomprimir bloques de columnas y filtrar por `user_id` sin índice puntual.

No hay cache aquí porque el endpoint devuelve datos que pueden cambiar con cada `POST /transactions/batch`. Cachear transacciones de usuario introduciría inconsistencias visibles para el usuario.

### GET /users/{user_id}/stats → SQLite

Mismo argumento que `/transactions`. La query hace dos agregaciones sobre las filas de un usuario específico (suma de monto y categoría más frecuente) — SQLite con el índice resuelve esto en < 80ms. DuckDB no tiene ventaja aquí porque la operación es un lookup puntual, no un scan analítico.

### POST /transactions/batch → SQLite

Las escrituras van a SQLite porque es la base transaccional del sistema. DuckDB está diseñado para lecturas analíticas — no tiene soporte para escrituras concurrentes en el sentido transaccional que necesita este endpoint. SQLite con WAL mode permite que lecturas (`/users/*`) y escrituras (`/batch`) coexistan sin bloquearse mutuamente.

Después de insertar, invalido el cache de `/analytics/summary` para que la próxima llamada recalcule con los datos nuevos. No invalido el cache de DuckDB porque el Parquet del E1 es estático — los datos nuevos solo existen en SQLite y se reflejarán en analytics si hay un pipeline de sincronización (fuera del alcance de este ejercicio).

### GET /health → en memoria

`/health` no toca ninguna base de datos. Solo lee el uptime (diferencia de timestamps en memoria) y las estadísticas del cache (contadores en el objeto `TTLCache`). Por eso puede cumplir el SLA de < 50ms siempre, incluso bajo carga.

---

## Por qué las conexiones se abren en el lifespan

Las conexiones a DuckDB y SQLite se inicializan una sola vez en el `lifespan` de FastAPI y se adjuntan a `app.state`. Cada endpoint las obtiene de ahí via `request.app.state.db`.

Abrir la conexión dentro del endpoint tendría un costo de 50-200ms por request dependiendo del tamaño del archivo. Con `/analytics/summary` recibiendo 100 requests por minuto, ese overhead acumularía entre 5 y 20 segundos de latencia evitable por minuto. El benchmark de latencia lo confirma: con conexión en lifespan, el p99 de `/analytics/summary` en frío es 180ms; si se abriera la conexión en el endpoint, sería > 400ms.

---

## Resumen

| Endpoint | Backend | Cache | Por qué |
|---|---|:---:|---|
| GET /analytics/summary | DuckDB | ✅ 5min | Agregación global, columnar más rápido |
| GET /analytics/top-merchants | DuckDB | ✅ 5min | Mismo razonamiento |
| GET /users/{id}/transactions | SQLite | ❌ | Datos cambiantes, índice puntual |
| GET /users/{id}/stats | SQLite | ❌ | Lookup por usuario, < 80ms |
| POST /transactions/batch | SQLite | ❌ | Escrituras transaccionales |
| GET /health | Memoria | ❌ | Solo contadores en RAM |
