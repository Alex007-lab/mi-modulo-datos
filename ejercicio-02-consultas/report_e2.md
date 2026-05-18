# Reporte — El Motor de Consultas

**Módulo:** Python para Sistemas de Datos Modernos  
**Ejercicio:** 2 — Benchmark de Query Engines  
**Dataset:** 1,000,000 transacciones financieras en formato Parquet Snappy  
**Engines evaluados:** pandas, DuckDB, Polars

---

## 1. Tabla comparativa — 8 queries en 3 engines

| Query | Descripción | Pandas (s) | DuckDB (s) | Polars (s) | Ganador |
|-------|-------------|:----------:|:----------:|:----------:|:-------:|
| Q1 | Conteo por country_code | 0.0323 | **0.0237** | 0.1167 | DuckDB |
| Q2 | Stats de amount por category | 0.0491 | **0.0469** | 0.1151 | DuckDB |
| Q3 | Top 10 users por amount | **0.0442** | 0.1025 | 0.1061 | pandas |
| Q4 | Fallidas por hora del día | 0.0684 | **0.0333** | 0.1011 | DuckDB |
| Q5 | Amount>500 en MX/CO, 30 días | **0.0624** | 0.1257 | 0.0991 | pandas |
| Q6 | Top category por país | 0.0926 | **0.0624** | 0.1234 | DuckDB |
| Q7 | Usuarios con >5 fallos | 0.0381 | **0.0339** | 0.1017 | DuckDB |
| Q8 | Promedio diario por category | 0.7011 | **0.0775** | 0.1244 | DuckDB |

> Todas las queries fueron validadas como **numéricamente equivalentes** entre los tres engines (✅ 8/8).

---

## 2. Interpretación de EXPLAIN ANALYZE

### Q3 — Top 10 users por suma de amount

El plan de DuckDB para Q3 muestra la siguiente secuencia de operaciones (de abajo hacia arriba):

**TABLE_SCAN → PROJECTION → PROJECTION → HASH_GROUP_BY → PROJECTION → TOP_N**

Lo más relevante ocurre en el `TABLE_SCAN` con `READ_PARQUET`: el plan muestra `Projections: user_id, amount`. Esto significa que DuckDB **no lee las 8 columnas del archivo** — extrae solo las dos que necesita, aprovechando la naturaleza columnar de Parquet. Las otras 6 columnas nunca se cargan en memoria.

El paso `HASH_GROUP_BY` es donde ocurre la agregación: DuckDB construye una tabla hash con `user_id` como clave y acumula `SUM(amount)` y `COUNT(*)` en una sola pasada sobre 1,000,000 filas, produciendo 50,000 filas intermedias (una por `user_id` único). El nodo `TOP_N` aplica el `LIMIT 10` **durante** el ordenamiento sin necesidad de ordenar los 50,000 usuarios completos — mantiene un heap de los 10 mayores. El tiempo total reportado por DuckDB fue de **0.088 segundos**.

Sin embargo, con 3 repeticiones y promedio, **pandas gana Q3 con 0.044s frente a 0.103s de DuckDB**. La razón es que pandas tiene el DataFrame ya cargado en RAM desde el inicio del benchmark: el `groupby` sobre arrays numpy en memoria es más barato que el overhead que DuckDB paga por abrir el archivo Parquet, leerlo y ejecutar el plan en cada llamada. Este resultado ilustra un tradeoff importante: DuckDB es más eficiente leyendo desde disco, pero cuando los datos ya están en RAM, pandas puede superar a DuckDB en operaciones de agrupamiento simples.

### Q5 — Transacciones con amount > 500 en MX o CO, últimos 30 días

El plan de Q5 muestra cómo DuckDB maneja condiciones múltiples combinadas con una subconsulta.

El nodo `TABLE_SCAN` revela **predicate pushdown** en acción: en el campo `Filters` aparece `amount>500.0` y `optional: country_code IN ('MX', 'CO')`. Los filtros se aplican directamente al leer el Parquet, antes de que los datos lleguen al motor. Además, el campo `Dynamic Filters` muestra `timestamp>='2026-04-18 01:44:07...'` — DuckDB evaluó primero la subconsulta `max_date` para obtener el `MAX(timestamp)`, calculó el cutoff de 30 días, y lo inyectó como filtro estático en el scan principal. De 1,000,000 filas, solo 73,704 pasan el filtro de `amount` y `country_code`, y de esas solo 9,883 pasan el filtro de fecha. El `NESTED_LOOP_JOIN` con `max_date` es trivial porque esa tabla tiene exactamente 1 fila.

A pesar de esta optimización, **pandas gana Q5 con 0.062s frente a 0.126s de DuckDB**. El motivo es el mismo que en Q3: pandas opera sobre el DataFrame ya en RAM con operaciones vectorizadas sobre arrays numpy, evitando el overhead de I/O del archivo. Q5 retorna 9,883 filas, lo que también implica que DuckDB debe materializar y transferir ese resultado de vuelta a pandas, costo que en Q3 (solo 10 filas) es despreciable.

### Q6 — Top category por country_code

Q6 es la query más compleja: requiere un doble agrupamiento (por país+categoría primero, luego por país solo para quedarse con el máximo).

El `TABLE_SCAN` lee solo 3 columnas: `country_code`, `category` y `amount` — proyección columnar exacta. El primer `HASH_GROUP_BY` agrupa por `(country_code, category)` y calcula `COUNT(*)` y `AVG(amount)`, produciendo 150 filas (15 países × 10 categorías). El segundo `HASH_GROUP_BY` usa la función interna `arg_max_nulls_last` para quedarse, por cada `country_code`, con el struct completo `(category, transaction_count, avg_amount)` correspondiente al mayor `transaction_count`. Esto evita construir una ventana completa con `ROW_NUMBER()` — es equivalente pero implementado como una agregación directa. El tiempo total reportado por DuckDB fue de **0.048 segundos**, ganando a pandas (0.093s) en esta query más compleja donde el doble agrupamiento penaliza más a pandas.

---

## 3. Análisis de tradeoffs por query

### Query donde pandas supera claramente a DuckDB: Q3

Con 3 repeticiones y promedio, Q3 (Top 10 users por amount) muestra a **pandas ganando con 0.044s frente a 0.103s de DuckDB** — más del doble de rápido.

La causa es directa: pandas tiene el DataFrame cargado en RAM desde el inicio del benchmark. El `groupby("user_id").agg(...)` opera sobre arrays numpy contiguos en memoria, una operación altamente optimizada. DuckDB, en cambio, abre el archivo Parquet en cada llamada, lee las columnas necesarias desde disco, ejecuta el plan de aggregación y devuelve el resultado. Ese overhead de I/O y materialización domina cuando la operación de cómputo en sí es barata. Con una sola medición (sin repeticiones), el page cache del sistema operativo podría haber favorecido a DuckDB en la segunda y tercera ejecución; con el promedio, el overhead real de abrir el archivo se vuelve visible.

### Query donde DuckDB es el ganador claro: Q8

Q8 (promedio diario por categoría) es donde la ventaja de DuckDB es más dramática: **0.078s frente a 0.701s de pandas** — 9 veces más rápido.

En pandas, la operación `dt.date` sobre 1,000,000 timestamps genera objetos Python `datetime.date` intermedios antes de poder agrupar, lo que es costoso tanto en tiempo como en memoria (117 MB de pico). Además, el número de grupos resultantes es grande (~3,660: 366 días × 10 categorías), lo que hace el `groupby` más pesado. DuckDB ejecuta `CAST(timestamp AS DATE)` directamente sobre los enteros de 64 bits internos sin generar objetos Python, y agrupa con HASH_GROUP_BY multi-threaded en 0.078s usando solo 0.42 MB de RAM. La diferencia de 9x en tiempo y 280x en memoria hace de Q8 el caso más claro de cuándo DuckDB es la elección correcta.

### Query donde los tres son comparables: Q2

Q2 (stats de amount por category) es donde los tres engines están más cerca: pandas 0.049s, DuckDB 0.047s, Polars 0.115s. Pandas y DuckDB son prácticamente iguales.

La razón es que Q2 opera sobre una sola columna numérica (`amount`) con agrupamiento en solo 10 categorías — el caso más simple posible para un motor de agregación. Para pandas, el DataFrame ya está en RAM y el `groupby` sobre 10 grupos con `mean/min/max` es trivial. Para DuckDB, leer solo `category` y `amount` del Parquet (2 columnas de 8) es igualmente barato. El resultado es un empate técnico donde el overhead de cada engine se cancela mutuamente. Polars es más lento porque recarga el Parquet desde disco en cada llamada sin beneficiarse del cache del DataFrame en RAM.

---

## 4. Recomendación de arquitectura

### Cuándo usar DuckDB

DuckDB es el engine correcto para **cualquier carga analítica sobre archivos** cuando los datos no están previamente cargados en RAM. Su predicate pushdown, proyección columnar y ejecución multi-threaded lo hacen consistentemente eficiente para consultas complejas (Q6, Q8) y queries con filtros sobre archivos grandes. También es la elección correcta cuando la memoria es limitada: DuckDB procesó todas las queries usando menos de 2 MB de RAM, mientras pandas cargó el DataFrame completo (~400 MB). El caso ideal es pipelines de analytics, reportes y dashboards donde los datos viven en archivos Parquet y las consultas son declarativas en SQL.

### Cuándo usar pandas

Pandas es competitivo —y en algunos casos superior a DuckDB— cuando el **DataFrame ya está cargado en memoria** y las operaciones son simples agrupamientos sobre columnas numéricas (Q3, Q5, Q7). Si un pipeline hace múltiples consultas sobre el mismo dataset, cargar una vez en pandas y reutilizar el DataFrame puede ser más eficiente que que DuckDB abra el archivo en cada llamada. También es la elección natural cuando el resultado necesita integrarse con el ecosistema científico de Python (scikit-learn, matplotlib, statsmodels).

### Cuándo usar Polars

En este benchmark Polars no ganó ninguna query, porque cada llamada recarga el Parquet desde disco sin mantener un DataFrame en RAM entre queries. La ventaja real de Polars —que este benchmark no captura— es su **API lazy con `pl.scan_parquet()`**: encadenando transformaciones antes de ejecutarlas, Polars optimiza el plan completo y puede superar a DuckDB en pipelines de ETL con múltiples pasos. Para transformaciones complejas donde la lógica es difícil de expresar en SQL pero natural en código Python, Polars es la elección correcta sobre pandas.

---

*Mediciones realizadas en Python 3.14 con `time.perf_counter()`. Cada query se ejecutó 3 veces por engine y se reporta el promedio. El pico de memoria se registró en la primera ejecución con `tracemalloc`. Dataset: 1,000,000 filas en formato Parquet Snappy. Equivalencia numérica validada con tolerancia ±0.01 en valores float.*
