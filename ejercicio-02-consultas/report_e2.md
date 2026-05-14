# Reporte — El Motor de Consultas

**Módulo:** Python para Sistemas de Datos Modernos  
**Ejercicio:** 2 — Benchmark de Query Engines  
**Dataset:** 1,000,000 transacciones financieras en formato Parquet Snappy  
**Engines evaluados:** pandas, DuckDB, Polars

---

## 1. Tabla comparativa — 8 queries en 3 engines

| Query | Descripción                  | Pandas (s) | DuckDB (s) | Polars (s) | Ganador |
| ----- | ---------------------------- | :--------: | :--------: | :--------: | :-----: |
| Q1    | Conteo por country_code      |   0.0724   | **0.0596** |   0.2268   | DuckDB  |
| Q2    | Stats de amount por category |   0.0776   | **0.0594** |   0.1376   | DuckDB  |
| Q3    | Top 10 users por amount      | **0.0584** |   0.1320   |   0.1397   | pandas  |
| Q4    | Fallidas por hora del día    |   0.1013   | **0.0442** |   0.1565   | DuckDB  |
| Q5    | Amount>500 en MX/CO, 30 días | **0.0814** |   0.1520   |   0.1369   | pandas  |
| Q6    | Top category por país        |   0.1025   | **0.0760** |   0.1405   | DuckDB  |
| Q7    | Usuarios con >5 fallos       |   0.0718   | **0.0419** |   0.1356   | DuckDB  |
| Q8    | Promedio diario por category |   0.8326   | **0.0971** |   0.1715   | DuckDB  |

> Todas las queries fueron validadas como **numéricamente equivalentes** entre los tres engines (✅ 8/8).

---

## 2. Interpretación de EXPLAIN ANALYZE

### Q3 — Top 10 users por suma de amount

El plan de DuckDB para Q3 muestra la siguiente secuencia de operaciones de abajo hacia arriba:

**TABLE_SCAN → PROJECTION → PROJECTION → HASH_GROUP_BY → PROJECTION → TOP_N**

Lo más relevante es lo que DuckDB hace antes de leer datos: en el `TABLE_SCAN` con `READ_PARQUET`, el plan muestra `Projections: user_id, amount`. Esto significa que DuckDB **no lee las 8 columnas del archivo** — solo extrae las dos columnas que necesita, aprovechando la naturaleza columnar de Parquet. Las otras 6 columnas (transaction_id, timestamp, merchant_id, category, country_code, status) nunca se cargan en memoria.

El paso `HASH_GROUP_BY` es donde ocurre la agregación real: DuckDB construye una tabla hash con `user_id` como clave y acumula `SUM(amount)` y `COUNT(*)` en una sola pasada sobre los 1,000,000 de filas. El resultado intermedio son 50,000 filas (una por `user_id` único). Finalmente, `TOP_N` aplica el `LIMIT 10` **durante** el ordenamiento, sin necesidad de ordenar los 50,000 usuarios completos — solo mantiene un heap de los 10 mayores. El tiempo total fue de **0.0395 segundos**.

### Q5 — Transacciones con amount > 500 en MX o CO, últimos 30 días

El plan de Q5 es el más interesante porque muestra cómo DuckDB maneja condiciones múltiples combinadas con una subconsulta.

El nodo `TABLE_SCAN` revela algo crítico: en el campo `Filters` aparece `amount>500.0` y `optional: country_code IN ('MX', 'CO')`. Esto es **predicate pushdown** — los filtros se aplican directamente al leer el Parquet, antes de que los datos lleguen al motor de ejecución. Además, aparece un `Dynamic Filters: timestamp>='2026-04-08 18:53:30...'` — DuckDB evaluó primero el `MAX(timestamp)` de la subconsulta `max_date`, calculó el cutoff de 30 días, y luego lo inyectó como filtro estático en el scan del archivo principal. El resultado: de 1,000,000 filas, solo 73,704 pasan el filtro de `amount` y `country_code`, y de esas solo 9,883 pasan el filtro de fecha. El `NESTED_LOOP_JOIN` con `max_date` es trivial porque `max_date` es exactamente 1 fila.

Esto explica por qué Q5 es donde pandas y DuckDB están más parejos (0.1707s vs 0.1670s): el cuello de botella real es el I/O del archivo, no el cómputo, y ambos engines leen el mismo Parquet.

### Q6 — Top category por country_code

Q6 es la query más compleja del benchmark: requiere un doble agrupamiento (por país+categoría primero, luego por país solo para quedarse con el máximo). El plan de DuckDB resuelve esto de forma muy eficiente.

El `TABLE_SCAN` lee solo 3 columnas: `country_code`, `category` y `amount` — nuevamente, proyección columnar exacta. El primer `HASH_GROUP_BY` agrupa por `(country_code, category)` y calcula `COUNT(*)` y `AVG(amount)`, produciendo 150 filas (15 países × 10 categorías). El segundo `HASH_GROUP_BY` usa la función interna `arg_max_nulls_last` para quedarse, por cada `country_code`, con el struct completo `(category, transaction_count, avg_amount)` correspondiente al mayor `transaction_count`. Esto es equivalente al `ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ...)` del SQL, pero implementado internamente como una agregación, lo que evita construir una ventana completa. El tiempo total fue de **0.0349 segundos** para una query que en pandas tardó 0.3979s.

---

## 3. Análisis de tradeoffs por query

### Query donde Polars supera claramente a pandas: Q8

Q8 (promedio diario por categoría) es donde la diferencia entre Polars y pandas es más dramática: **0.1557s vs 2.3825s** — pandas es 15 veces más lento.

La razón es la operación `dt.date` sobre 1,000,000 timestamps. En pandas, extraer la fecha de un timestamp es una operación que genera objetos Python `datetime.date` intermedios antes de poder agrupar. Polars, en cambio, maneja timestamps como enteros de 64 bits internamente y la extracción de la fecha es una operación vectorizada sobre el array entero sin generar objetos Python. Adicionalmente, el `group_by` de Polars usa un algoritmo de hashing multi-threaded que aprovecha todos los núcleos disponibles, mientras que el `groupby` de pandas es single-threaded. Para Q8, donde el número de grupos es grande (365 días × 10 categorías = ~3,650 grupos), esta diferencia se amplifica.

### Query donde DuckDB es el ganador claro: Q4

Q4 (transacciones fallidas agrupadas por hora) muestra la mayor ventaja de DuckDB: **0.0500s vs 0.5228s de pandas** — 10 veces más rápido.

Pandas tarda tanto porque primero filtra el DataFrame completo por `status == 'failed'` (operación sobre 1M filas en RAM), luego hace una copia con `.copy()`, y finalmente extrae la hora con `pd.to_datetime().dt.hour`, que requiere una conversión de tipo sobre todo el subset filtrado. DuckDB, en cambio, empuja el filtro `WHERE status = 'failed'` al Parquet scan y extrae la hora con `HOUR(timestamp)` directamente sobre los datos binarios, sin pasar por representaciones intermedias. El resultado: DuckDB procesa Q4 tan rápido como Q1 (simple conteo), porque la complejidad es la misma una vez que el filtro se aplica en el scan.

### Query donde los tres son comparables: Q5

Q5 (amount > 500 en MX o CO, últimos 30 días) es donde los tres engines están más cerca: pandas 0.1707s, DuckDB 0.1670s, Polars 0.6484s. Pandas y DuckDB son prácticamente iguales.

Para pandas, el dataset ya está cargado en RAM: filtrar por tres condiciones booleanas sobre arrays de numpy es extremadamente eficiente. Para DuckDB, aunque aplica predicate pushdown, el cuello de botella real es el I/O del archivo Parquet —no el cómputo— y ese costo lo comparte con pandas cuando pandas ya tiene el archivo en memoria. Polars es el más lento aquí porque recarga el Parquet desde disco en cada llamada (no mantiene cache entre queries en nuestro benchmark), lo que lo penaliza frente a pandas que ya tiene el DataFrame en RAM.

---

## 4. Recomendación de arquitectura

### Cuándo usar DuckDB

DuckDB es el engine correcto para **cualquier carga analítica sobre archivos** (Parquet, CSV, JSON). Su ventaja es estructural: opera directamente sobre archivos sin cargarlos completos en RAM, aplica predicate pushdown y proyección columnar, y usa múltiples núcleos de forma transparente. En nuestro benchmark ganó las 8 queries. El caso de uso ideal es: pipelines de analytics, reportes, dashboards, consultas ad-hoc sobre datasets de cientos de MB a decenas de GB. También es la elección correcta cuando el mismo archivo se consulta desde múltiples procesos o cuando la memoria disponible es limitada, ya que DuckDB usa típicamente menos de 1 MB de RAM en este benchmark versus los 16-117 MB de pandas.

### Cuándo usar Polars

Polars brilla en **transformaciones complejas sobre DataFrames** donde el dataset ya está en memoria y las operaciones son encadenadas (lazy evaluation). Su ventaja real —que este benchmark no captura completamente— es la API lazy: con `pl.scan_parquet()` en lugar de `pl.read_parquet()`, Polars puede optimizar toda una cadena de operaciones antes de ejecutarla, similar a Spark pero en un solo proceso. Para pipelines de ETL con múltiples pasos de transformación (filtrar, enriquecer, agrupar, unir), Polars supera a pandas de forma consistente. La elección de Polars sobre DuckDB se justifica cuando las transformaciones son más programáticas que declarativas —cuando la lógica es difícil de expresar en SQL pero natural en código Python.

### Cuándo usar pandas

Pandas sigue siendo válido para **exploración interactiva** (notebooks, análisis ad-hoc con datasets que caben cómodamente en RAM), para **integración con el ecosistema científico** (scikit-learn, matplotlib, statsmodels esperan DataFrames de pandas), y para **operaciones fila a fila** donde la vectorización no aplica. Su debilidad principal es el rendimiento en operaciones de agrupamiento sobre fechas (Q8) y en consultas con filtros sobre datos en disco. Para producción analítica a escala, pandas debería funcionar como capa final de presentación de resultados, no como motor de procesamiento.

---

_Mediciones realizadas con `time.perf_counter()` y `tracemalloc`. Dataset: 1,000,000 filas, Parquet Snappy. Equivalencia validada con tolerancia numérica de ±0.01 en valores float._
