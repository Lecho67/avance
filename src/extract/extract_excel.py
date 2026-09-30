"""Extracción de las tres fuentes ZNI hacia la capa bronze (data/bronze/*.parquet).

El nombre del módulo viene de la plantilla del curso; las tres fuentes en realidad se
extraen por la API de Socrata (datos.gov.co), no desde Excel. Como respaldo, si la API
falla tras agotar los reintentos, se busca un archivo descargado a mano en
data/bronze/manual/<fuente>.csv o data/bronze/manual/<fuente>.xlsx.

Bronze guarda los datos tal como llegan (todas las columnas de origen como texto; la
tipificación es trabajo de silver), más las columnas de trazabilidad _fuente_id,
_fecha_carga, _fecha_corte_fuente y _lote_id. Cada corrida SOBREESCRIBE el parquet de
cada fuente (no se acumula): el pipeline es idempotente, correr dos veces con los mismos
datos de origen produce el mismo resultado.

Uso (desde la raíz del proyecto, con el entorno virtual activado):
    python src/extract/extract_excel.py                     # extrae las tres fuentes
    python src/extract/extract_excel.py --fuente prestacion  # extrae solo una
"""
from __future__ import annotations

import argparse
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests

_RAIZ_PROYECTO = Path(__file__).resolve().parent.parent.parent
if str(_RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_PROYECTO))

from src import cargar_configuracion, obtener_logger, obtener_token_socrata  # noqa: E402

CONFIG = cargar_configuracion()
LOGGER = obtener_logger("extract_excel", "extract.log")

BASE_URL: str = CONFIG["api"]["base_url"]
LIMITE_PAGINA: int = CONFIG["api"]["limite_pagina"]
REINTENTOS_MAXIMOS: int = CONFIG["api"]["reintentos_maximos"]
BACKOFF_BASE: float = CONFIG["api"]["backoff_segundos_base"]
RUTA_BRONZE = Path(CONFIG["rutas"]["bronze"])
RUTA_MANUAL = RUTA_BRONZE / "manual"


def solicitar(url: str, parametros: dict[str, Any] | None = None) -> Any:
    """Hace un GET con reintentos y backoff exponencial; agrega el token de Socrata si existe en .env."""
    encabezados = {}
    token = obtener_token_socrata()
    if token:
        encabezados["X-App-Token"] = token

    ultimo_error: Exception | None = None
    for intento in range(1, REINTENTOS_MAXIMOS + 1):
        try:
            respuesta = requests.get(url, params=parametros, headers=encabezados, timeout=120)
            respuesta.raise_for_status()
            return respuesta.json()
        except requests.RequestException as error:
            ultimo_error = error
            espera = BACKOFF_BASE * (2 ** (intento - 1))
            LOGGER.warning(
                "Intento %s/%s fallido para %s (%s). Reintentando en %ss.",
                intento, REINTENTOS_MAXIMOS, url, error, espera,
            )
            if intento < REINTENTOS_MAXIMOS:
                time.sleep(espera)
    raise RuntimeError(f"No se pudo consultar {url} tras {REINTENTOS_MAXIMOS} intentos") from ultimo_error


def obtener_fecha_corte(id_fuente: str) -> datetime:
    """Consulta /api/views/{id}.json y devuelve rowsUpdatedAt (última actualización real) como fecha UTC."""
    metadatos = solicitar(f"{BASE_URL}/api/views/{id_fuente}.json")
    return datetime.fromtimestamp(metadatos["rowsUpdatedAt"], tz=timezone.utc)


def extraer_paginado(id_fuente: str) -> pd.DataFrame:
    """Trae todas las filas de una fuente Socrata paginando con $limit/$offset, ordenado por :id
    (el identificador interno de fila de Socrata) para que la paginación sea estable."""
    filas_totales: list[dict[str, Any]] = []
    offset = 0
    while True:
        pagina = solicitar(f"{BASE_URL}/resource/{id_fuente}.json", {
            "$limit": LIMITE_PAGINA,
            "$offset": offset,
            "$order": ":id",
        })
        if not pagina:
            break
        filas_totales.extend(pagina)
        LOGGER.info("  página offset=%s: %s filas (acumulado %s)", offset, len(pagina), len(filas_totales))
        if len(pagina) < LIMITE_PAGINA:
            break
        offset += LIMITE_PAGINA
    return pd.DataFrame(filas_totales)


def leer_respaldo_manual(nombre_fuente: str) -> pd.DataFrame | None:
    """Lee un archivo descargado a mano (data/bronze/manual/<fuente>.csv|.xlsx) si existe; si no, None."""
    ruta_csv = RUTA_MANUAL / f"{nombre_fuente}.csv"
    ruta_xlsx = RUTA_MANUAL / f"{nombre_fuente}.xlsx"
    if ruta_csv.exists():
        LOGGER.info("Usando respaldo manual: %s", ruta_csv)
        return pd.read_csv(ruta_csv, dtype=str, encoding="utf-8-sig")
    if ruta_xlsx.exists():
        LOGGER.info("Usando respaldo manual: %s", ruta_xlsx)
        return pd.read_excel(ruta_xlsx, dtype=str)
    return None


def generar_lote_id() -> str:
    """Genera un identificador de lote único para trazar todas las filas de una misma corrida de extracción."""
    return f"{datetime.now(tz=timezone.utc):%Y%m%dT%H%M%S}_{uuid.uuid4().hex[:8]}"


def agregar_columnas_trazabilidad(
    df: pd.DataFrame, id_fuente: str, fecha_corte: datetime | None, lote_id: str,
) -> pd.DataFrame:
    """Castea las columnas de origen a texto (silver tipifica) y agrega las columnas de trazabilidad."""
    df = df.astype("string")
    df["_fuente_id"] = id_fuente
    df["_fecha_carga"] = pd.Timestamp.now(tz="UTC")
    df["_fecha_corte_fuente"] = pd.Timestamp(fecha_corte) if fecha_corte is not None else pd.NaT
    df["_lote_id"] = lote_id
    return df


def extraer_fuente(nombre_fuente: str, id_fuente: str, lote_id: str) -> int:
    """Extrae una fuente (API, con respaldo manual) y escribe data/bronze/<fuente>.parquet.

    Devuelve el número de filas escritas.
    """
    LOGGER.info("Extrayendo fuente '%s' (id=%s)...", nombre_fuente, id_fuente)
    try:
        fecha_corte = obtener_fecha_corte(id_fuente)
        df = extraer_paginado(id_fuente)
    except RuntimeError as error:
        LOGGER.error("Falló la extracción por API de '%s': %s. Buscando respaldo manual...", nombre_fuente, error)
        df = leer_respaldo_manual(nombre_fuente)
        if df is None:
            raise RuntimeError(
                f"No se pudo extraer '{nombre_fuente}' por API ni encontrar respaldo manual en {RUTA_MANUAL}"
            ) from error
        # No se conoce la fecha de corte real de un archivo puesto a mano: se deja en blanco
        # en vez de inventar una (no se asume que está "al día").
        fecha_corte = None

    df = agregar_columnas_trazabilidad(df, id_fuente, fecha_corte, lote_id)

    RUTA_BRONZE.mkdir(parents=True, exist_ok=True)
    ruta_salida = RUTA_BRONZE / f"{nombre_fuente}.parquet"
    df.to_parquet(ruta_salida, index=False, engine="pyarrow")
    LOGGER.info("  %s: %s filas escritas en %s", nombre_fuente, len(df), ruta_salida)
    return len(df)


def main() -> None:
    """Punto de entrada de línea de comandos: extrae una fuente o las tres hacia bronze."""
    parser = argparse.ArgumentParser(description="Extracción Socrata hacia la capa bronze.")
    parser.add_argument(
        "--fuente", choices=list(CONFIG["fuentes"]), default=None,
        help="Extraer solo esta fuente (por defecto, las tres).",
    )
    args = parser.parse_args()

    lote_id = generar_lote_id()
    LOGGER.info("Iniciando extracción. lote_id=%s", lote_id)

    fuentes = (
        {args.fuente: CONFIG["fuentes"][args.fuente]["id"]}
        if args.fuente
        else {nombre: datos["id"] for nombre, datos in CONFIG["fuentes"].items()}
    )

    errores = 0
    for nombre, id_fuente in fuentes.items():
        try:
            extraer_fuente(nombre, id_fuente, lote_id)
        except Exception:
            errores += 1
            LOGGER.exception("Error extrayendo '%s'", nombre)

    if errores:
        LOGGER.error("Extracción completa con %s fuente(s) fallida(s).", errores)
        sys.exit(1)
    LOGGER.info("Extracción completa sin errores.")


if __name__ == "__main__":
    main()
