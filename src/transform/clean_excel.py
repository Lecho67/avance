"""Limpieza silver de las tres fuentes ZNI (data/bronze/*.parquet -> data/silver/*.parquet).

El nombre del módulo viene de la plantilla del curso (ver src/extract/extract_excel.py).

Por fuente: normaliza los códigos DANE con ceros a la izquierda, tipifica las columnas
numéricas y de fecha, filtra por los 4 departamentos del alcance (Valle del Cauca, Cauca,
Nariño, Putumayo) y elimina duplicados EXACTOS (todas las columnas de origen iguales).

Cuando varias filas comparten la llave de una fuente pero tienen valores distintos no se
colapsan aquí: en prestacion resultó que son localidades distintas que comparten un código
DANE (la llave real incluye el nombre normalizado), y en operacion_diaria/pqr son
generadores o casos individuales. Combinarlos es trabajo de gold.

Cada registro lleva _reglas_aplicadas: la lista de reglas que se le aplicaron (las de base,
que tocan a todos los registros, más las condicionales que modificaron ese registro).

Uso (desde la raíz del proyecto, con el entorno virtual activado):
    python src/transform/clean_excel.py                     # limpia las tres fuentes
    python src/transform/clean_excel.py --fuente prestacion  # limpia solo una
"""
from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

_RAIZ_PROYECTO = Path(__file__).resolve().parent.parent.parent
if str(_RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_PROYECTO))

from src import cargar_configuracion, obtener_logger, registrar_error_controlado  # noqa: E402

CONFIG = cargar_configuracion()
LOGGER = obtener_logger("clean_excel", "clean.log")

RUTA_BRONZE = Path(CONFIG["rutas"]["bronze"])
RUTA_SILVER = Path(CONFIG["rutas"]["silver"])
ARCHIVO_ESTADISTICAS = RUTA_SILVER / "_estadisticas_limpieza.json"
COLUMNAS_TRAZABILIDAD = ["_fuente_id", "_fecha_carga", "_fecha_corte_fuente", "_lote_id"]
REGLAS_BASE = ["tipificacion_columnas", "filtro_departamentos_alcance", "deduplicacion_exacta"]
# Sufijo final "(MUNICIPIO - DEPARTAMENTO)" que prestacion agrega al nombre de la localidad.
# Admite un nivel de paréntesis anidado, p. ej. "NOANAMITO (LÓPEZ (MICAY) - CAUCA)".
PATRON_SUFIJO_GEOGRAFICO = r"\s*\((?:[^()]|\([^()]*\))*\s-\s(?:[^()]|\([^()]*\))*\)\s*$"


def normalizar_codigo_dane(serie: pd.Series, longitud: int) -> tuple[pd.Series, pd.Series]:
    """Rellena con ceros a la izquierda hasta `longitud` los valores puramente numéricos.

    Devuelve (serie normalizada, máscara de qué filas SÍ cambiaron) para alimentar
    _reglas_aplicadas.
    """
    texto = serie.astype("string").str.strip()
    es_numerico = texto.str.fullmatch(r"\d+").fillna(False)
    normalizado = texto.where(~es_numerico, texto.str.zfill(longitud))
    cambio = (normalizado.ne(texto) & texto.notna()).fillna(False).astype(bool)
    return normalizado, cambio


def normalizar_nombre_localidad(serie: pd.Series) -> pd.Series:
    """Nombre de localidad sin el sufijo final '(MUNICIPIO - DEPARTAMENTO)', sin tildes, en
    mayúsculas y sin puntuación. Los paréntesis internos se conservan (p. ej. '(TABLÓN SALADO)')."""
    texto = serie.astype("string")
    sin_sufijo = texto.str.replace(PATRON_SUFIJO_GEOGRAFICO, "", regex=True)
    sin_tildes = sin_sufijo.map(
        lambda t: unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode("ascii"),
        na_action="ignore",
    ).astype("string")
    limpio = sin_tildes.str.upper().str.replace(r"[^A-Z0-9 ]+", " ", regex=True)
    return limpio.str.replace(r"\s+", " ", regex=True).str.strip()


def construir_reglas_aplicadas(
    indice: pd.Index, base: list[str], condicionales: dict[str, pd.Series] | None = None,
) -> pd.Series:
    """Arma _reglas_aplicadas: la lista de base (igual para todas las filas) más, por fila,
    los nombres de las reglas condicionales cuya máscara booleana es verdadera."""
    listas: list[list[str]] = [list(base) for _ in range(len(indice))]
    for nombre_regla, mascara in (condicionales or {}).items():
        for i in np.flatnonzero(mascara.to_numpy(dtype=bool)):
            listas[i].append(nombre_regla)
    return pd.Series(listas, index=indice, dtype="object")


def filtrar_departamentos(df: pd.DataFrame, columna_mpio: str) -> pd.DataFrame:
    """Conserva solo las filas cuyo código de municipio empieza por uno de los 4 departamentos del alcance."""
    departamentos = set(CONFIG["geografia"]["departamentos_dane"].values())
    prefijo = df[columna_mpio].astype("string").str[:2]
    return df[prefijo.isin(departamentos)].copy()


def remover_duplicados_exactos(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Elimina filas donde TODAS las columnas de datos de origen (sin contar trazabilidad
    ni _reglas_aplicadas) son idénticas. Devuelve (df sin duplicados, cuántas se eliminaron)."""
    columnas_datos = [c for c in df.columns if c not in COLUMNAS_TRAZABILIDAD and c != "_reglas_aplicadas"]
    antes = len(df)
    df_sin_duplicados = df.drop_duplicates(subset=columnas_datos, keep="first")
    return df_sin_duplicados, antes - len(df_sin_duplicados)


def _cierre_comun(df: pd.DataFrame, nombre: str, columna_mpio: str, entrada: int) -> pd.DataFrame:
    """Filtro por departamento + duplicados exactos + orden determinista, y deja las
    estadísticas de la limpieza en df.attrs para el KPI de duplicados."""
    df = filtrar_departamentos(df, columna_mpio)
    tras_filtro = len(df)
    df, duplicados = remover_duplicados_exactos(df)
    llave = [c for c in CONFIG["fuentes"][nombre]["campos_llave"] if c in df.columns]
    df = df.sort_values(llave, kind="stable").reset_index(drop=True)
    df.attrs["estadisticas"] = {
        "filas_bronze": entrada,
        "filas_fuera_de_alcance": entrada - tras_filtro,
        "duplicados_exactos_eliminados": duplicados,
        "filas_silver": len(df),
    }
    if duplicados:
        LOGGER.info("  %s: %s filas exactamente duplicadas eliminadas", nombre, duplicados)
    return df


def limpiar_prestacion(df: pd.DataFrame) -> pd.DataFrame:
    """Limpieza silver de prestacion (3ebi-d83g)."""
    df = df.copy()
    entrada = len(df)

    df["id_dpto"], cambio_dpto = normalizar_codigo_dane(df["id_dpto"], CONFIG["codigos_dane"]["longitud_departamento"])
    df["id_mpio"], cambio_mpio = normalizar_codigo_dane(df["id_mpio"], CONFIG["codigos_dane"]["longitud_municipio"])
    df["id_localidad"], cambio_loc = normalizar_codigo_dane(df["id_localidad"], CONFIG["codigos_dane"]["longitud_localidad"])

    # Una fila trae id_dpto='00' aunque su municipio es de Cauca: el departamento es el
    # prefijo de 2 dígitos del municipio.
    prefijo = df["id_mpio"].str[:2]
    dpto_corregido = (df["id_dpto"].ne(prefijo) & prefijo.notna()).fillna(False).astype(bool)
    df["id_dpto"] = df["id_dpto"].where(~dpto_corregido, prefijo)

    df["localidad_nombre_normalizado"] = normalizar_nombre_localidad(df["localidad"])

    df["anio"] = pd.to_numeric(df["anio"], errors="coerce").astype("Int64")
    df["mes"] = pd.to_numeric(df["mes"], errors="coerce").astype("Int64")
    for columna in ("energia_activa", "energia_reactiva", "potencia_maxima", "prom_diario_horas"):
        df[columna] = pd.to_numeric(df[columna], errors="coerce")
    df["fecha_demanda_maxima"] = pd.to_datetime(df["fecha_demanda_maxima"], errors="coerce")

    df["_reglas_aplicadas"] = construir_reglas_aplicadas(
        df.index,
        REGLAS_BASE + ["localidad_nombre_normalizado"],
        {"dane_normalizado": cambio_dpto | cambio_mpio | cambio_loc, "dane_departamento_corregido": dpto_corregido},
    )
    return _cierre_comun(df, "prestacion", "id_mpio", entrada)


def limpiar_operacion_diaria(df: pd.DataFrame) -> pd.DataFrame:
    """Limpieza silver de operacion_diaria (qwe5-ycap).

    codigo_localidad tiene 13 dígitos (municipio 5 + centro poblado 3 + consecutivo 5), no
    el id_localidad de 8 dígitos de prestacion. Se deriva id_mpio con sus primeros 5 dígitos.
    """
    df = df.copy()
    entrada = len(df)

    df["codigo_localidad"], cambio_codigo = normalizar_codigo_dane(
        df["codigo_localidad"], CONFIG["codigos_dane"]["longitud_codigo_operacion"],
    )
    df["id_mpio"] = df["codigo_localidad"].str.slice(0, CONFIG["codigos_dane"]["longitud_municipio"])

    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    df["ano"] = pd.to_numeric(df["ano"], errors="coerce").astype("Int64")
    df["periodo"] = pd.to_numeric(df["periodo"], errors="coerce").astype("Int64")
    for columna in ("energia_generada", "horometro", "capacidad_generacion", "tiempo_servicio"):
        df[columna] = pd.to_numeric(df[columna], errors="coerce")
    df["identificador_empresa"] = df["identificador_empresa"].astype("string")

    df["_reglas_aplicadas"] = construir_reglas_aplicadas(
        df.index,
        REGLAS_BASE + ["municipio_derivado_de_codigo_localidad"],
        {"dane_normalizado": cambio_codigo},
    )
    return _cierre_comun(df, "operacion_diaria", "id_mpio", entrada)


def limpiar_pqr(df: pd.DataFrame) -> pd.DataFrame:
    """Limpieza silver de pqr (5wua-nr2d).

    HALLAZGO (perfilado 2026-09-30, ver config.yaml): are_esp_nombre / identificador_empresa
    en esta fuente son de empresas de GAS, no operadores eléctricos de ZNI. Se mantiene la
    fuente pero solo podrá unirse por municipio, nunca por empresa (0% de cruce real).

    car_t1554_dane_mpio no trae el prefijo de departamento por sí solo: id_mpio se compone
    con car_t1554_dane_depto (2 dígitos) + car_t1554_dane_mpio (3 dígitos).
    car_carg_periodo es el MES de carga (1-12), no el semestre: se deriva la columna
    semestre (1 = ene-jun, 2 = jul-dic).
    """
    df = df.copy()
    entrada = len(df)

    df["car_t1554_dane_depto"], cambio_depto = normalizar_codigo_dane(df["car_t1554_dane_depto"], 2)
    df["car_t1554_dane_mpio"], cambio_mpio = normalizar_codigo_dane(df["car_t1554_dane_mpio"], 3)
    df["id_mpio"] = df["car_t1554_dane_depto"].str.cat(df["car_t1554_dane_mpio"])

    df["car_carg_ano"] = pd.to_numeric(df["car_carg_ano"], errors="coerce").astype("Int64")
    df["car_carg_periodo"] = pd.to_numeric(df["car_carg_periodo"], errors="coerce").astype("Int64")
    df["semestre"] = ((df["car_carg_periodo"] - 1) // 6 + 1).astype("Int64")

    for columna in ("rad_fecha", "respuesta_fecha", "notifica_fecha", "fecha_traslado"):
        df[columna] = pd.to_datetime(df[columna], errors="coerce")
    df["identificador_empresa"] = df["identificador_empresa"].astype("string")

    df["_reglas_aplicadas"] = construir_reglas_aplicadas(
        df.index,
        REGLAS_BASE + ["municipio_compuesto_depto_mpio", "semestre_derivado_de_mes_carga"],
        {"dane_normalizado": cambio_depto | cambio_mpio},
    )
    return _cierre_comun(df, "pqr", "id_mpio", entrada)


LIMPIADORES: dict[str, Callable[[pd.DataFrame], pd.DataFrame]] = {
    "prestacion": limpiar_prestacion,
    "operacion_diaria": limpiar_operacion_diaria,
    "pqr": limpiar_pqr,
}


def limpiar_fuente(nombre_fuente: str) -> dict[str, int]:
    """Lee data/bronze/<fuente>.parquet, aplica su limpieza y escribe data/silver/<fuente>.parquet.

    Devuelve las estadísticas de la limpieza (filas de entrada/salida, descartes, duplicados).
    """
    ruta_bronze = RUTA_BRONZE / f"{nombre_fuente}.parquet"
    if not ruta_bronze.exists():
        raise FileNotFoundError(f"No existe {ruta_bronze}; corre la etapa extract primero.")

    df_bronze = pd.read_parquet(ruta_bronze)
    LOGGER.info("Limpiando fuente '%s': %s filas en bronze", nombre_fuente, len(df_bronze))

    df_silver = LIMPIADORES[nombre_fuente](df_bronze)
    estadisticas = dict(df_silver.attrs["estadisticas"])

    RUTA_SILVER.mkdir(parents=True, exist_ok=True)
    ruta_salida = RUTA_SILVER / f"{nombre_fuente}.parquet"
    df_silver.to_parquet(ruta_salida, index=False, engine="pyarrow")
    LOGGER.info(
        "  %s: %s filas en silver (%s fuera de alcance, %s duplicados exactos) -> %s",
        nombre_fuente, estadisticas["filas_silver"], estadisticas["filas_fuera_de_alcance"],
        estadisticas["duplicados_exactos_eliminados"], ruta_salida,
    )
    return estadisticas


def _guardar_estadisticas(nuevas: dict[str, dict[str, int]]) -> None:
    """Fusiona las estadísticas de limpieza con las ya guardadas (para correr una sola fuente)."""
    actuales: dict[str, dict[str, int]] = {}
    if ARCHIVO_ESTADISTICAS.exists():
        actuales = json.loads(ARCHIVO_ESTADISTICAS.read_text(encoding="utf-8"))
    actuales.update(nuevas)
    ARCHIVO_ESTADISTICAS.write_text(json.dumps(actuales, indent=2, sort_keys=True), encoding="utf-8")


def limpiar_todas(fuentes: list[str] | None = None) -> tuple[dict[str, dict[str, int]], list[str]]:
    """Limpia las fuentes indicadas (o las tres). Un fallo en una fuente se registra como error
    controlado y no detiene a las demás. Devuelve (estadísticas por fuente, fuentes fallidas)."""
    resultados: dict[str, dict[str, int]] = {}
    fallidas: list[str] = []
    for nombre in fuentes or list(LIMPIADORES):
        try:
            resultados[nombre] = limpiar_fuente(nombre)
        except Exception as error:  # noqa: BLE001 - se captura para no tumbar el pipeline
            fallidas.append(nombre)
            registrar_error_controlado("silver", f"{nombre}: {error}")
            LOGGER.exception("Error limpiando '%s'", nombre)
    if resultados:
        _guardar_estadisticas(resultados)
    return resultados, fallidas


def main() -> None:
    """Punto de entrada de línea de comandos: limpia una fuente o las tres hacia silver."""
    parser = argparse.ArgumentParser(description="Limpieza silver de las fuentes ZNI.")
    parser.add_argument(
        "--fuente", choices=list(LIMPIADORES), default=None,
        help="Limpiar solo esta fuente (por defecto, las tres).",
    )
    args = parser.parse_args()

    _, fallidas = limpiar_todas([args.fuente] if args.fuente else None)
    if fallidas:
        LOGGER.error("Limpieza completa con %s fuente(s) fallida(s): %s", len(fallidas), fallidas)
        sys.exit(1)
    LOGGER.info("Limpieza completa sin errores.")


if __name__ == "__main__":
    main()
