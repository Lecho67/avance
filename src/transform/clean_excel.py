"""Limpieza silver de las tres fuentes ZNI (data/bronze/*.parquet -> data/silver/*.parquet).

El nombre del módulo viene de la plantilla del curso (ver src/extract/extract_excel.py).

Por fuente: normaliza los códigos DANE con ceros a la izquierda, tipifica las columnas
numéricas y de fecha, filtra por los 4 departamentos del alcance (Valle del Cauca, Cauca,
Nariño, Putumayo) y elimina duplicados EXACTOS (todas las columnas de origen iguales).

Cuando varias filas comparten la llave candidata de una fuente pero tienen valores
distintos (confirmado en el perfilado para prestacion, operacion_diaria y pqr: ver
config.yaml), NO se decide aquí cómo combinarlas (sumar, promediar, quedarse con una):
eso es una decisión de modelado que le corresponde a quien construya gold
(gold_transformations.py, Fase 4). Esta capa las deja tal cual y lo documenta con
_reglas_aplicadas; la prueba probar_unicidad_llave de quality_checks.py lo reporta.

Uso (desde la raíz del proyecto, con el entorno virtual activado):
    python src/transform/clean_excel.py                     # limpia las tres fuentes
    python src/transform/clean_excel.py --fuente prestacion  # limpia solo una
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

_RAIZ_PROYECTO = Path(__file__).resolve().parent.parent.parent
if str(_RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_PROYECTO))

from src import cargar_configuracion, obtener_logger  # noqa: E402

CONFIG = cargar_configuracion()
LOGGER = obtener_logger("clean_excel", "clean.log")

RUTA_BRONZE = Path(CONFIG["rutas"]["bronze"])
RUTA_SILVER = Path(CONFIG["rutas"]["silver"])
COLUMNAS_TRAZABILIDAD = ["_fuente_id", "_fecha_carga", "_fecha_corte_fuente", "_lote_id"]


def normalizar_codigo_dane(serie: pd.Series, longitud: int) -> tuple[pd.Series, pd.Series]:
    """Rellena con ceros a la izquierda hasta `longitud` los valores puramente numéricos.

    Devuelve (serie normalizada, máscara de qué filas SÍ cambiaron) para alimentar
    _reglas_aplicadas.
    """
    texto = serie.astype("string").str.strip()
    es_numerico = texto.str.fullmatch(r"\d+").fillna(False)
    normalizado = texto.where(~es_numerico, texto.str.zfill(longitud))
    cambio = normalizado.ne(texto) & texto.notna()
    return normalizado, cambio


def longitud_modal(serie: pd.Series) -> int:
    """Longitud (en dígitos) más frecuente entre los valores puramente numéricos de la serie."""
    valores = serie.dropna().astype(str)
    valores = valores[valores.str.fullmatch(r"\d+")]
    if valores.empty:
        return 0
    return int(valores.str.len().mode().iloc[0])


def construir_reglas_aplicadas(*banderas: tuple[str, pd.Series]) -> pd.Series:
    """Arma la columna _reglas_aplicadas: lista de nombres de regla por fila, a partir de
    pares (nombre_regla, máscara_booleana) que indican si esa regla tocó la fila."""
    if not banderas:
        return pd.Series(dtype="object")
    n = len(banderas[0][1])
    listas: list[list[str]] = [[] for _ in range(n)]
    for nombre_regla, mascara in banderas:
        for i, aplica in enumerate(mascara.to_numpy()):
            if aplica:
                listas[i].append(nombre_regla)
    return pd.Series(listas, index=banderas[0][1].index)


def filtrar_departamentos(df: pd.DataFrame, columna_mpio: str) -> pd.DataFrame:
    """Conserva solo las filas cuyo código de municipio empieza por uno de los 4 departamentos del alcance."""
    departamentos = set(CONFIG["geografia"]["departamentos_dane"].values())
    prefijo = df[columna_mpio].astype("string").str[:2]
    return df[prefijo.isin(departamentos)].copy()


def remover_duplicados_exactos(df: pd.DataFrame, nombre_fuente: str) -> pd.DataFrame:
    """Elimina filas donde TODAS las columnas de datos de origen (sin contar trazabilidad
    ni _reglas_aplicadas) son idénticas. No colapsa filas que comparten llave pero tienen
    valores distintos (ver docstring del módulo)."""
    columnas_datos = [c for c in df.columns if c not in COLUMNAS_TRAZABILIDAD and c != "_reglas_aplicadas"]
    antes = len(df)
    df_sin_duplicados = df.drop_duplicates(subset=columnas_datos, keep="first")
    eliminadas = antes - len(df_sin_duplicados)
    if eliminadas:
        LOGGER.info("  %s: %s filas exactamente duplicadas eliminadas", nombre_fuente, eliminadas)
    return df_sin_duplicados


def limpiar_prestacion(df: pd.DataFrame) -> pd.DataFrame:
    """Limpieza silver de prestacion (3ebi-d83g)."""
    df = df.copy()

    df["id_dpto"], cambio_dpto = normalizar_codigo_dane(df["id_dpto"], CONFIG["codigos_dane"]["longitud_departamento"])
    df["id_mpio"], cambio_mpio = normalizar_codigo_dane(df["id_mpio"], CONFIG["codigos_dane"]["longitud_municipio"])
    df["id_localidad"], cambio_loc = normalizar_codigo_dane(df["id_localidad"], 8)

    df["anio"] = pd.to_numeric(df["anio"], errors="coerce").astype("Int64")
    df["mes"] = pd.to_numeric(df["mes"], errors="coerce").astype("Int64")
    for columna in ("energia_activa", "energia_reactiva", "potencia_maxima", "prom_diario_horas"):
        df[columna] = pd.to_numeric(df[columna], errors="coerce")
    df["fecha_demanda_maxima"] = pd.to_datetime(df["fecha_demanda_maxima"], errors="coerce")

    df["_reglas_aplicadas"] = construir_reglas_aplicadas(
        ("dane_normalizado", cambio_dpto | cambio_mpio | cambio_loc),
    )
    df = filtrar_departamentos(df, "id_mpio")
    df = remover_duplicados_exactos(df, "prestacion")
    return df


def limpiar_operacion_diaria(df: pd.DataFrame) -> pd.DataFrame:
    """Limpieza silver de operacion_diaria (qwe5-ycap).

    codigo_localidad no tiene el mismo esquema que id_localidad de prestacion (12-13
    dígitos, no 8: ver hallazgo en config.yaml). Se deriva id_mpio (5 dígitos) tomando su
    prefijo, que es el nivel real en el que esta fuente cruza con las otras dos.
    """
    df = df.copy()

    longitud = longitud_modal(df["codigo_localidad"])
    df["codigo_localidad"], cambio_codigo = normalizar_codigo_dane(df["codigo_localidad"], longitud)
    df["id_mpio"] = df["codigo_localidad"].str.slice(0, CONFIG["codigos_dane"]["longitud_municipio"])

    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    df["ano"] = pd.to_numeric(df["ano"], errors="coerce").astype("Int64")
    df["periodo"] = pd.to_numeric(df["periodo"], errors="coerce").astype("Int64")
    for columna in ("energia_generada", "horometro", "capacidad_generacion", "tiempo_servicio"):
        df[columna] = pd.to_numeric(df[columna], errors="coerce")
    df["identificador_empresa"] = df["identificador_empresa"].astype("string")

    df["_reglas_aplicadas"] = construir_reglas_aplicadas(("dane_normalizado", cambio_codigo))
    df = filtrar_departamentos(df, "id_mpio")
    df = remover_duplicados_exactos(df, "operacion_diaria")
    return df


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
        ("dane_compuesto", cambio_depto | cambio_mpio),
        ("semestre_derivado", df["semestre"].notna()),
    )
    df = filtrar_departamentos(df, "id_mpio")
    df = remover_duplicados_exactos(df, "pqr")
    return df


LIMPIADORES = {
    "prestacion": limpiar_prestacion,
    "operacion_diaria": limpiar_operacion_diaria,
    "pqr": limpiar_pqr,
}


def limpiar_fuente(nombre_fuente: str) -> int:
    """Lee data/bronze/<fuente>.parquet, aplica su limpieza y escribe data/silver/<fuente>.parquet.

    Devuelve el número de filas escritas en silver.
    """
    ruta_bronze = RUTA_BRONZE / f"{nombre_fuente}.parquet"
    if not ruta_bronze.exists():
        raise FileNotFoundError(f"No existe {ruta_bronze}; corre extract_excel.py primero.")

    df_bronze = pd.read_parquet(ruta_bronze)
    filas_bronze = len(df_bronze)
    LOGGER.info("Limpiando fuente '%s': %s filas en bronze", nombre_fuente, filas_bronze)

    df_silver = LIMPIADORES[nombre_fuente](df_bronze)

    RUTA_SILVER.mkdir(parents=True, exist_ok=True)
    ruta_salida = RUTA_SILVER / f"{nombre_fuente}.parquet"
    df_silver.to_parquet(ruta_salida, index=False, engine="pyarrow")
    LOGGER.info(
        "  %s: %s filas en silver (%s descartadas por filtro de departamento o duplicado exacto) -> %s",
        nombre_fuente, len(df_silver), filas_bronze - len(df_silver), ruta_salida,
    )
    return len(df_silver)


def main() -> None:
    """Punto de entrada de línea de comandos: limpia una fuente o las tres hacia silver."""
    parser = argparse.ArgumentParser(description="Limpieza silver de las fuentes ZNI.")
    parser.add_argument(
        "--fuente", choices=list(LIMPIADORES), default=None,
        help="Limpiar solo esta fuente (por defecto, las tres).",
    )
    args = parser.parse_args()

    fuentes = [args.fuente] if args.fuente else list(LIMPIADORES)
    errores = 0
    for nombre in fuentes:
        try:
            limpiar_fuente(nombre)
        except Exception:
            errores += 1
            LOGGER.exception("Error limpiando '%s'", nombre)

    if errores:
        LOGGER.error("Limpieza completa con %s fuente(s) fallida(s).", errores)
        sys.exit(1)
    LOGGER.info("Limpieza completa sin errores.")


if __name__ == "__main__":
    main()
