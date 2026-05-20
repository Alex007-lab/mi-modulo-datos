"""
db.py — Gestión de conexiones a DuckDB y SQLite.

Las conexiones se abren UNA SOLA VEZ en el lifespan de FastAPI y se
reutilizan en todos los requests. Abrirlas dentro de cada endpoint
añadiría 50-200ms de overhead por request — error de arquitectura
que se vería inmediatamente en los benchmarks de latencia.

DuckDB: para los endpoints analíticos (/analytics/*).
SQLite: para los endpoints transaccionales (/users/*, /transactions/batch).
"""

from pathlib import Path
from typing import Optional

import duckdb
import sqlite3

# Rutas por defecto — sobreescribibles via variables de entorno en main.py
DEFAULT_PARQUET = (
    Path(__file__).parent.parent.parent
    / "ejercicio-01-formatos" / "data" / "transactions_1m_parquet_snappy.parquet"
)
DEFAULT_DB = (
    Path(__file__).parent.parent.parent
    / "ejercicio-03-sqlite" / "data" / "transactions.db"
)


class DatabaseConnections:
    """
    Contenedor de conexiones activas.
    Se instancia una vez en el lifespan y se adjunta al app.state.
    """

    def __init__(self, parquet_path: Path, db_path: Path):
        self.parquet_path = parquet_path
        self.db_path      = db_path
        self._duck: Optional[duckdb.DuckDBPyConnection] = None
        self._sqlite: Optional[sqlite3.Connection]      = None

    def open(self) -> None:
        """Abre ambas conexiones. Llamado en el lifespan startup."""
        # DuckDB in-memory — lee el Parquet directamente en cada query
        self._duck = duckdb.connect()
        self._duck.execute("PRAGMA threads=4")

        # SQLite — WAL mode para lecturas concurrentes sin bloqueo
        self._sqlite = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,   # FastAPI usa un thread pool
        )
        self._sqlite.execute("PRAGMA journal_mode=WAL")
        self._sqlite.execute("PRAGMA cache_size=-64000")  # 64MB cache
        self._sqlite.execute("PRAGMA synchronous=NORMAL")
        self._sqlite.row_factory = sqlite3.Row              # acceso por nombre de columna

    def close(self) -> None:
        """Cierra ambas conexiones. Llamado en el lifespan shutdown."""
        if self._duck:
            self._duck.close()
        if self._sqlite:
            self._sqlite.close()

    @property
    def duck(self) -> duckdb.DuckDBPyConnection:
        if self._duck is None:
            raise RuntimeError("DuckDB no está inicializado. ¿Se llamó open()?")
        return self._duck

    @property
    def sqlite(self) -> sqlite3.Connection:
        if self._sqlite is None:
            raise RuntimeError("SQLite no está inicializado. ¿Se llamó open()?")
        return self._sqlite
