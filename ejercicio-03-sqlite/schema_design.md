# Schema Design — Capa Transaccional SQLite

## Contexto del problema

El requerimiento es claro: consultas por usuario individual que respondan en menos de 50ms. Eso descarta DuckDB para este caso — DuckDB es un motor OLAP diseñado para escanear millones de filas en paralelo, no para saltar directamente a los registros de un usuario específico. SQLite con índices bien diseñados puede responder una búsqueda puntual en microsegundos porque el índice B-tree le dice exactamente en qué página del archivo está la información.

El diseño del schema parte de los 5 patrones de acceso, no al revés. Antes de decidir qué índices crear, analicé qué columnas aparecen en los WHERE y ORDER BY de cada patrón y qué tipo de operación hace cada uno (punto, rango, agrupamiento).

---

## Decisiones de tipo de dato

**`transaction_id` como TEXT**

SQLite no tiene tipo UUID nativo. La alternativa sería almacenarlo como BLOB (16 bytes) o como dos INTEGER de 64 bits, lo que reduciría el tamaño del índice. Elegí TEXT porque la ganancia de espacio con BLOB es marginal para 1M de registros (~16MB vs ~38MB en el índice) y TEXT permite consultas directas sin conversión: `WHERE transaction_id = 'abc-123'` funciona sin función auxiliar. La PRIMARY KEY sobre TEXT crea automáticamente un índice único que cubre P1 sin índice adicional.

**`timestamp` como TEXT en formato ISO 8601**

Esta fue la decisión más importante del schema. SQLite no tiene tipo DATETIME — las opciones son TEXT, REAL (Julian Day) o INTEGER (Unix epoch). Elegí TEXT con formato `YYYY-MM-DD HH:MM:SS.ffffff` porque las comparaciones lexicográficas sobre ese formato son equivalentes a comparaciones temporales: `'2026-01-15' > '2026-01-01'` es verdadero. Esto permite usar el índice `idx_user_timestamp` directamente con `BETWEEN` y `>=` sin funciones de conversión, que romperían el uso del índice en SQLite. Si hubiera usado `strftime()` en el WHERE, SQLite haría un full scan aunque existiera el índice.

**`amount` como REAL**

Float64 nativo de SQLite. Suficiente para valores en el rango 0.01–5000.00. La alternativa sería INTEGER (centavos × 100) para evitar errores de punto flotante, pero dado que los datos vienen de un CSV con floats y los SLA son de latencia no de precisión contable, REAL es apropiado aquí.

**`user_id` y `merchant_id` como INTEGER**

Tipo nativo más eficiente de SQLite. Comparaciones de enteros son más rápidas que de strings y el almacenamiento es más compacto (4-8 bytes vs longitud variable). Esto importa especialmente en el índice `idx_user_timestamp` que se consulta en cada P2, P3 y P4.

---

## Decisiones de índices

### PRIMARY KEY en `transaction_id` → cubre P1

La PRIMARY KEY en SQLite crea implícitamente un índice único B-tree. Para P1 (búsqueda exacta por `transaction_id`) esto es suficiente: el B-tree navega de la raíz a la hoja en O(log 1,000,000) ≈ 20 comparaciones. No necesité índice adicional.

Lo que no hice: no usé `INTEGER PRIMARY KEY` (ROWID alias) porque transaction_id es un UUID string, no un entero secuencial. Forzar una columna artificial de ROWID habría añadido complejidad sin beneficio para los patrones de acceso definidos.

### `idx_user_timestamp (user_id, timestamp)` → cubre P2, P3, P4

Este es el índice más importante del schema porque cubre tres patrones de una sola vez.

El razonamiento fue: P2, P3 y P4 comparten la misma estructura de acceso — "dame las transacciones de este usuario, filtradas o ordenadas por tiempo". En un índice compuesto `(user_id, timestamp)`, SQLite primero salta al `user_id` correcto (búsqueda exacta en la primera columna) y luego navega el subárbol de timestamps de ese usuario. Esto es un "range scan" dentro de un "point lookup", la operación más eficiente posible para estos patrones.

El orden de las columnas es crítico. Si el índice fuera `(timestamp, user_id)`, una búsqueda por `user_id` específico requeriría escanear todos los timestamps — el índice sería inútil para estos patrones. El orden `(user_id, timestamp)` permite que la primera columna actúe como "partición" y la segunda como "orden dentro de la partición".

Para P2 específicamente, el índice elimina el sort: `ORDER BY timestamp DESC LIMIT 20` sobre el índice ya ordenado es una simple lectura de las últimas 20 entradas del subárbol del usuario, sin materializar ni ordenar nada.

### `idx_country_user (country_code, user_id)` → cubre P5

P5 requiere: "para este country_code, dame los user_id con más de N transacciones". La query natural es:

```sql
SELECT user_id, COUNT(*) as cnt
FROM transactions
WHERE country_code = ?
GROUP BY user_id
HAVING cnt > ?
```

Sin índice, esto es un full scan de 1M filas con agrupamiento en memoria. Con `idx_country_user`, SQLite puede hacer un index-only scan: el índice contiene `(country_code, user_id)` y SQLite puede contar las apariciones de cada `user_id` dentro del `country_code` dado sin tocar la tabla principal (covering index para el COUNT).

Consideré añadir una tercera columna al índice (`country_code, user_id, amount`) para cubrir P4 también desde el índice de país, pero P4 ya está cubierto por `idx_user_timestamp` y añadir `amount` al índice de país solo aumentaría el tamaño del índice sin beneficio real para los patrones definidos.

### Lo que decidí NO indexar

No puse índice en `merchant_id`, `category`, `status` ni `amount` solos porque ningún patrón de acceso los usa como filtro primario. Un índice mal elegido no es neutral — ocupa espacio, ralentiza las escrituras y puede confundir al optimizador de SQLite. Cada índice que no existe es una decisión consciente.

---

## WAL mode

WAL (Write-Ahead Logging) es el modo de journaling alternativo de SQLite. En el modo por defecto (DELETE), cada escritura bloquea el archivo completo — lectores y escritores se excluyen mutuamente. En WAL, los escritores añaden al log sin bloquear lectores. Para la ingesta de 1M registros en chunks, WAL mejora el throughput porque los commits intermedios no bloquean el archivo mientras se escribe el siguiente chunk. El benchmark de ingesta mide ambos modos para cuantificar esta diferencia.

---

## Lo que este schema no intenta hacer

Este schema está optimizado exclusivamente para los 5 patrones definidos. No está optimizado para:
- Consultas analíticas de tipo OLAP (para eso existe DuckDB con el Parquet del E1)
- Actualizaciones frecuentes (no hay índices en columnas que cambiarían)
- Texto libre o búsqueda semántica

La especialización es intencional: un schema que intenta optimizar todo termina sin optimizar nada.
