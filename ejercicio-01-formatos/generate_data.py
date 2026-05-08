"""
generate_data.py — Genera el dataset de transacciones para el módulo.

Uso:
    python generate_data.py --size 100k
    python generate_data.py --size 500k
    python generate_data.py --size 1m
"""

import argparse
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd


# ─── Constantes del schema (NO modificar) ────────────────────────────────────

CATEGORIES = [
    "Food", "Travel", "Electronics", "Health", "Entertainment",
    "Retail", "Transport", "Education", "Services", "Other",
]

COUNTRY_CODES = [
    "MX", "CO", "BR", "AR", "CL", "PE", "EC",
    "VE", "BO", "PY", "UY", "CR", "GT", "PA", "DO",
]

# Distribución de status: completed 85%, failed 10%, pending 5%
STATUS_VALUES = ["completed", "failed", "pending"]
STATUS_WEIGHTS = [0.85, 0.10, 0.05]

SIZE_MAP = {
    "100k": 100_000,
    "500k": 500_000,
    "1m":   1_000_000,
}

DATA_DIR = Path(__file__).parent / "data"


# ─── Generación ───────────────────────────────────────────────────────────────

def generate_transactions(n: int, seed: int = 42) -> pd.DataFrame:
    """
    Genera n filas de transacciones con el schema fijo del módulo.
    Usa numpy para velocidad; los UUIDs se generan en batch.
    """
    rng = np.random.default_rng(seed)

    # Rango de timestamps: último año hasta hoy
    now = datetime.now()
    one_year_ago = now - timedelta(days=365)
    total_seconds = int((now - one_year_ago).total_seconds())
    offsets = rng.integers(0, total_seconds, size=n)
    timestamps = [one_year_ago + timedelta(seconds=int(s)) for s in offsets]

    # UUIDs en batch usando bytes aleatorios de numpy
    raw = rng.bytes(n * 16)
    transaction_ids = [
        str(uuid.UUID(bytes=raw[i*16:(i+1)*16])) for i in range(n)
    ]

    df = pd.DataFrame({
        "transaction_id": transaction_ids,
        "timestamp":      timestamps,
        "user_id":        rng.integers(1, 50_001, size=n),
        "merchant_id":    rng.integers(1, 10_001, size=n),
        "amount":         rng.uniform(0.01, 5_000.00, size=n).round(2),
        "category":       rng.choice(CATEGORIES, size=n),
        "country_code":   rng.choice(COUNTRY_CODES, size=n),
        "status":         rng.choice(STATUS_VALUES, size=n, p=STATUS_WEIGHTS),
    })

    return df


def parse_size(size_str: str) -> int:
    """Convierte '100k', '500k' o '1m' a entero."""
    key = size_str.lower().strip()
    if key not in SIZE_MAP:
        raise ValueError(
            f"Tamaño '{size_str}' no válido. Opciones: {', '.join(SIZE_MAP)}"
        )
    return SIZE_MAP[key]


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Genera el dataset de transacciones en CSV."
    )
    parser.add_argument(
        "--size",
        required=True,
        choices=list(SIZE_MAP.keys()),
        help="Número de registros a generar (100k, 500k, 1m).",
    )
    args = parser.parse_args()

    n = parse_size(args.size)
    output_path = DATA_DIR / f"transactions_{args.size}.csv"
    DATA_DIR.mkdir(exist_ok=True)

    print(f"Generando {n:,} transacciones...")
    df = generate_transactions(n)

    print(f"Guardando en {output_path}...")
    df.to_csv(output_path, index=False)

    size_mb = output_path.stat().st_size / (1024 ** 2)
    print(f"Listo. Archivo: {output_path}  ({size_mb:.1f} MB)")
    print(f"Filas: {len(df):,}  |  Columnas: {list(df.columns)}")

    # Verificación rápida de distribución de status
    dist = df["status"].value_counts(normalize=True).mul(100).round(1)
    print("\nDistribución de status (%):")
    for status, pct in dist.items():
        print(f"  {status}: {pct}%")


if __name__ == "__main__":
    main()
