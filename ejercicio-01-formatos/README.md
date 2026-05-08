# Módulo — Python para Sistemas de Datos Modernos

## Ejercicio 1 — Formatos Bajo la Lupa

### Requisitos
- Python 3.11+
- uv (`curl -Lsf https://astral.sh/uv/install.sh | sh`)

### Instalación
```bash
uv sync
```

### Cómo correr
```bash
cd ejercicio-01-formatos

# Generar datos
uv run python generate_data.py --size 1m

# Correr benchmark
uv run python benchmark_cli.py --size 1m --formats csv parquet_none parquet_snappy parquet_gzip
```

Los resultados quedan en `ejercicio-01-formatos/results/`.
