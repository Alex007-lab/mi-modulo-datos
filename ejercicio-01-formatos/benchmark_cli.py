"""
benchmark_cli.py — CLI para ejecutar el benchmark de formatos.

Uso:
    python benchmark_cli.py --size 100k
    python benchmark_cli.py --size 1m --formats csv parquet_snappy parquet_gzip
    python benchmark_cli.py --size 500k --formats csv json parquet_none parquet_snappy parquet_gzip

Formatos disponibles: csv, json, parquet_none, parquet_snappy, parquet_gzip
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
import matplotlib
matplotlib.use("Agg")  # Sin pantalla (modo headless)
import matplotlib.pyplot as plt

# Rutas del proyecto
PROJECT_DIR  = Path(__file__).parent
DATA_DIR     = PROJECT_DIR / "data"
RESULTS_DIR  = PROJECT_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)

# Importamos el módulo de benchmark
sys.path.insert(0, str(PROJECT_DIR))
from storage_benchmark import benchmark_all
from storage_benchmark.runner import FORMAT_REGISTRY
from generate_data import generate_transactions, SIZE_MAP


# ─── Helpers ─────────────────────────────────────────────────────────────────

ALL_FORMATS = list(FORMAT_REGISTRY.keys())

FORMAT_LABELS = {
    "csv":            "CSV",
    "json":           "JSON Lines",
    "parquet_none":   "Parquet (sin compresión)",
    "parquet_snappy": "Parquet (Snappy)",
    "parquet_gzip":   "Parquet (Gzip)",
}


def save_results(results: list[dict], size_label: str) -> Path:
    """Guarda los resultados en un JSON dentro de results/."""
    output = RESULTS_DIR / f"benchmark_{size_label}.json"
    with open(output, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nResultados guardados en: {output}")
    return output


def print_table(results: list[dict]) -> None:
    """Imprime una tabla resumen en la terminal."""
    header = f"{'Formato':<25} {'Escritura(s)':>14} {'Lectura(s)':>12} {'Selectiva(s)':>14} {'Tamaño(MB)':>12} {'Mem(MB)':>10}"
    sep = "─" * len(header)
    print(f"\n{sep}")
    print(header)
    print(sep)
    for r in results:
        label = FORMAT_LABELS.get(r["format"], r["format"])
        if r.get("error"):
            print(f"{label:<25} {'ERROR: ' + r['error']:>64}")
        else:
            print(
                f"{label:<25} "
                f"{r['write_avg_s']:>14.4f} "
                f"{r['read_full_s']:>12.4f} "
                f"{r['read_selective_s']:>14.4f} "
                f"{r['size_mb']:>12.2f} "
                f"{r['peak_memory_mb']:>10.2f}"
            )
    print(sep)


def generate_charts(results: list[dict], size_label: str) -> None:
    """Genera gráficas de barras para tiempo de lectura y tamaño en disco."""
    valid = [r for r in results if not r.get("error")]
    labels   = [FORMAT_LABELS.get(r["format"], r["format"]) for r in valid]
    reads    = [r["read_full_s"] for r in valid]
    sizes_mb = [r["size_mb"] for r in valid]
    colors   = ["#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B2"]

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    fig.suptitle(f"Benchmark de Formatos — {size_label.upper()}", fontsize=14, fontweight="bold")

    # Gráfica 1: Tiempo de lectura completa
    bars1 = axes[0].bar(labels, reads, color=colors)
    axes[0].set_title("Tiempo de lectura completa (s)")
    axes[0].set_ylabel("Segundos")
    axes[0].set_xticks(range(len(labels)))
    axes[0].set_xticklabels(labels, rotation=20, ha="right", fontsize=9)
    for bar, val in zip(bars1, reads):
        axes[0].text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.002,
            f"{val:.3f}s",
            ha="center", va="bottom", fontsize=8,
        )

    # Gráfica 2: Tamaño en disco
    bars2 = axes[1].bar(labels, sizes_mb, color=colors)
    axes[1].set_title("Tamaño en disco (MB)")
    axes[1].set_ylabel("MB")
    axes[1].set_xticks(range(len(labels)))
    axes[1].set_xticklabels(labels, rotation=20, ha="right", fontsize=9)
    for bar, val in zip(bars2, sizes_mb):
        axes[1].text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.3,
            f"{val:.1f}",
            ha="center", va="bottom", fontsize=8,
        )

    plt.tight_layout()
    chart_path = RESULTS_DIR / f"charts_{size_label}.png"
    plt.savefig(chart_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Gráficas guardadas en: {chart_path}")


# ─── CLI ─────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="Benchmark de formatos de almacenamiento.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python benchmark_cli.py --size 100k
  python benchmark_cli.py --size 1m --formats csv parquet_snappy parquet_gzip
        """,
    )
    parser.add_argument(
        "--size",
        required=True,
        choices=list(SIZE_MAP.keys()),
        help="Escala del dataset: 100k, 500k o 1m.",
    )
    parser.add_argument(
        "--formats",
        nargs="+",
        default=ALL_FORMATS,
        choices=ALL_FORMATS,
        metavar="FORMAT",
        help=(
            f"Formatos a comparar. Por defecto: todos. "
            f"Opciones: {', '.join(ALL_FORMATS)}"
        ),
    )
    return parser.parse_args()


def main():
    args = parse_args()
    size_label = args.size
    formats    = args.formats
    n          = SIZE_MAP[size_label]

    print("=" * 60)
    print(f"BENCHMARK DE FORMATOS — {size_label.upper()} ({n:,} filas)")
    print(f"Formatos: {', '.join(formats)}")
    print("=" * 60)

    # 1. Generamos los datos en memoria (NO cuenta como tiempo de escritura)
    print(f"\nGenerando {n:,} transacciones en memoria...")
    df = generate_transactions(n)
    print(f"Dataset listo: {len(df):,} filas × {len(df.columns)} columnas\n")

    # 2. Ejecutamos el benchmark
    print("Midiendo formatos:")
    DATA_DIR.mkdir(exist_ok=True)
    results = benchmark_all(formats, df, DATA_DIR, size_label)

    # 3. Mostramos tabla resumen
    print_table(results)

    # 4. Guardamos JSON con resultados
    save_results(results, size_label)

    # 5. Generamos gráficas
    print("Generando gráficas...")
    generate_charts(results, size_label)

    print("\nBenchmark completado.")


if __name__ == "__main__":
    main()
