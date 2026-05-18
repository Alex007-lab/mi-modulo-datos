-- schema.sql — DDL completo para la capa transaccional de SQLite
--
-- Diseño orientado a 5 patrones de acceso con SLA estrictos:
--   P1: búsqueda por transaction_id exacto      → < 10ms
--   P2: últimas 20 tx de un user_id             → < 50ms
--   P3: tx de un user_id en rango de fechas     → < 50ms
--   P4: suma de amount de un user_id último mes → < 50ms
--   P5: user_ids de un country_code con > N tx  → < 200ms


-- ─── Tabla principal ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS transactions (
    -- UUID como TEXT: SQLite no tiene tipo UUID nativo.
    -- PRIMARY KEY crea automáticamente un índice único en transaction_id,
    -- lo que cubre P1 directamente sin índice adicional.
    transaction_id  TEXT        NOT NULL PRIMARY KEY,

    -- TIMESTAMP como TEXT en formato ISO 8601 (YYYY-MM-DD HH:MM:SS.ffffff).
    -- SQLite no tiene tipo DATETIME nativo; TEXT con formato ISO permite
    -- comparaciones lexicográficas correctas (>, <, BETWEEN) sin conversión.
    timestamp       TEXT        NOT NULL,

    -- Enteros como INTEGER: tipo nativo de SQLite, almacenamiento compacto
    -- y comparación rápida. Sin CHECK constraints para maximizar velocidad
    -- de ingesta (la validación ocurre en la capa de aplicación, en ingest.py).
    user_id         INTEGER     NOT NULL,
    merchant_id     INTEGER     NOT NULL,

    -- REAL para amount: equivalente a float64 de Python. Suficiente precisión
    -- para valores monetarios en el rango 0.01-5000.00.
    amount          REAL        NOT NULL,

    -- TEXT para columnas categóricas: cardinalidad baja (10 y 15 valores únicos
    -- respectivamente), lo que las hace candidatas ideales para índices compuestos.
    category        TEXT        NOT NULL,
    country_code    TEXT        NOT NULL,
    status          TEXT        NOT NULL
);


-- ─── Índices ─────────────────────────────────────────────────────────────────

-- IDX_USER_TIMESTAMP: índice compuesto para P2, P3 y P4.
--
-- P2 necesita las últimas 20 transacciones de un user_id ordenadas por timestamp.
-- Sin este índice, SQLite haría un full table scan (1M filas) para encontrar
-- las transacciones del usuario y luego un sort. Con el índice, la búsqueda
-- es O(log n) en user_id y las filas ya vienen ordenadas por timestamp desde
-- el índice, eliminando el sort completamente.
--
-- P3 usa user_id + rango de timestamp: el índice compuesto permite seek
-- directo a (user_id, fecha_inicio) y scan hasta (user_id, fecha_fin).
--
-- P4 suma amount filtrado por user_id y último mes: misma estrategia que P3,
-- el índice cubre el filtro y SQLite solo lee las filas del período.
--
-- El orden (user_id, timestamp) es crítico: invertirlo haría inútil el índice
-- para búsquedas por usuario específico.
CREATE INDEX IF NOT EXISTS idx_user_timestamp
    ON transactions (user_id, timestamp);


-- IDX_COUNTRY_USER: índice compuesto para P5.
--
-- P5 agrupa por country_code y cuenta transacciones por user_id para filtrar
-- los que superan N. Sin índice, full scan + group by sobre 1M filas.
-- Con este índice, SQLite puede hacer un index scan agrupado por country_code,
-- evitando tocar la tabla principal para el conteo.
--
-- Se incluye user_id en el índice (no solo country_code) porque la query
-- necesita GROUP BY user_id dentro de cada país — el índice compuesto
-- permite hacer ese agrupamiento directamente sobre el índice.
CREATE INDEX IF NOT EXISTS idx_country_user
    ON transactions (country_code, user_id);
