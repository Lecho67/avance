"""Utilidades compartidas del pipeline ETL: carga de configuración y logging.

Proyecto: Monitoreo del servicio de energía en ZNI (suroccidente colombiano).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

RAIZ_PROYECTO = Path(__file__).resolve().parent.parent
RUTA_CONFIG = RAIZ_PROYECTO / "config" / "config.yaml"
RUTA_LOGS = RAIZ_PROYECTO / "logs"

load_dotenv(RAIZ_PROYECTO / ".env")


def cargar_configuracion(ruta: Path = RUTA_CONFIG) -> dict[str, Any]:
    """Carga config/config.yaml y devuelve su contenido como diccionario."""
    with open(ruta, "r", encoding="utf-8") as archivo:
        return yaml.safe_load(archivo) or {}


def obtener_url_base_datos() -> str:
    """Arma la URL de conexión a PostgreSQL desde DATABASE_URL o, si no está definida, desde las variables PG_*."""
    url = os.getenv("DATABASE_URL", "").strip()
    if url:
        return url
    host = os.getenv("PG_HOST", "localhost")
    puerto = os.getenv("PG_PORT", "5432")
    base_datos = os.getenv("PG_DATABASE", "postgres")
    usuario = os.getenv("PG_USER", "postgres")
    clave = os.getenv("PG_PASSWORD", "")
    return f"postgresql+psycopg2://{usuario}:{clave}@{host}:{puerto}/{base_datos}"


def obtener_token_socrata() -> str | None:
    """Devuelve el token opcional de la API de Socrata (datos.gov.co), si está configurado."""
    token = os.getenv("SOCRATA_APP_TOKEN", "").strip()
    return token or None


_ERRORES_CONTROLADOS: list[dict[str, str]] = []


def registrar_error_controlado(etapa: str, detalle: str) -> None:
    """Registra un error de transformación que fue capturado sin tumbar el pipeline."""
    _ERRORES_CONTROLADOS.append({"etapa": etapa, "detalle": detalle})


def obtener_errores_controlados() -> list[dict[str, str]]:
    """Devuelve (una copia de) los errores controlados registrados en esta corrida."""
    return list(_ERRORES_CONTROLADOS)


def reiniciar_errores_controlados() -> None:
    """Vacía el contador de errores controlados (se llama al iniciar una corrida completa)."""
    _ERRORES_CONTROLADOS.clear()


def obtener_logger(nombre: str, archivo: str | None = None) -> logging.Logger:
    """Crea (o recupera) un logger que escribe en consola y en logs/<archivo>.log.

    Los mensajes de log del proyecto se redactan en español, siguiendo la convención
    acordada para comentarios, docstrings y nombres de la capa gold.
    """
    RUTA_LOGS.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(nombre)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    formato = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")

    manejador_consola = logging.StreamHandler()
    manejador_consola.setFormatter(formato)
    logger.addHandler(manejador_consola)

    ruta_archivo = RUTA_LOGS / (archivo or f"{nombre}.log")
    manejador_archivo = logging.FileHandler(ruta_archivo, encoding="utf-8")
    manejador_archivo.setFormatter(formato)
    logger.addHandler(manejador_archivo)

    return logger
