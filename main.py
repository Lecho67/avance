"""Orquestador del pipeline ETL: Monitoreo del servicio de energía en ZNI (suroccidente colombiano).

Un solo comando reproduce todo desde cero (perfilado, extracción, silver, gold, carga y análisis exploratorio):

    python main.py                          # equivale a --etapa all
    python main.py --etapa perfilar         # perfilado de las 3 fuentes  -> logs/perfilado/*.csv
    python main.py --etapa extract          # API de Socrata              -> data/bronze
    python main.py --etapa silver           # limpieza y calidad          -> data/silver
    python main.py --etapa gold             # modelo analítico y KPI      -> data/gold
    python main.py --etapa load             # carga a PostgreSQL (gold)
    python main.py --etapa eda              # análisis exploratorio (Matplotlib) -> docs/eda
    python main.py --etapa all --incluir-silver   # además carga silver a PostgreSQL

Cada etapa captura sus errores sin tumbar el pipeline: se registran como errores controlados
(contador en src/__init__.py y en el KPI numero_errores_transformacion), se loguean en
logs/pipeline.log y las etapas que dependen de una etapa fallida se omiten. El código de salida
es 0 si no hubo errores y 1 si hubo al menos uno.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Callable

_RAIZ_PROYECTO = Path(__file__).resolve().parent
if str(_RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_PROYECTO))

from src import (  # noqa: E402
    obtener_errores_controlados,
    obtener_logger,
    registrar_error_controlado,
    reiniciar_errores_controlados,
)

LOGGER = obtener_logger("main", "pipeline.log")

ETAPAS = ["perfilar", "extract", "silver", "gold", "load", "eda"]
# Etapa de la que depende cada una cuando se corre todo junto: si falla, la siguiente se omite.
# El EDA lee gold (no la base de datos), así que no depende de que la carga a PostgreSQL haya salido bien.
PREREQUISITO = {"silver": "extract", "gold": "silver", "load": "gold", "eda": "gold"}


def etapa_perfilar(**_: object) -> str:
    """Perfila las tres fuentes (columnas, llaves, formatos DANE, duplicados, cruces)."""
    from src.extract import profile_sources

    profile_sources.main()
    return "perfilado escrito en logs/perfilado"


def etapa_extract(**_: object) -> str:
    """Extrae las tres fuentes desde la API de Socrata hacia bronze."""
    from src.extract.extract_excel import extraer_todas

    resultados, fallidas = extraer_todas()
    if fallidas:
        raise RuntimeError(f"fuentes sin extraer: {fallidas}")
    return ", ".join(f"{fuente}={filas}" for fuente, filas in resultados.items()) + " filas"


def etapa_silver(**_: object) -> str:
    """Limpia las tres fuentes (bronze -> silver) y corre las pruebas de calidad sobre silver."""
    import pandas as pd

    from src.transform.clean_excel import RUTA_SILVER, limpiar_todas
    from src.transform.quality_checks import diagnosticar_silver

    resultados, fallidas = limpiar_todas()
    if fallidas:
        raise RuntimeError(f"fuentes sin limpiar: {fallidas}")
    silver = {fuente: pd.read_parquet(RUTA_SILVER / f"{fuente}.parquet") for fuente in resultados}
    pruebas = diagnosticar_silver(silver)
    no_aprobadas = [p for p in pruebas if not p["aprobado"] and not p["informativa"]]
    for p in no_aprobadas:
        LOGGER.warning("Prueba de calidad no aprobada en silver: %s %s (%s) = %s%%", p["fuente"], p["prueba"], p["objeto"], p["metrica"])
    filas = ", ".join(f"{fuente}={datos['filas_silver']}" for fuente, datos in resultados.items())
    return f"{filas} filas; pruebas de calidad: {len(pruebas) - len(no_aprobadas)}/{len(pruebas)} aprobadas o informativas"


def etapa_gold(**_: object) -> str:
    """Construye el modelo gold (con pruebas de calidad antes de cada unión) y los KPI."""
    from src.transform.gold_transformations import ejecutar_gold

    resultado = ejecutar_gold()
    kpis = resultado.tablas["kpis_pipeline"]
    incumplidos = kpis.loc[~kpis["cumple"], "indicador"].tolist()
    uniones = ", ".join(f"{u['union']}={u['resultado_union']}" for u in resultado.resumen_uniones)
    estado_kpi = "todos los KPI cumplen su meta" if not incumplidos else f"KPI que no cumplen: {incumplidos}"
    return f"{len(resultado.tablas)} tablas; {estado_kpi}; uniones: {uniones}"


def etapa_load(incluir_silver: bool = False, **_: object) -> str:
    """Carga gold (y opcionalmente silver) a PostgreSQL."""
    from src.load.load_database import ejecutar_carga

    cargadas = ejecutar_carga(incluir_silver=incluir_silver)
    return f"{len(cargadas)} tablas, {sum(cargadas.values())} filas"


def etapa_eda(**_: object) -> str:
    """Análisis exploratorio sobre gold: figuras (Matplotlib), tablas de apoyo y hallazgos en docs/eda."""
    from src.eda.run_eda import ejecutar_eda

    resumen = ejecutar_eda()
    return f"{len(resumen['figuras'])} figuras y {len(resumen['tablas'])} tablas en docs/eda"


FUNCIONES_ETAPA: dict[str, Callable[..., str]] = {
    "perfilar": etapa_perfilar,
    "extract": etapa_extract,
    "silver": etapa_silver,
    "gold": etapa_gold,
    "load": etapa_load,
    "eda": etapa_eda,
}


def ejecutar_etapas(etapas: list[str], incluir_silver: bool = False) -> dict[str, dict]:
    """Ejecuta las etapas en orden. Un fallo se registra como error controlado; las etapas que
    dependen de una etapa fallida de esta misma corrida se omiten. Devuelve el resultado por etapa."""
    resultados: dict[str, dict] = {}
    for etapa in etapas:
        prerequisito = PREREQUISITO.get(etapa)
        if prerequisito in resultados and resultados[prerequisito]["estado"] != "ok":
            resultados[etapa] = {"estado": "omitida", "detalle": f"depende de '{prerequisito}', que no terminó bien", "segundos": 0.0}
            LOGGER.warning("Etapa '%s' omitida: depende de '%s', que no terminó bien.", etapa, prerequisito)
            continue
        LOGGER.info("=== Etapa '%s' ===", etapa)
        inicio = time.perf_counter()
        try:
            detalle = FUNCIONES_ETAPA[etapa](incluir_silver=incluir_silver)
            estado = "ok"
        except Exception as error:  # noqa: BLE001 - error controlado: no tumba el pipeline
            detalle, estado = str(error), "error"
            registrar_error_controlado(etapa, detalle)
            LOGGER.error("Etapa '%s' falló (error controlado): %s", etapa, detalle)
        segundos = time.perf_counter() - inicio
        resultados[etapa] = {"estado": estado, "detalle": detalle, "segundos": round(segundos, 1)}
        LOGGER.info("Etapa '%s': %s (%.1f s) - %s", etapa, estado, segundos, detalle)
    return resultados


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada. Devuelve el código de salida (0 sin errores, 1 con errores controlados)."""
    parser = argparse.ArgumentParser(description="Pipeline ETL de energía en ZNI (suroccidente colombiano).")
    parser.add_argument("--etapa", choices=[*ETAPAS, "all"], default="all", help="Etapa a ejecutar (por defecto: all).")
    parser.add_argument("--incluir-silver", action="store_true", help="En la etapa load, cargar también silver a PostgreSQL.")
    args = parser.parse_args(argv)

    reiniciar_errores_controlados()
    etapas = ETAPAS if args.etapa == "all" else [args.etapa]
    LOGGER.info("Inicio del pipeline. Etapas: %s", etapas)
    resultados = ejecutar_etapas(etapas, incluir_silver=args.incluir_silver)

    errores = obtener_errores_controlados()
    print("\nResumen del pipeline")
    print("--------------------")
    for etapa, datos in resultados.items():
        print(f"{etapa:9s} {datos['estado']:8s} {datos['segundos']:7.1f} s  {datos['detalle']}")
    print(f"\nErrores controlados: {len(errores)}")
    for error in errores:
        print(f"  - [{error['etapa']}] {error['detalle']}")
    LOGGER.info("Fin del pipeline. Errores controlados: %s", len(errores))
    return 1 if errores else 0


if __name__ == "__main__":
    sys.exit(main())
