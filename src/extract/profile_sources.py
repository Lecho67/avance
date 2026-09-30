"""Perfila las tres fuentes ZNI de datos.gov.co (Socrata) para completar la matriz de
granularidad y llaves del documento de diseño (sección 4.1 de
docs/Avance_2_Proyecto_ETL_2026_V4.pdf).

Uso (desde la raíz del proyecto, con el entorno virtual activado):
    python src/extract/profile_sources.py

Salidas en logs/perfilado/:
    columnas.csv       campos reales, tipo, filas totales, % de nulos y última
                        actualización de la vista (metadato rowsUpdatedAt)
    muestras.csv        5 filas de muestra por fuente
    formatos_dane.csv   longitud observada y % numérico de cada campo candidato a
                        código DANE
    llaves.csv          prueba de unicidad de cada llave candidata (grupos duplicados,
                        % de filas afectadas y hasta 5 ejemplos)
    cruces.csv           % de cruce entre fuentes a nivel municipio (5 dígitos) y a la
                        longitud nativa de cada campo, limitado a los 4 departamentos
                        del alcance (Valle del Cauca, Cauca, Nariño, Putumayo)

Los campos candidatos (DANE, tiempo, actor) se detectan por nombre con una heurística de
expresiones regulares: es un punto de partida. Los nombres reales y las llaves deben
revisarse a mano antes de completar config/config.yaml; este script no decide la matriz
de uniones por sí solo.
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Any

import pandas as pd
import requests

_RAIZ_PROYECTO = Path(__file__).resolve().parent.parent.parent
if str(_RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_PROYECTO))

from src import cargar_configuracion, obtener_logger, obtener_token_socrata  # noqa: E402

CONFIG = cargar_configuracion()
LOGGER = obtener_logger("profile_sources", "perfilado.log")

BASE_URL: str = CONFIG["api"]["base_url"]
REINTENTOS_MAXIMOS: int = CONFIG["api"]["reintentos_maximos"]
BACKOFF_BASE: float = CONFIG["api"]["backoff_segundos_base"]

FUENTES: dict[str, str] = {nombre: datos["id"] for nombre, datos in CONFIG["fuentes"].items()}
DEPARTAMENTOS_DANE: set[str] = set(CONFIG["geografia"]["departamentos_dane"].values())
LONGITUD_MUNICIPIO: int = CONFIG["codigos_dane"]["longitud_municipio"]

SALIDA = Path(CONFIG["rutas"]["logs_perfilado"])

PATRON_DANE = re.compile(r"dane|divipola|cod(igo)?_?(mun|loc|dep|cent)|id_(dpto|depto|mpio|mun|loc|localidad|cent)", re.I)
PATRON_NOMBRE = re.compile(r"nombre|_nom_|nom$|^nom_", re.I)
PATRON_TIEMPO = re.compile(r"fecha|periodo|anio|ano$|mes|semestre|trimestre", re.I)
PATRON_ACTOR = re.compile(r"empresa|operador|prestador|nit", re.I)

# pqr: car_t1554_dane_mpio por sí solo NO trae el prefijo de departamento (ej. "895"
# para Zapatoca, Santander); hay que anteponerle car_t1554_dane_depto (2 dígitos) para
# obtener el código DANE de municipio completo de 5 dígitos. Confirmado al perfilar:
# ver el hallazgo en el resumen de la Fase 1.
PQR_CAMPO_DEPTO = "car_t1554_dane_depto"
PQR_CAMPO_MPIO = "car_t1554_dane_mpio"

# Llaves candidatas a probar por fuente, alineadas con la granularidad documentada en
# la sección 4.1 del diseño, usando únicamente nombres de campo reales confirmados en
# columnas.csv (no se prueban las combinaciones genéricas de todos los campos tipo
# tiempo/actor detectados por heurística, que generan ruido: ver dane+tiempo(+actor)
# en llaves.csv si se quiere esa vista más amplia).
LLAVES_A_PROBAR: dict[str, list[list[str]]] = {
    "prestacion": [
        ["id_localidad", "anio", "mes"],
    ],
    "operacion_diaria": [
        ["codigo_localidad", "fecha"],
        ["codigo_localidad", "fecha", "identificador_empresa"],
    ],
    "pqr": [
        ["rad_recibido"],
        [PQR_CAMPO_DEPTO, PQR_CAMPO_MPIO, "identificador_empresa", "car_carg_ano", "car_carg_periodo"],
    ],
}


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


def consultar(id_fuente: str, parametros: dict[str, Any]) -> list[dict[str, Any]]:
    """Ejecuta una consulta SoQL contra el recurso de una fuente."""
    return solicitar(f"{BASE_URL}/resource/{id_fuente}.json", parametros)


def metadatos_fuente(id_fuente: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Devuelve los metadatos completos de la vista y sus columnas (sin las columnas internas de Socrata)."""
    metadatos = solicitar(f"{BASE_URL}/api/views/{id_fuente}.json")
    columnas = [c for c in metadatos["columns"] if not c["fieldName"].startswith(":")]
    return metadatos, columnas


def normalizar_dane(serie: pd.Series) -> pd.Series:
    """Recorta espacios y quita el '.0' que deja la conversión numérica al leer JSON."""
    return serie.astype("string").str.strip().str.replace(r"\.0$", "", regex=True)


def conteo_no_nulos(id_fuente: str, campos: list[str]) -> dict[str, int]:
    """Cuenta valores no nulos de varios campos en una sola consulta agregada."""
    seleccion = ", ".join(f"count({campo}) as c{i}" for i, campo in enumerate(campos))
    fila = consultar(id_fuente, {"$select": seleccion})[0]
    return {campo: int(fila.get(f"c{i}", 0) or 0) for i, campo in enumerate(campos)}


def valores_distintos(id_fuente: str, campo: str) -> pd.Series:
    """Trae todos los valores distintos (no nulos) de un campo, normalizados como texto."""
    filas = consultar(id_fuente, {"$select": campo, "$group": campo, "$limit": 200000})
    valores = pd.Series([f.get(campo) for f in filas if f.get(campo) is not None], dtype="string")
    return normalizar_dane(valores)


def duplicados_de_llave(id_fuente: str, llave: list[str], total_filas: int) -> dict[str, Any]:
    """Busca grupos duplicados de una llave candidata y calcula el % de filas que afectan."""
    seleccion = ", ".join(llave)
    grupos = consultar(id_fuente, {
        "$select": f"{seleccion}, count(*) as n",
        "$group": seleccion,
        "$having": "count(*) > 1",
        "$order": "n desc",
        "$limit": 50000,
    })
    filas_en_duplicados = sum(int(g["n"]) for g in grupos)
    return {
        "campos_llave": ", ".join(llave),
        "grupos_duplicados": len(grupos),
        "filas_en_duplicados": filas_en_duplicados,
        "pct_filas_duplicadas": round(100 * filas_en_duplicados / total_filas, 2) if total_filas else None,
        "ejemplos_json": json.dumps(grupos[:5], ensure_ascii=False, default=str),
    }


def valores_nivel_municipio(valores: pd.Series) -> set[str]:
    """Reduce cualquier código DANE numérico a su prefijo de municipio (5 dígitos: depto + municipio)."""
    numericos = valores[valores.str.fullmatch(r"\d+")]
    return set(numericos.str.zfill(LONGITUD_MUNICIPIO).str[:LONGITUD_MUNICIPIO])


def valores_nivel_nativo(valores: pd.Series) -> set[str]:
    """Rellena con ceros a la longitud más frecuente del propio campo (no fuerza 5 ni 8 dígitos)."""
    numericos = valores[valores.str.fullmatch(r"\d+")]
    if numericos.empty:
        return set()
    longitud_moda = int(numericos.str.len().mode().iloc[0])
    return set(numericos.str.zfill(longitud_moda))


def filtrar_alcance(codigos: set[str]) -> set[str]:
    """Conserva solo los códigos cuyo prefijo de departamento está en el alcance del proyecto."""
    return {c for c in codigos if c[:2] in DEPARTAMENTOS_DANE}


def valores_compuestos_pqr_municipio(id_fuente: str) -> pd.Series:
    """Combina car_t1554_dane_depto (2 dígitos) + car_t1554_dane_mpio (3 dígitos) de pqr
    en el código DANE de municipio completo de 5 dígitos. Necesario porque
    car_t1554_dane_mpio por sí solo solo trae el consecutivo dentro del departamento."""
    filas = consultar(id_fuente, {
        "$select": f"{PQR_CAMPO_DEPTO}, {PQR_CAMPO_MPIO}",
        "$group": f"{PQR_CAMPO_DEPTO}, {PQR_CAMPO_MPIO}",
        "$limit": 50000,
    })
    depto = normalizar_dane(pd.Series([f.get(PQR_CAMPO_DEPTO) for f in filas], dtype="string"))
    mpio = normalizar_dane(pd.Series([f.get(PQR_CAMPO_MPIO) for f in filas], dtype="string"))
    valido = depto.str.fullmatch(r"\d+").fillna(False) & mpio.str.fullmatch(r"\d+").fillna(False)
    compuesto = depto[valido].str.zfill(2) + mpio[valido].str.zfill(3)
    return compuesto.reset_index(drop=True)


def valores_planos(id_fuente: str, campo: str) -> pd.Series:
    """Trae valores distintos de un campo sin asumir que es un código DANE (p. ej. un
    identificador de empresa), normalizados igual para poder compararlos entre fuentes."""
    return valores_distintos(id_fuente, campo)


def main() -> None:
    """Perfila las tres fuentes y escribe los CSV de resultados en logs/perfilado/."""
    SALIDA.mkdir(parents=True, exist_ok=True)
    columnas_out: list[dict[str, Any]] = []
    muestras_out: list[dict[str, Any]] = []
    formatos_out: list[dict[str, Any]] = []
    llaves_out: list[dict[str, Any]] = []
    distintos_por_campo: dict[tuple[str, str], pd.Series] = {}
    distintos_actor: dict[tuple[str, str], pd.Series] = {}

    for nombre, id_fuente in FUENTES.items():
        LOGGER.info("Perfilando fuente '%s' (id=%s)...", nombre, id_fuente)
        metadatos, columnas = metadatos_fuente(id_fuente)
        campos = [c["fieldName"] for c in columnas]
        total_filas = int(consultar(id_fuente, {"$select": "count(*)"})[0]["count"])
        no_nulos = conteo_no_nulos(id_fuente, campos)
        actualizado = datetime.fromtimestamp(metadatos["rowsUpdatedAt"], tz=timezone.utc)

        LOGGER.info(
            "  %s: %s filas, %s columnas, última actualización de la vista (rowsUpdatedAt) %s",
            nombre, total_filas, len(campos), actualizado.isoformat(),
        )

        for columna in columnas:
            campo = columna["fieldName"]
            columnas_out.append({
                "fuente": nombre,
                "id": id_fuente,
                "campo": campo,
                "nombre_mostrado": columna.get("name", ""),
                "tipo": columna["dataTypeName"],
                "descripcion": columna.get("description", ""),
                "filas_totales": total_filas,
                "pct_nulos": round(100 * (1 - no_nulos[campo] / total_filas), 2) if total_filas else None,
                "ultima_actualizacion_vista_utc": actualizado.isoformat(),
            })

        for fila in consultar(id_fuente, {"$limit": 5}):
            muestras_out.append({"fuente": nombre, **fila})

        campos_dane = [c for c in campos if PATRON_DANE.search(c) and not PATRON_NOMBRE.search(c)]
        campos_tiempo = [c for c in campos if PATRON_TIEMPO.search(c)]
        campos_actor = [c for c in campos if PATRON_ACTOR.search(c)]
        LOGGER.info(
            "  candidatos por heurística -> DANE: %s | tiempo: %s | actor: %s",
            campos_dane, campos_tiempo, campos_actor,
        )

        for campo in campos_dane:
            valores = valores_distintos(id_fuente, campo)
            distintos_por_campo[(nombre, campo)] = valores
            longitudes = valores.str.len().value_counts().to_dict()
            formatos_out.append({
                "fuente": nombre,
                "campo": campo,
                "valores_distintos": len(valores),
                "longitudes_observadas_json": json.dumps({int(k): int(v) for k, v in longitudes.items()}),
                "pct_solo_digitos": round(100 * valores.str.fullmatch(r"\d+").mean(), 2) if len(valores) else None,
            })

        if nombre == "pqr" and PQR_CAMPO_DEPTO in campos and PQR_CAMPO_MPIO in campos:
            compuesto = valores_compuestos_pqr_municipio(id_fuente)
            distintos_por_campo[(nombre, "municipio_compuesto(depto+mpio)")] = compuesto
            LOGGER.info(
                "  compuesto pqr municipio (depto+mpio): %s valores distintos",
                len(compuesto),
            )

        for campo in campos_actor:
            distintos_actor[(nombre, campo)] = valores_planos(id_fuente, campo)

        for llave in LLAVES_A_PROBAR.get(nombre, []):
            llave_presente = [c for c in llave if c in campos]
            if llave_presente != llave:
                LOGGER.warning(
                    "  llave candidata %s tiene campos que no existen en la fuente; se omite",
                    llave,
                )
                continue
            resultado = duplicados_de_llave(id_fuente, llave, total_filas)
            llaves_out.append({"fuente": nombre, "variante": "candidata (según diseño)", **resultado})

    LOGGER.info("Calculando cruces entre fuentes (limitado a los 4 departamentos del alcance)...")
    cruces_out: list[dict[str, Any]] = []
    nombres_fuentes = list(FUENTES)
    niveles = (
        ("municipio (5 dígitos)", valores_nivel_municipio),
        ("nativo (longitud propia del campo)", valores_nivel_nativo),
    )
    for i, fuente_a in enumerate(nombres_fuentes):
        for fuente_b in nombres_fuentes[i + 1:]:
            campos_a = [k for k in distintos_por_campo if k[0] == fuente_a]
            campos_b = [k for k in distintos_por_campo if k[0] == fuente_b]
            for clave_a, clave_b in product(campos_a, campos_b):
                for nivel, funcion_nivel in niveles:
                    conjunto_a = filtrar_alcance(funcion_nivel(distintos_por_campo[clave_a]))
                    conjunto_b = filtrar_alcance(funcion_nivel(distintos_por_campo[clave_b]))
                    if not conjunto_a or not conjunto_b:
                        continue
                    interseccion = conjunto_a & conjunto_b
                    cruces_out.append({
                        "fuente_a": fuente_a, "campo_a": clave_a[1],
                        "fuente_b": fuente_b, "campo_b": clave_b[1],
                        "nivel": nivel,
                        "n_valores_a_en_alcance": len(conjunto_a),
                        "n_valores_b_en_alcance": len(conjunto_b),
                        "pct_de_a_en_b": round(100 * len(interseccion) / len(conjunto_a), 2),
                        "pct_de_b_en_a": round(100 * len(interseccion) / len(conjunto_b), 2),
                    })

    LOGGER.info("Calculando cruce del identificador de empresa (operacion_diaria <-> pqr)...")
    claves_actor = list(distintos_actor)
    for i, clave_a in enumerate(claves_actor):
        for clave_b in claves_actor[i + 1:]:
            if clave_a[0] == clave_b[0]:
                continue
            conjunto_a = set(distintos_actor[clave_a].dropna())
            conjunto_b = set(distintos_actor[clave_b].dropna())
            if not conjunto_a or not conjunto_b:
                continue
            interseccion = conjunto_a & conjunto_b
            cruces_out.append({
                "fuente_a": clave_a[0], "campo_a": clave_a[1],
                "fuente_b": clave_b[0], "campo_b": clave_b[1],
                "nivel": "identificador_empresa (sin transformar)",
                "n_valores_a_en_alcance": len(conjunto_a),
                "n_valores_b_en_alcance": len(conjunto_b),
                "pct_de_a_en_b": round(100 * len(interseccion) / len(conjunto_a), 2),
                "pct_de_b_en_a": round(100 * len(interseccion) / len(conjunto_b), 2),
            })

    pd.DataFrame(columnas_out).to_csv(SALIDA / "columnas.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(muestras_out).to_csv(SALIDA / "muestras.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(formatos_out).to_csv(SALIDA / "formatos_dane.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(llaves_out).to_csv(SALIDA / "llaves.csv", index=False, encoding="utf-8-sig")
    columnas_cruces = [
        "fuente_a", "campo_a", "fuente_b", "campo_b", "nivel",
        "n_valores_a_en_alcance", "n_valores_b_en_alcance", "pct_de_a_en_b", "pct_de_b_en_a",
    ]
    df_cruces = pd.DataFrame(cruces_out, columns=columnas_cruces)
    if not df_cruces.empty:
        df_cruces = df_cruces.sort_values("pct_de_a_en_b", ascending=False)
    df_cruces.to_csv(SALIDA / "cruces.csv", index=False, encoding="utf-8-sig")

    LOGGER.info("Perfilado completo. Resultados en %s", SALIDA.resolve())


if __name__ == "__main__":
    main()
