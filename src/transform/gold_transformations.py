"""Capa gold: modelo analítico listo para Power BI (data/silver/*.parquet -> data/gold/*).

Tablas (nombres y columnas en español, snake_case):
  dimensiones   dim_municipio, dim_localidad
  hechos        fact_prestacion (localidad-mes), fact_pqr (municipio-semestre-empresa)
  puente        puente_operador_localidad (con vigencia observada)
  indicadores   ind_* (estado del servicio, brechas, evolución, operadores, PQR, peor desempeño)
  metadatos     meta_fuentes (frescura por fuente), meta_uniones (pruebas de calidad por unión),
                kpis_pipeline (también escrito como data/gold/kpis_pipeline.csv)

Cada registro lleva fecha_corte_fuente, estado_frescura y es_comparable, más la trazabilidad
(fuentes_origen, fecha_carga, lote_id, reglas_aplicadas). Los periodos no comparables se
marcan, no se descartan.

Ninguna unión se construye sin pasar antes las pruebas de calidad de quality_checks.py; el
resultado de cada prueba queda en meta_uniones.

Uso (desde la raíz del proyecto, con el entorno virtual activado):
    python src/transform/gold_transformations.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from pandas.api import types as tipos

_RAIZ_PROYECTO = Path(__file__).resolve().parent.parent.parent
if str(_RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_PROYECTO))

from src import (  # noqa: E402
    cargar_configuracion,
    obtener_errores_controlados,
    obtener_logger,
    registrar_error_controlado,
)
from src.transform import quality_checks as qc  # noqa: E402
from src.transform.clean_excel import PATRON_SUFIJO_GEOGRAFICO  # noqa: E402

CONFIG = cargar_configuracion()
LOGGER = obtener_logger("gold_transformations", "gold.log")

RUTA_SILVER = Path(CONFIG["rutas"]["silver"])
RUTA_GOLD = Path(CONFIG["rutas"]["gold"])
ARCHIVO_ESTADISTICAS_SILVER = RUTA_SILVER / "_estadisticas_limpieza.json"
PLAUSIBILIDAD = CONFIG["plausibilidad"]
NOMBRES_DEPARTAMENTO: dict[str, str] = {str(k): v for k, v in CONFIG["geografia"]["nombres_departamento"].items()}
CODIGOS = CONFIG["codigos_dane"]
SEVERIDAD_FRESCURA = {"vigente": 0, "desactualizada": 1, "congelada": 2}
HORAS_DIA = PLAUSIBILIDAD["horas_servicio_max_dia"]

# Llave de cada tabla gold (para el KPI de duplicados, las llaves primarias y los índices).
CLAVES_TABLAS: dict[str, list[str]] = {
    "dim_municipio": ["id_municipio"],
    "dim_localidad": ["clave_localidad"],
    "fact_prestacion": ["clave_localidad", "anio", "mes"],
    "fact_pqr": ["id_municipio", "anio", "semestre", "id_empresa"],
    "puente_operador_localidad": ["codigo_localidad_operacion", "id_operador", "clave_localidad"],
    "ind_localidades_con_servicio": ["id_departamento", "anio", "mes"],
    "ind_horas_servicio_departamento": ["id_departamento", "anio", "mes"],
    "ind_horas_servicio_municipio": ["id_municipio", "anio", "mes"],
    "ind_brechas_horas_servicio": ["nivel_geografico", "id_geografia", "anio"],
    "ind_evolucion_mensual": ["nivel_geografico", "id_geografia", "periodo"],
    "ind_operador_localidad": ["clave_localidad", "id_operador"],
    "ind_comparacion_operadores": ["id_operador"],
    "ind_pqr_vs_horas_municipio": ["id_municipio", "anio", "semestre"],
    "ind_pqr_empresa_municipio": ["id_municipio", "anio", "semestre", "id_empresa"],
    "ind_peor_desempeno_municipio": ["id_municipio"],
    "ind_localidades_menos_horas": ["clave_localidad"],
    "meta_fuentes": ["fuente"],
    "meta_uniones": ["nombre_union", "prueba", "objeto_evaluado"],
    "kpis_pipeline": ["indicador"],
}
PREFIJOS_TABLAS_CON_TRAZABILIDAD = ("dim_", "fact_", "puente_", "ind_")

# Variables que silver debe dejar estandarizadas (KPI "% de variables estandarizadas").
ESPECIFICACION_ESTANDARIZACION: dict[str, dict[str, tuple]] = {
    "prestacion": {
        "id_dpto": ("dane", 2), "id_mpio": ("dane", 5), "id_localidad": ("dane", 8),
        "anio": ("entero",), "mes": ("entero",), "energia_activa": ("numerico",),
        "energia_reactiva": ("numerico",), "potencia_maxima": ("numerico",),
        "prom_diario_horas": ("numerico",), "fecha_demanda_maxima": ("fecha",),
    },
    "operacion_diaria": {
        "codigo_localidad": ("dane", 13), "id_mpio": ("dane", 5), "fecha": ("fecha",),
        "ano": ("entero",), "periodo": ("entero",), "energia_generada": ("numerico",),
        "tiempo_servicio": ("numerico",), "horometro": ("numerico",),
        "capacidad_generacion": ("numerico",), "identificador_empresa": ("texto",),
    },
    "pqr": {
        "car_t1554_dane_depto": ("dane", 2), "car_t1554_dane_mpio": ("dane", 3), "id_mpio": ("dane", 5),
        "car_carg_ano": ("entero",), "car_carg_periodo": ("entero",), "semestre": ("entero",),
        "rad_fecha": ("fecha",), "respuesta_fecha": ("fecha",), "notifica_fecha": ("fecha",),
        "identificador_empresa": ("texto",),
    },
}


# ---------------------------------------------------------------------------
# Estructuras y utilidades generales
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class EstadoFuente:
    """Cobertura y frescura observadas de una fuente dentro del alcance del proyecto."""

    nombre: str
    fuente_id: str
    frecuencia_meses: int
    actualizacion_nominal: str
    primer_periodo: pd.Period
    ultimo_periodo: pd.Period
    meses_cubiertos: frozenset
    fecha_corte: pd.Timestamp
    fecha_actualizacion_portal: pd.Timestamp | None
    periodos_retraso: float
    estado_frescura: str
    filas: int


@dataclass(frozen=True)
class TrazaFuente:
    """Datos de trazabilidad de una fuente tomados de su tabla silver."""

    fuente_id: str
    fecha_carga: pd.Timestamp
    lote_id: str
    reglas: frozenset


@dataclass
class ResultadoGold:
    """Resultado de una construcción completa de gold."""

    tablas: dict[str, pd.DataFrame]
    resumen_uniones: list[dict]


def moda(serie: pd.Series):
    """Valor más frecuente (desempate: el primero en orden alfabético); NA si no hay valores."""
    valores = serie.dropna()
    if valores.empty:
        return pd.NA
    conteo = valores.value_counts()
    return sorted(conteo[conteo == conteo.max()].index)[0]


def primero_no_nulo(*valores):
    """Primer valor que no sea nulo (NA si todos lo son)."""
    for valor in valores:
        if not pd.isna(valor):
            return valor
    return pd.NA


def inicio_de_mes(anio: pd.Series, mes: pd.Series) -> pd.Series:
    """Primer día del mes como fecha, a partir de columnas de año y mes."""
    return pd.to_datetime({"year": anio.astype("int64"), "month": mes.astype("int64"), "day": 1})


def periodos_de(anio: pd.Series, mes: pd.Series) -> pd.PeriodIndex:
    """PeriodIndex mensual a partir de columnas de año y mes."""
    return pd.PeriodIndex(inicio_de_mes(anio, mes).dt.to_period("M"))


def mes_a_semestre(mes):
    """Semestre de un mes: 1 para enero-junio, 2 para julio-diciembre."""
    return (mes - 1) // 6 + 1


def quitar_sufijo_geografico(serie: pd.Series) -> pd.Series:
    """Nombre visible de la localidad sin el sufijo '(MUNICIPIO - DEPARTAMENTO)'."""
    return serie.astype("string").str.replace(PATRON_SUFIJO_GEOGRAFICO, "", regex=True).str.strip()


def construir_clave_localidad(id_localidad: pd.Series, nombre_normalizado: pd.Series) -> pd.Series:
    """Clave estable de la entidad localidad: '<id_localidad>-<NOMBRE_NORMALIZADO>'."""
    nombre = nombre_normalizado.astype("string").str.replace(" ", "_", regex=False)
    return id_localidad.astype("string") + "-" + nombre


def semestres_completos(meses: Iterable[pd.Period]) -> frozenset:
    """Pares (año, semestre) cuyos 6 meses están presentes en `meses`."""
    por_semestre: dict[tuple[int, int], set[int]] = {}
    for periodo in meses:
        por_semestre.setdefault((periodo.year, int(mes_a_semestre(periodo.month))), set()).add(periodo.month)
    return frozenset(clave for clave, presentes in por_semestre.items() if len(presentes) == 6)


def clasificar_frescura(
    ultimo_periodo: pd.Period, fecha_referencia: pd.Timestamp, frecuencia_meses: int,
    actualizacion_nominal: str, max_retraso: int | None = None,
) -> tuple[str, float]:
    """Política de frescura del diseño (sección 4.2).

    congelada: la fuente no tiene actualización nominal. vigente: hasta `max_retraso` periodos
    de retraso frente a su frecuencia. desactualizada: más de `max_retraso` periodos.
    Devuelve (estado, periodos de retraso).
    """
    if max_retraso is None:
        max_retraso = CONFIG["frescura"]["vigente_max_periodos_retraso"]
    meses = (fecha_referencia.year - ultimo_periodo.year) * 12 + (fecha_referencia.month - ultimo_periodo.month)
    periodos = max(meses, 0) / frecuencia_meses
    if actualizacion_nominal == "congelada":
        return "congelada", periodos
    return ("vigente" if periodos <= max_retraso else "desactualizada"), periodos


def construir_estado_fuente(
    nombre: str, periodos: pd.PeriodIndex, fecha_portal: pd.Timestamp | None,
    fecha_referencia: pd.Timestamp, filas: int,
) -> EstadoFuente:
    """Cobertura observada + frescura de una fuente a partir de sus meses con datos."""
    cfg = CONFIG["fuentes"][nombre]
    unicos = periodos.unique().sort_values()
    ultimo = unicos.max()
    estado, retraso = clasificar_frescura(
        ultimo, fecha_referencia, cfg["frecuencia_nominal_meses"], cfg["actualizacion_nominal"],
    )
    return EstadoFuente(
        nombre=nombre, fuente_id=cfg["id"], frecuencia_meses=cfg["frecuencia_nominal_meses"],
        actualizacion_nominal=cfg["actualizacion_nominal"], primer_periodo=unicos.min(), ultimo_periodo=ultimo,
        meses_cubiertos=frozenset(unicos), fecha_corte=ultimo.end_time.normalize(),
        fecha_actualizacion_portal=fecha_portal, periodos_retraso=retraso, estado_frescura=estado, filas=filas,
    )


def _a_fecha_naive(marca: pd.Timestamp) -> pd.Timestamp:
    """Timestamp con zona -> fecha (medianoche, sin zona) en la zona horaria de referencia del
    proyecto (config frescura.zona_horaria_referencia), para que el día no dependa del UTC."""
    if marca.tzinfo is not None:
        marca = marca.tz_convert(CONFIG["frescura"].get("zona_horaria_referencia", "UTC")).tz_localize(None)
    return marca.normalize()


def traza_de_silver(df: pd.DataFrame) -> TrazaFuente:
    """Trazabilidad (fuente, fecha de carga, lote y reglas vistas) de una tabla silver."""
    carga = df["_fecha_carga"].max()
    if carga.tzinfo is not None:
        carga = carga.tz_convert("UTC").tz_localize(None)
    return TrazaFuente(
        fuente_id="|".join(sorted(df["_fuente_id"].dropna().unique())),
        fecha_carga=carga,
        lote_id="|".join(sorted(df["_lote_id"].dropna().unique())),
        reglas=frozenset(regla for lista in df["_reglas_aplicadas"] for regla in lista),
    )


def anadir_trazabilidad(df: pd.DataFrame, trazas: list[TrazaFuente], reglas_gold: list[str]) -> pd.DataFrame:
    """Agrega fuentes_origen, fecha_carga, lote_id y reglas_aplicadas (silver + gold) a una tabla."""
    df = df.copy()
    reglas_silver = sorted(set().union(*[t.reglas for t in trazas]))
    df["fuentes_origen"] = "|".join(sorted({t.fuente_id for t in trazas}))
    df["fecha_carga"] = max(t.fecha_carga for t in trazas)
    df["lote_id"] = "|".join(sorted({t.lote_id for t in trazas}))
    df["reglas_aplicadas"] = "; ".join(dict.fromkeys(reglas_silver + list(reglas_gold)))
    return df


def anadir_frescura(
    df: pd.DataFrame, estados: list[EstadoFuente], es_comparable: bool | pd.Series,
) -> pd.DataFrame:
    """Agrega fecha_corte_fuente, estado_frescura y es_comparable. Con varias fuentes se toma
    el corte más antiguo y el estado más restrictivo (congelada > desactualizada > vigente)."""
    df = df.copy()
    df["fecha_corte_fuente"] = min(e.fecha_corte for e in estados)
    df["estado_frescura"] = max((e.estado_frescura for e in estados), key=SEVERIDAD_FRESCURA.get)
    df["es_comparable"] = es_comparable
    return df


def hash_tabla(df: pd.DataFrame) -> str:
    """Huella SHA-256 del contenido de una tabla (para verificar reproducibilidad)."""
    contenido = pd.util.hash_pandas_object(df.reset_index(drop=True), index=False).to_numpy().tobytes()
    return hashlib.sha256(contenido + "|".join(map(str, df.columns)).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Validación de medidas de prestacion (horas y potencia)
# ---------------------------------------------------------------------------
def validar_horas(horas: pd.Series, cfg: dict | None = None) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Horas de servicio diarias válidas (0 a 24).

    Un valor mayor a 24 cuyo valor/factor cae en rango se reescala (la fuente cambió de formato
    en 2025-12 y 2026-01: 776 = 7.76 h). Si no se puede reescalar queda nulo. Devuelve
    (horas validadas, máscara de reescaladas, máscara de inválidas excluidas).
    """
    cfg = cfg or PLAUSIBILIDAD
    maximo = float(cfg["horas_servicio_max_dia"])
    factor = float(cfg["factor_reescala_horas"])
    h = pd.to_numeric(horas, errors="coerce").to_numpy(dtype="float64", na_value=np.nan)
    en_rango = (h >= 0) & (h <= maximo)
    reescalable = (h > maximo) & ((h / factor) <= maximo) & bool(cfg["reescalar_valores_fuera_de_rango"])
    validas = np.where(en_rango, h, np.where(reescalable, h / factor, np.nan))
    invalidas = ~np.isnan(h) & ~en_rango & ~reescalable
    return (
        pd.Series(validas, index=horas.index, dtype="float64"),
        pd.Series(reescalable, index=horas.index),
        pd.Series(invalidas, index=horas.index),
    )


def validar_potencia(
    potencia: pd.Series, horas_fuera_de_rango: pd.Series, cfg: dict | None = None,
) -> tuple[pd.Series, pd.Series]:
    """Potencia máxima plausible. NO se reescala: en las filas donde la fuente cambió de formato
    (las horas estaban fuera de rango) la escala de la potencia es inconsistente (÷1000 en unas
    localidades, ÷10000 en otras) y no se puede corregir de forma fiable, así que se excluye.
    Fuera de esas filas, un valor por encima del máximo plausible también se excluye.
    Devuelve (potencia validada, máscara de inválidas excluidas)."""
    cfg = cfg or PLAUSIBILIDAD
    maximo = float(cfg["potencia_maxima_max_plausible"])
    p = pd.to_numeric(potencia, errors="coerce").to_numpy(dtype="float64", na_value=np.nan)
    cambio_de_formato = horas_fuera_de_rango.to_numpy(dtype=bool)
    confiable = (p >= 0) & (p <= maximo) & ~cambio_de_formato
    validas = np.where(confiable, p, np.nan)
    invalidas = ~np.isnan(p) & ~confiable
    return pd.Series(validas, index=potencia.index, dtype="float64"), pd.Series(invalidas, index=potencia.index)


# ---------------------------------------------------------------------------
# Dimensiones
# ---------------------------------------------------------------------------
def _nombre_por_id(df: pd.DataFrame, col_id: str, col_nombre: str) -> dict:
    """Nombre más frecuente por código (ignora nulos)."""
    base = df.dropna(subset=[col_id, col_nombre])
    if base.empty:
        return {}
    return base.groupby(col_id)[col_nombre].agg(moda).to_dict()


def construir_dim_municipio(pr: pd.DataFrame, op: pd.DataFrame, pq: pd.DataFrame) -> pd.DataFrame:
    """Un registro por municipio que aparece en alguna fuente. El nombre sale de prestacion
    si existe, si no de pqr y si no de operacion_diaria; los nombres solo se muestran, nunca se unen."""
    n_pr = _nombre_por_id(pr, "id_mpio", "mpio")
    n_pq = _nombre_por_id(pq, "id_mpio", "dane_nom_mpio")
    n_op = _nombre_por_id(op, "id_mpio", "dane_nom_mpio")
    en_pr, en_op, en_pq = set(pr["id_mpio"].dropna()), set(op["id_mpio"].dropna()), set(pq["id_mpio"].dropna())
    ids = sorted(en_pr | en_op | en_pq)
    dim = pd.DataFrame({"id_municipio": ids})
    dim["nombre_municipio"] = [primero_no_nulo(n_pr.get(i), n_pq.get(i), n_op.get(i)) for i in ids]
    dim["id_departamento"] = dim["id_municipio"].str.slice(0, CODIGOS["longitud_departamento"])
    dim["nombre_departamento"] = dim["id_departamento"].map(NOMBRES_DEPARTAMENTO)
    dim["en_prestacion"] = dim["id_municipio"].isin(en_pr)
    dim["en_operacion_diaria"] = dim["id_municipio"].isin(en_op)
    dim["en_pqr"] = dim["id_municipio"].isin(en_pq)
    return dim


def construir_dim_localidad(pr: pd.DataFrame, dim_municipio: pd.DataFrame) -> pd.DataFrame:
    """Una fila por localidad analítica = (id_localidad, nombre normalizado). Un mismo código
    DANE puede agrupar varias localidades con nombre distinto (codigo_compartido)."""
    df = pr.copy()
    df["clave_localidad"] = construir_clave_localidad(df["id_localidad"], df["localidad_nombre_normalizado"])
    df["nombre_visible"] = quitar_sufijo_geografico(df["localidad"])
    df["periodo"] = inicio_de_mes(df["anio"], df["mes"])
    dim = df.groupby("clave_localidad", sort=True).agg(
        id_localidad=("id_localidad", "first"),
        localidad_nombre_normalizado=("localidad_nombre_normalizado", "first"),
        nombre_localidad=("nombre_visible", moda),
        id_municipio=("id_mpio", "first"),
        primer_periodo=("periodo", "min"),
        ultimo_periodo=("periodo", "max"),
        n_meses_reportados=("periodo", "nunique"),
    ).reset_index()
    entidades_por_codigo = dim.groupby("id_localidad")["clave_localidad"].transform("size")
    dim["n_entidades_mismo_codigo"] = entidades_por_codigo.astype("int64")
    dim["codigo_compartido"] = dim["n_entidades_mismo_codigo"] > 1
    dim["id_departamento"] = dim["id_municipio"].str.slice(0, CODIGOS["longitud_departamento"])
    dim = dim.merge(
        dim_municipio[["id_municipio", "nombre_municipio", "nombre_departamento"]], on="id_municipio", how="left",
    )
    columnas = [
        "clave_localidad", "id_localidad", "localidad_nombre_normalizado", "nombre_localidad", "id_municipio",
        "nombre_municipio", "id_departamento", "nombre_departamento", "codigo_compartido",
        "n_entidades_mismo_codigo", "primer_periodo", "ultimo_periodo", "n_meses_reportados",
    ]
    return dim[columnas]


# ---------------------------------------------------------------------------
# Hechos de prestacion y operadores
# ---------------------------------------------------------------------------
def construir_fact_prestacion_base(
    pr: pd.DataFrame, estado_pr: EstadoFuente, estado_op: EstadoFuente, estado_pq: EstadoFuente,
) -> pd.DataFrame:
    """Hecho localidad-mes de prestacion SIN enriquecer con operador (eso depende de la unión)."""
    f = pr.copy()
    f["clave_localidad"] = construir_clave_localidad(f["id_localidad"], f["localidad_nombre_normalizado"])
    f["periodo"] = inicio_de_mes(f["anio"], f["mes"])
    f["semestre"] = mes_a_semestre(f["mes"]).astype("Int64")
    horas, horas_reescaladas, horas_invalidas = validar_horas(f["prom_diario_horas"])
    potencia, potencia_invalida = validar_potencia(f["potencia_maxima"], horas_reescaladas | horas_invalidas)
    sem_pq = semestres_completos(estado_pq.meses_cubiertos)
    periodos = periodos_de(f["anio"], f["mes"])

    out = pd.DataFrame({
        "clave_localidad": f["clave_localidad"],
        "id_localidad": f["id_localidad"],
        "id_municipio": f["id_mpio"],
        "id_departamento": f["id_mpio"].str.slice(0, CODIGOS["longitud_departamento"]),
        "anio": f["anio"],
        "mes": f["mes"],
        "periodo": f["periodo"],
        "semestre": f["semestre"],
        "energia_activa": f["energia_activa"],
        "energia_reactiva": f["energia_reactiva"],
        "potencia_maxima": potencia,
        "potencia_maxima_reportada": pd.to_numeric(f["potencia_maxima"], errors="coerce").astype("float64"),
        "horas_servicio_promedio_dia": horas,
        "horas_servicio_reportadas": pd.to_numeric(f["prom_diario_horas"], errors="coerce").astype("float64"),
        "con_servicio": (f["energia_activa"] > 0).fillna(False).astype(bool),
        "fecha_demanda_maxima": f["fecha_demanda_maxima"],
        "horas_reescaladas": horas_reescaladas,
        "horas_invalidas": horas_invalidas,
        "potencia_invalida": potencia_invalida,
    })
    out["fecha_corte_fuente"] = estado_pr.fecha_corte
    out["estado_frescura"] = estado_pr.estado_frescura
    out["es_comparable_operador"] = [p in estado_op.meses_cubiertos for p in periodos]
    out["es_comparable_pqr"] = [(int(a), int(s)) in sem_pq for a, s in zip(out["anio"], out["semestre"])]
    out["es_comparable"] = out["es_comparable_operador"] & out["es_comparable_pqr"]
    out["_reglas_silver"] = f["_reglas_aplicadas"]
    return out


def preparar_operacion(op: pd.DataFrame) -> pd.DataFrame:
    """Agrega a operacion_diaria el mes y el id_localidad enlazable (solo si el centro poblado
    de codigo_localidad es distinto de '000'; ver regla enlace_localidad_por_prefijo_divipola)."""
    o = op.copy()
    o["mes_inicio"] = o["fecha"].dt.to_period("M").dt.to_timestamp()
    o["centro_poblado"] = o["codigo_localidad"].str.slice(5, 8)
    tiene_codigo = (o["centro_poblado"] != CODIGOS["centro_poblado_sin_codigo"]).fillna(False).astype(bool)
    o["id_localidad_enlace"] = o["codigo_localidad"].str.slice(0, CODIGOS["longitud_localidad"]).where(tiene_codigo)
    return o


def construir_evidencia_operador_mes(o: pd.DataFrame) -> pd.DataFrame:
    """Energía generada por (localidad enlazada, mes, operador) y nombre del operador."""
    enlazadas = o[o["id_localidad_enlace"].notna()]
    evidencia = enlazadas.groupby(["id_localidad_enlace", "mes_inicio", "identificador_empresa"], as_index=False).agg(
        energia_generada=("energia_generada", "sum"), nombre_operador=("nombre", moda),
    )
    return evidencia.sort_values(["id_localidad_enlace", "mes_inicio", "identificador_empresa"]).reset_index(drop=True)


def elegir_operador_principal(evidencia: pd.DataFrame) -> pd.DataFrame:
    """Operador principal por localidad-mes: el de mayor energía generada (empate: menor
    identificador). Agrega n_operadores = cuántos operadores hubo en esa localidad-mes."""
    orden = evidencia.assign(_id_num=pd.to_numeric(evidencia["identificador_empresa"], errors="coerce")).sort_values(
        ["id_localidad_enlace", "mes_inicio", "energia_generada", "_id_num"],
        ascending=[True, True, False, True], kind="stable",
    )
    principal = orden.drop_duplicates(["id_localidad_enlace", "mes_inicio"], keep="first").drop(columns="_id_num")
    cuantos = evidencia.groupby(["id_localidad_enlace", "mes_inicio"]).size().rename("n_operadores").reset_index()
    return principal.merge(cuantos, on=["id_localidad_enlace", "mes_inicio"], how="left").reset_index(drop=True)


def construir_puente_base(o: pd.DataFrame) -> pd.DataFrame:
    """Relación operador-localidad de la fuente (un registro por código de localidad y operador)
    con la vigencia OBSERVADA (primera y última fecha con registros)."""
    puente = o.groupby(["codigo_localidad", "identificador_empresa"], sort=True).agg(
        nombre_localidad_operacion=("nombre_localidad", moda),
        nombre_operador=("nombre", moda),
        vigente_desde=("fecha", "min"),
        vigente_hasta=("fecha", "max"),
        dias_con_registro=("fecha", "nunique"),
        meses_con_registro=("mes_inicio", "nunique"),
        energia_generada_total=("energia_generada", "sum"),
    ).reset_index()
    puente = puente.rename(columns={"codigo_localidad": "codigo_localidad_operacion", "identificador_empresa": "id_operador"})
    puente["id_municipio"] = puente["codigo_localidad_operacion"].str.slice(0, CODIGOS["longitud_municipio"])
    puente["centro_poblado"] = puente["codigo_localidad_operacion"].str.slice(5, 8)
    con_codigo = (puente["centro_poblado"] != CODIGOS["centro_poblado_sin_codigo"]).fillna(False).astype(bool)
    puente["nivel_enlace"] = np.where(con_codigo.to_numpy(), "localidad", "municipio")
    puente["id_localidad"] = puente["codigo_localidad_operacion"].str.slice(0, CODIGOS["longitud_localidad"]).where(con_codigo)
    return puente


def finalizar_puente(
    puente: pd.DataFrame, dim_localidad: pd.DataFrame, estado_op: EstadoFuente,
    estado_pr: EstadoFuente, traza_op: TrazaFuente,
) -> pd.DataFrame:
    """Puente con la clave de la entidad localidad (se repite por cada entidad que comparte el
    código), vigencia observada y columnas de frescura/trazabilidad."""
    claves = dim_localidad[["id_localidad", "clave_localidad"]]
    p = puente.merge(claves, on="id_localidad", how="left")
    p["enlazada_a_prestacion"] = p["clave_localidad"].notna()
    columnas = [
        "codigo_localidad_operacion", "nombre_localidad_operacion", "id_municipio", "centro_poblado", "nivel_enlace",
        "id_localidad", "clave_localidad", "enlazada_a_prestacion", "id_operador", "nombre_operador",
        "vigente_desde", "vigente_hasta", "dias_con_registro", "meses_con_registro", "energia_generada_total",
    ]
    p = p[columnas].sort_values(["codigo_localidad_operacion", "id_operador", "clave_localidad"], na_position="last")
    dentro = (p["vigente_desde"].dt.to_period("M") >= estado_pr.primer_periodo) & (
        p["vigente_hasta"].dt.to_period("M") <= estado_pr.ultimo_periodo
    )
    p = anadir_frescura(p.reset_index(drop=True), [estado_op], dentro.reset_index(drop=True))
    return anadir_trazabilidad(p, [traza_op], [
        "enlace_localidad_por_prefijo_divipola", "vigencia_operador_observada",
        "frescura_por_fuente", "comparabilidad_por_cobertura_observada",
    ])


def enriquecer_con_operador(
    fact: pd.DataFrame, principal: pd.DataFrame, ids_enlazables: set[str], habilitada: bool,
) -> pd.DataFrame:
    """LEFT JOIN de prestacion (localidad-mes) hacia el operador principal del mes. Solo para
    localidades enlazables por código y meses con cobertura de operacion_diaria."""
    f = fact.copy()
    if not habilitada:
        for columna in ("id_operador", "nombre_operador"):
            f[columna] = pd.Series(pd.NA, index=f.index, dtype="string")
        f["n_operadores_localidad_mes"] = pd.Series(pd.NA, index=f.index, dtype="Int64")
        f["estado_operador"] = "union no habilitada"
        return f
    p = principal.rename(columns={
        "id_localidad_enlace": "id_localidad", "mes_inicio": "periodo",
        "identificador_empresa": "id_operador", "n_operadores": "n_operadores_localidad_mes",
    })[["id_localidad", "periodo", "id_operador", "nombre_operador", "n_operadores_localidad_mes"]]
    f = f.merge(p, on=["id_localidad", "periodo"], how="left")
    en_ventana = f["es_comparable_operador"].to_numpy(dtype=bool)
    tiene = f["id_operador"].notna().to_numpy()
    enlazable = f["id_localidad"].isin(ids_enlazables).to_numpy()
    f["estado_operador"] = np.select(
        [~en_ventana, en_ventana & tiene, en_ventana & enlazable],
        ["sin dato vigente", "con dato", "sin registro en el mes"],
        default="sin enlace por codigo",
    )
    f["n_operadores_localidad_mes"] = f["n_operadores_localidad_mes"].astype("Int64")
    return f


def reglas_por_fila(
    silver: pd.Series, base: list[str], condicionales: dict[str, pd.Series],
) -> pd.Series:
    """reglas_aplicadas por fila: reglas de silver + reglas gold de base + las gold condicionales."""
    mascaras = {nombre: serie.to_numpy(dtype=bool) for nombre, serie in condicionales.items()}
    texto = []
    for i, lista in enumerate(silver):
        reglas = list(lista) + base + [nombre for nombre, mascara in mascaras.items() if mascara[i]]
        texto.append("; ".join(dict.fromkeys(reglas)))
    return pd.Series(texto, index=silver.index)


def finalizar_fact_prestacion(
    f: pd.DataFrame, traza_pr: TrazaFuente, union_a_habilitada: bool,
) -> pd.DataFrame:
    """Orden de columnas, trazabilidad por fila y llave ordenada de fact_prestacion."""
    base = [
        "localidad_entidad_codigo_y_nombre", "con_servicio_por_energia_activa", "semestre_desde_mes",
        "frescura_por_fuente", "comparabilidad_por_cobertura_observada",
    ]
    condicionales = {
        "horas_reescaladas_x100": f["horas_reescaladas"],
        "horas_invalidas_excluidas": f["horas_invalidas"],
        "potencia_invalida_excluida": f["potencia_invalida"],
    }
    if union_a_habilitada:
        base = base + ["union_prestacion_operador_nivel_localidad"]
        condicionales["enlace_localidad_por_prefijo_divipola"] = f["estado_operador"] == "con dato"
        condicionales["operador_principal_por_energia_generada"] = f["n_operadores_localidad_mes"].fillna(0).gt(1)
    f = f.copy()
    f["reglas_aplicadas"] = reglas_por_fila(f["_reglas_silver"], base, condicionales)
    f["fuentes_origen"] = traza_pr.fuente_id
    f["fecha_carga"] = traza_pr.fecha_carga
    f["lote_id"] = traza_pr.lote_id
    columnas = [
        "clave_localidad", "id_localidad", "id_municipio", "id_departamento", "anio", "mes", "periodo", "semestre",
        "energia_activa", "energia_reactiva", "potencia_maxima", "potencia_maxima_reportada",
        "horas_servicio_promedio_dia", "horas_servicio_reportadas", "con_servicio", "fecha_demanda_maxima",
        "horas_reescaladas", "horas_invalidas", "potencia_invalida",
        "id_operador", "nombre_operador", "n_operadores_localidad_mes", "estado_operador",
        "fecha_corte_fuente", "estado_frescura", "es_comparable_operador", "es_comparable_pqr", "es_comparable",
        "fuentes_origen", "fecha_carga", "lote_id", "reglas_aplicadas",
    ]
    return f[columnas].sort_values(["clave_localidad", "anio", "mes"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Hecho de PQR
# ---------------------------------------------------------------------------
def construir_fact_pqr(
    pq: pd.DataFrame, estado_pq: EstadoFuente, estado_pr: EstadoFuente, traza_pq: TrazaFuente,
) -> pd.DataFrame:
    """Casos de PQR contados por municipio, año, semestre y empresa (agregación previa a
    cualquier unión). Las empresas de esta fuente son distribuidoras de gas (ver config.yaml)."""
    d = pq.copy()
    d["dias_respuesta"] = (d["respuesta_fecha"] - d["rad_fecha"]).dt.days
    f = d.groupby(["id_mpio", "car_carg_ano", "semestre", "identificador_empresa"], sort=True).agg(
        nombre_empresa=("are_esp_nombre", moda),
        n_pqr=("car_carg_periodo", "size"),
        n_con_respuesta=("respuesta_fecha", lambda s: int(s.notna().sum())),
        dias_respuesta_promedio=("dias_respuesta", "mean"),
        meses_con_datos=("car_carg_periodo", "nunique"),
    ).reset_index()
    f = f.rename(columns={
        "id_mpio": "id_municipio", "car_carg_ano": "anio", "identificador_empresa": "id_empresa",
    })
    mes_inicio_semestre = np.where((f["semestre"] == 1).to_numpy(dtype=bool), 1, 7)
    f["periodo_semestre"] = inicio_de_mes(f["anio"], pd.Series(mes_inicio_semestre, index=f.index))
    f["pct_con_respuesta"] = (100 * f["n_con_respuesta"] / f["n_pqr"]).round(2)
    f["dias_respuesta_promedio"] = f["dias_respuesta_promedio"].astype("float64").round(2)
    f["n_pqr"] = f["n_pqr"].astype("int64")
    f["anio"] = f["anio"].astype("Int64")
    f["semestre"] = f["semestre"].astype("Int64")

    completos = semestres_completos(estado_pq.meses_cubiertos) & semestres_completos(estado_pr.meses_cubiertos)
    comparable = pd.Series([(int(a), int(s)) in completos for a, s in zip(f["anio"], f["semestre"])], index=f.index)
    columnas = [
        "id_municipio", "anio", "semestre", "periodo_semestre", "id_empresa", "nombre_empresa", "n_pqr",
        "n_con_respuesta", "pct_con_respuesta", "dias_respuesta_promedio", "meses_con_datos",
    ]
    f = anadir_frescura(f[columnas], [estado_pq], comparable)
    return anadir_trazabilidad(f, [traza_pq], [
        "agregacion_pqr_municipio_semestre_empresa", "frescura_por_fuente", "comparabilidad_por_cobertura_observada",
    ])


# ---------------------------------------------------------------------------
# Pruebas de calidad antes de cada unión
# ---------------------------------------------------------------------------
def _fila_prueba(union: str, nivel: str, objeto: str, res: qc.ResultadoCalidad, bloqueante: bool) -> dict:
    return {
        "union": union, "nivel": nivel, "prueba": res.nombre_prueba, "objeto_evaluado": objeto,
        "metrica": float(res.metrica), "aprobado": bool(res.aprobado), "bloqueante": bloqueante,
        "detalle": json.dumps(res.detalle, ensure_ascii=False, default=str),
    }


def evaluar_union_prestacion_operador(
    fact_base: pd.DataFrame, op_silver: pd.DataFrame, evidencia: pd.DataFrame, ids_enlazables: set[str],
) -> tuple[list[dict], dict]:
    """Pruebas de la unión prestacion <-> operacion_diaria (localidad + mes). Bloquean la unión:
    unicidad de las llaves y validez DANE. El cruce y la cardinalidad se documentan."""
    union, nivel = "prestacion_operacion_diaria", "localidad (prefijo DIVIPOLA) + mes"
    pruebas = [
        ("prestacion (clave_localidad, anio, mes)", qc.probar_unicidad_llave(fact_base, ["clave_localidad", "anio", "mes"]), True),
        ("operacion_diaria (codigo_localidad, fecha, serie_generador)",
         qc.probar_unicidad_llave(op_silver, ["codigo_localidad", "fecha", "serie_generador"]), True),
        ("operador agregado (localidad, mes, operador)",
         qc.probar_unicidad_llave(evidencia, ["id_localidad_enlace", "mes_inicio", "identificador_empresa"]), True),
        ("prestacion.id_localidad (8 dígitos)", qc.probar_validez_dane(fact_base["id_localidad"], CODIGOS["longitud_localidad"]), True),
        ("id_localidad enlazable de operacion_diaria (8 dígitos)",
         qc.probar_validez_dane(pd.Series(sorted(ids_enlazables), dtype="string"), CODIGOS["longitud_localidad"]), True),
        ("localidades de prestacion sin operador enlazable",
         qc.probar_cruce_entre_fuentes(set(fact_base["id_localidad"]), ids_enlazables, union), False),
        ("operadores por localidad-mes (esperado 1)",
         qc.probar_cardinalidad_maxima(evidencia, ["id_localidad_enlace", "mes_inicio"], "identificador_empresa", 1), False),
    ]
    filas = [_fila_prueba(union, nivel, objeto, res, bloqueante) for objeto, res, bloqueante in pruebas]
    habilitada = all(res.aprobado for _, res, bloqueante in pruebas if bloqueante)
    cardinalidad_ok = pruebas[-1][1].aprobado
    resultado = "no_implementada" if not habilitada else ("implementada" if cardinalidad_ok else "implementada_con_tratamiento")
    motivo = (
        "Una prueba bloqueante no aprobó." if not habilitada else
        "Se implementa solo para localidades enlazables por código y meses con cobertura; las localidades-mes con más de un "
        "operador se tratan con la regla operador_principal_por_energia_generada." if not cardinalidad_ok else
        "Todas las pruebas aprobadas."
    )
    return filas, {"union": union, "nivel": nivel, "habilitada": habilitada, "resultado_union": resultado, "motivo": motivo}


def evaluar_union_prestacion_pqr(
    mun_sem_pr: pd.DataFrame, fact_pqr: pd.DataFrame, pqr_mun_sem: pd.DataFrame, sem_pqr: frozenset,
) -> tuple[list[dict], dict]:
    """Pruebas de la unión prestacion <-> pqr (municipio + semestre)."""
    union, nivel = "prestacion_pqr", "municipio + semestre"
    comparables = mun_sem_pr[[(int(a), int(s)) in sem_pqr for a, s in zip(mun_sem_pr["anio"], mun_sem_pr["semestre"])]]

    def llaves(df: pd.DataFrame) -> set[str]:
        return {f"{m}|{a}|{s}" for m, a, s in zip(df["id_municipio"], df["anio"], df["semestre"])}

    pruebas = [
        ("prestacion (id_municipio, anio, semestre)", qc.probar_unicidad_llave(mun_sem_pr, ["id_municipio", "anio", "semestre"]), True),
        ("pqr (id_municipio, anio, semestre, id_empresa)",
         qc.probar_unicidad_llave(fact_pqr, ["id_municipio", "anio", "semestre", "id_empresa"]), True),
        ("pqr agregada (id_municipio, anio, semestre)", qc.probar_unicidad_llave(pqr_mun_sem, ["id_municipio", "anio", "semestre"]), True),
        ("prestacion.id_municipio (5 dígitos)", qc.probar_validez_dane(mun_sem_pr["id_municipio"], CODIGOS["longitud_municipio"]), True),
        ("pqr.id_municipio (5 dígitos)", qc.probar_validez_dane(fact_pqr["id_municipio"], CODIGOS["longitud_municipio"]), True),
        ("municipio-semestre de prestacion (semestres con PQR) sin PQR",
         qc.probar_cruce_entre_fuentes(llaves(comparables), llaves(pqr_mun_sem), union), False),
        ("empresas por municipio-semestre antes de agregar (esperado 1)",
         qc.probar_cardinalidad_maxima(fact_pqr, ["id_municipio", "anio", "semestre"], "id_empresa", 1), False),
    ]
    filas = [_fila_prueba(union, nivel, objeto, res, bloqueante) for objeto, res, bloqueante in pruebas]
    habilitada = all(res.aprobado for _, res, bloqueante in pruebas if bloqueante)
    cardinalidad_ok = pruebas[-1][1].aprobado
    resultado = "no_implementada" if not habilitada else ("implementada" if cardinalidad_ok else "implementada_con_tratamiento")
    motivo = (
        "Una prueba bloqueante no aprobó." if not habilitada else
        "Hay varias empresas por municipio-semestre: la PQR se agrega por municipio-semestre (sumando empresas) antes de "
        "unir, como exige el diseño; nunca se asigna a una localidad." if not cardinalidad_ok else
        "Todas las pruebas aprobadas."
    )
    return filas, {"union": union, "nivel": nivel, "habilitada": habilitada, "resultado_union": resultado, "motivo": motivo}


def evaluar_union_operador_pqr(op_silver: pd.DataFrame, pq_silver: pd.DataFrame) -> tuple[list[dict], dict]:
    """Pruebas de la unión operacion_diaria <-> pqr. La variante por identificador de empresa
    exige >= 95% de coincidencia; si no, la relación se limita al municipio (regla de respaldo)."""
    union, nivel = "operacion_diaria_pqr", "municipio + empresa (respaldo: municipio)"
    empresa = qc.probar_identificador_empresa_comun(op_silver["identificador_empresa"], pq_silver["identificador_empresa"])
    pruebas = [
        ("identificador_empresa en ambas fuentes", empresa, True),
        ("operacion_diaria.id_municipio (5 dígitos)", qc.probar_validez_dane(op_silver["id_mpio"], CODIGOS["longitud_municipio"]), True),
        ("pqr.id_municipio (5 dígitos)", qc.probar_validez_dane(pq_silver["id_mpio"], CODIGOS["longitud_municipio"]), True),
        ("municipios de operacion_diaria sin PQR",
         qc.probar_cruce_entre_fuentes(set(op_silver["id_mpio"]), set(pq_silver["id_mpio"]), union), False),
    ]
    filas = [_fila_prueba(union, nivel, objeto, res, bloqueante) for objeto, res, bloqueante in pruebas]
    municipio_ok = all(res.aprobado for _, res, _ in pruebas[1:3])
    if empresa.aprobado and municipio_ok:
        resultado, motivo = "implementada", "El identificador de empresa es común: se puede unir por municipio + empresa."
    elif municipio_ok:
        resultado = "solo_municipio"
        motivo = (
            f"El identificador de empresa coincide en {empresa.metrica}% (< {empresa.detalle.get('umbral_minimo')}%): no se une por "
            "empresa; la relación se limita al municipio (ambas tablas comparten id_municipio)."
        )
    else:
        resultado, motivo = "no_implementada", "Falló la validez del código de municipio."
    return filas, {
        "union": union, "nivel": nivel, "habilitada": municipio_ok, "habilitada_por_empresa": bool(empresa.aprobado),
        "resultado_union": resultado, "motivo": motivo,
    }


# ---------------------------------------------------------------------------
# Indicadores
# ---------------------------------------------------------------------------
def _suma_o_nulo(serie: pd.Series) -> float:
    return serie.sum(min_count=1)


def agregar_medidas_servicio(fact: pd.DataFrame, claves: list[str]) -> pd.DataFrame:
    """Medidas de servicio agregadas por `claves`; usa solo horas y potencias válidas."""
    g = fact.groupby(claves, sort=True)
    return g.agg(
        n_localidades_reportadas=("clave_localidad", "nunique"),
        n_localidades_con_servicio=("con_servicio", "sum"),
        n_observaciones_horas=("horas_servicio_promedio_dia", "count"),
        horas_servicio_promedio=("horas_servicio_promedio_dia", "mean"),
        n_horas_reescaladas=("horas_reescaladas", "sum"),
        n_horas_invalidas=("horas_invalidas", "sum"),
        energia_activa_total=("energia_activa", "sum"),
        energia_reactiva_total=("energia_reactiva", "sum"),
        potencia_maxima_suma=("potencia_maxima", _suma_o_nulo),
        potencia_maxima_max=("potencia_maxima", "max"),
        n_potencias_invalidas=("potencia_invalida", "sum"),
    ).reset_index()


def _con_periodo(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.insert(df.columns.get_loc("mes") + 1, "periodo", inicio_de_mes(df["anio"], df["mes"]))
    return df


def construir_indicadores_servicio(
    fact: pd.DataFrame, dim_municipio: pd.DataFrame, estado_pr: EstadoFuente, traza_pr: TrazaFuente,
) -> dict[str, pd.DataFrame]:
    """Indicadores que solo dependen de prestacion: localidades con servicio, horas de servicio
    por departamento y municipio, brechas y evolución mensual."""
    geo_mpio = dim_municipio[["id_municipio", "nombre_municipio", "id_departamento", "nombre_departamento"]]
    geo_dpto = dim_municipio[["id_departamento", "nombre_departamento"]].drop_duplicates()

    def cierre(df: pd.DataFrame, reglas: list[str]) -> pd.DataFrame:
        return anadir_trazabilidad(anadir_frescura(df, [estado_pr], True), [traza_pr], reglas)

    por_dpto = _con_periodo(agregar_medidas_servicio(fact, ["id_departamento", "anio", "mes"])).merge(geo_dpto, on="id_departamento", how="left")
    por_mpio = _con_periodo(agregar_medidas_servicio(fact, ["id_municipio", "anio", "mes"])).merge(geo_mpio, on="id_municipio", how="left")

    servicio = por_dpto[[
        "id_departamento", "nombre_departamento", "anio", "mes", "periodo", "n_localidades_reportadas", "n_localidades_con_servicio",
    ]].copy()
    servicio["n_localidades_sin_servicio"] = servicio["n_localidades_reportadas"] - servicio["n_localidades_con_servicio"]
    servicio["pct_localidades_con_servicio"] = (100 * servicio["n_localidades_con_servicio"] / servicio["n_localidades_reportadas"]).round(2)

    def ordenar(df: pd.DataFrame, columnas: list[str]) -> pd.DataFrame:
        resto = [c for c in df.columns if c not in columnas]
        return df[columnas + resto]

    horas_dpto = ordenar(por_dpto, ["id_departamento", "nombre_departamento", "anio", "mes", "periodo"])
    horas_mpio = ordenar(por_mpio, ["id_municipio", "nombre_municipio", "id_departamento", "nombre_departamento", "anio", "mes", "periodo"])

    # Brechas anuales: horas promedio de las observaciones válidas y brecha respecto a 24 h.
    partes = []
    base = fact.merge(dim_municipio[["id_municipio", "nombre_municipio", "nombre_departamento"]], on="id_municipio", how="left")
    for nivel, clave, nombre in (("departamento", "id_departamento", "nombre_departamento"), ("municipio", "id_municipio", "nombre_municipio")):
        agrupado = base.groupby([clave, nombre, "anio"], sort=True).agg(
            n_localidades_reportadas=("clave_localidad", "nunique"),
            n_observaciones_horas=("horas_servicio_promedio_dia", "count"),
            horas_servicio_promedio=("horas_servicio_promedio_dia", "mean"),
        ).reset_index().rename(columns={clave: "id_geografia", nombre: "nombre_geografia"})
        agrupado.insert(0, "nivel_geografico", nivel)
        partes.append(agrupado)
    brechas = pd.concat(partes, ignore_index=True)
    brechas["brecha_horas"] = (HORAS_DIA - brechas["horas_servicio_promedio"]).round(4)
    brechas = brechas.sort_values(["nivel_geografico", "anio", "brecha_horas", "id_geografia"], ascending=[True, True, False, True])
    brechas["ranking_brecha"] = brechas.groupby(["nivel_geografico", "anio"]).cumcount() + 1
    brechas = brechas.sort_values(["nivel_geografico", "id_geografia", "anio"]).reset_index(drop=True)

    # Evolución mensual con variaciones mensual e interanual (región y departamento).
    def evolucion(claves: list[str], nivel: str) -> pd.DataFrame:
        g = fact.groupby(claves + ["periodo"], sort=True).agg(
            n_localidades_reportadas=("clave_localidad", "nunique"),
            n_localidades_con_servicio=("con_servicio", "sum"),
            horas_servicio_promedio=("horas_servicio_promedio_dia", "mean"),
            energia_activa_total=("energia_activa", "sum"),
        ).reset_index()
        if not claves:
            g.insert(0, "id_geografia", "REGION")
            g.insert(1, "nombre_geografia", "SUROCCIDENTE (4 DEPARTAMENTOS)")
        else:
            g = g.rename(columns={"id_departamento": "id_geografia"})
            g.insert(1, "nombre_geografia", g["id_geografia"].map(NOMBRES_DEPARTAMENTO))
        g.insert(0, "nivel_geografico", nivel)
        return g

    evo = pd.concat([evolucion([], "region"), evolucion(["id_departamento"], "departamento")], ignore_index=True)
    for sufijo, meses in (("mensual", 1), ("interanual", 12)):
        previo = evo[["nivel_geografico", "id_geografia", "periodo", "horas_servicio_promedio", "energia_activa_total"]].copy()
        previo["periodo"] = previo["periodo"] + pd.DateOffset(months=meses)
        previo = previo.rename(columns={"horas_servicio_promedio": "_h_prev", "energia_activa_total": "_e_prev"})
        evo = evo.merge(previo, on=["nivel_geografico", "id_geografia", "periodo"], how="left")
        evo[f"variacion_{sufijo}_horas_pct"] = ((evo["horas_servicio_promedio"] - evo["_h_prev"]) / evo["_h_prev"].where(evo["_h_prev"] > 0) * 100).round(2)
        evo[f"variacion_{sufijo}_energia_pct"] = ((evo["energia_activa_total"] - evo["_e_prev"]) / evo["_e_prev"].where(evo["_e_prev"] > 0) * 100).round(2)
        evo = evo.drop(columns=["_h_prev", "_e_prev"])
    evo["energia_activa_total"] = evo["energia_activa_total"].astype("Int64")
    evo = evo.sort_values(["nivel_geografico", "id_geografia", "periodo"]).reset_index(drop=True)

    return {
        "ind_localidades_con_servicio": cierre(servicio, ["con_servicio_por_energia_activa", "frescura_por_fuente", "comparabilidad_por_cobertura_observada"]),
        "ind_horas_servicio_departamento": cierre(horas_dpto, ["horas_reescaladas_x100", "horas_invalidas_excluidas", "potencia_invalida_excluida", "frescura_por_fuente", "comparabilidad_por_cobertura_observada"]),
        "ind_horas_servicio_municipio": cierre(horas_mpio, ["horas_reescaladas_x100", "horas_invalidas_excluidas", "potencia_invalida_excluida", "frescura_por_fuente", "comparabilidad_por_cobertura_observada"]),
        "ind_brechas_horas_servicio": cierre(brechas, ["brecha_horas_respecto_a_24", "horas_reescaladas_x100", "horas_invalidas_excluidas", "frescura_por_fuente", "comparabilidad_por_cobertura_observada"]),
        "ind_evolucion_mensual": cierre(evo, ["horas_reescaladas_x100", "horas_invalidas_excluidas", "frescura_por_fuente", "comparabilidad_por_cobertura_observada"]),
    }


def construir_indicadores_operador(
    fact: pd.DataFrame, dim_localidad: pd.DataFrame, estado_pr: EstadoFuente, estado_op: EstadoFuente,
    traza_pr: TrazaFuente, traza_op: TrazaFuente,
) -> dict[str, pd.DataFrame]:
    """Operador por localidad y comparación de horas de servicio entre operadores (solo meses
    con cobertura de operacion_diaria y localidades enlazables por código)."""
    con_dato = fact[fact["estado_operador"] == "con dato"]
    reglas = [
        "union_prestacion_operador_nivel_localidad", "enlace_localidad_por_prefijo_divipola", "operador_principal_por_energia_generada",
        "vigencia_operador_observada", "horas_reescaladas_x100", "horas_invalidas_excluidas", "frescura_por_fuente", "comparabilidad_por_cobertura_observada",
    ]
    estados = [estado_pr, estado_op]
    por_loc = con_dato.groupby(["clave_localidad", "id_operador"], sort=True).agg(
        nombre_operador=("nombre_operador", moda),
        n_meses=("periodo", "nunique"),
        periodo_desde=("periodo", "min"),
        periodo_hasta=("periodo", "max"),
        horas_servicio_promedio=("horas_servicio_promedio_dia", "mean"),
        n_observaciones_horas=("horas_servicio_promedio_dia", "count"),
        energia_activa_total=("energia_activa", "sum"),
    ).reset_index()
    por_loc = por_loc.merge(
        dim_localidad[["clave_localidad", "nombre_localidad", "id_municipio", "nombre_municipio"]], on="clave_localidad", how="left",
    )
    por_loc["brecha_horas"] = (HORAS_DIA - por_loc["horas_servicio_promedio"]).round(4)
    por_loc = por_loc[[
        "clave_localidad", "nombre_localidad", "id_municipio", "nombre_municipio", "id_operador", "nombre_operador", "n_meses",
        "periodo_desde", "periodo_hasta", "horas_servicio_promedio", "brecha_horas", "n_observaciones_horas", "energia_activa_total",
    ]]
    operador_localidad = anadir_trazabilidad(anadir_frescura(por_loc, estados, True), [traza_pr, traza_op], reglas)

    por_op = con_dato.groupby("id_operador", sort=True).agg(
        nombre_operador=("nombre_operador", moda),
        n_localidades=("clave_localidad", "nunique"),
        n_meses=("periodo", "nunique"),
        periodo_desde=("periodo", "min"),
        periodo_hasta=("periodo", "max"),
        horas_servicio_promedio=("horas_servicio_promedio_dia", "mean"),
        n_observaciones_horas=("horas_servicio_promedio_dia", "count"),
        energia_activa_total=("energia_activa", "sum"),
    ).reset_index()
    por_op["brecha_horas"] = (HORAS_DIA - por_op["horas_servicio_promedio"]).round(4)
    por_op = por_op.sort_values(["horas_servicio_promedio", "id_operador"], ascending=[False, True])
    por_op["ranking_horas"] = np.arange(1, len(por_op) + 1)
    por_op = por_op.sort_values("id_operador").reset_index(drop=True)
    comparacion = anadir_trazabilidad(anadir_frescura(por_op, estados, True), [traza_pr, traza_op], reglas)
    return {"ind_operador_localidad": operador_localidad, "ind_comparacion_operadores": comparacion}


def construir_indicadores_pqr(
    fact: pd.DataFrame, fact_pqr: pd.DataFrame, dim_municipio: pd.DataFrame, dim_localidad: pd.DataFrame,
    estado_pr: EstadoFuente, estado_pq: EstadoFuente, traza_pr: TrazaFuente, traza_pq: TrazaFuente,
    sem_pqr: frozenset, union_b_habilitada: bool,
) -> dict[str, pd.DataFrame]:
    """PQR vs horas de servicio por municipio-semestre, PQR por empresa-municipio y peor
    desempeño combinado. La PQR nunca se asigna a una localidad individual."""
    if not union_b_habilitada:
        return {}
    estados = [estado_pr, estado_pq]
    geo = dim_municipio[["id_municipio", "nombre_municipio", "id_departamento", "nombre_departamento"]]
    reglas_union = [
        "union_prestacion_pqr_nivel_municipio_semestre", "semestre_desde_mes", "agregacion_pqr_municipio_semestre_empresa",
        "horas_reescaladas_x100", "horas_invalidas_excluidas", "frescura_por_fuente", "comparabilidad_por_cobertura_observada",
    ]

    # Lado izquierdo: prestacion agregada a municipio-semestre (antes de unir).
    mun_sem = fact.groupby(["id_municipio", "anio", "semestre"], sort=True).agg(
        n_localidades=("clave_localidad", "nunique"),
        n_meses_con_datos=("mes", "nunique"),
        n_observaciones_horas=("horas_servicio_promedio_dia", "count"),
        horas_servicio_promedio=("horas_servicio_promedio_dia", "mean"),
        energia_activa_total=("energia_activa", "sum"),
    ).reset_index()
    mun_sem["brecha_horas"] = (HORAS_DIA - mun_sem["horas_servicio_promedio"]).round(4)
    en_cobertura = pd.Series([(int(a), int(s)) in sem_pqr for a, s in zip(mun_sem["anio"], mun_sem["semestre"])], index=mun_sem.index)

    # Lado derecho: PQR agregada a municipio-semestre (suma de empresas) + empresa principal.
    pqr_ms = fact_pqr.groupby(["id_municipio", "anio", "semestre"], sort=True).agg(
        n_pqr_total=("n_pqr", "sum"), n_empresas_con_pqr=("id_empresa", "nunique"),
    ).reset_index()
    principal = fact_pqr.sort_values(["id_municipio", "anio", "semestre", "n_pqr", "id_empresa"], ascending=[True, True, True, False, True])
    principal = principal.drop_duplicates(["id_municipio", "anio", "semestre"], keep="first")[
        ["id_municipio", "anio", "semestre", "id_empresa", "nombre_empresa"]
    ].rename(columns={"id_empresa": "id_empresa_principal", "nombre_empresa": "nombre_empresa_principal"})

    union = mun_sem.merge(pqr_ms, on=["id_municipio", "anio", "semestre"], how="left").merge(
        principal, on=["id_municipio", "anio", "semestre"], how="left",
    )
    tiene_pqr = union["n_pqr_total"].notna().to_numpy()
    cubierto = en_cobertura.to_numpy()
    union["n_pqr_total"] = np.where(tiene_pqr, union["n_pqr_total"], np.where(cubierto, 0, np.nan))
    union["n_pqr_total"] = union["n_pqr_total"].astype("float64").round().astype("Int64")
    union["n_empresas_con_pqr"] = union["n_empresas_con_pqr"].where(tiene_pqr, np.where(cubierto, 0, np.nan)).astype("Int64")
    union["estado_pqr"] = np.select([~cubierto, tiene_pqr], ["sin dato vigente", "con dato"], default="sin registro en periodo cubierto")
    union = union.merge(geo, on="id_municipio", how="left")
    pqr_vs_horas = union[[
        "id_municipio", "nombre_municipio", "id_departamento", "nombre_departamento", "anio", "semestre", "n_localidades",
        "n_meses_con_datos", "n_observaciones_horas", "horas_servicio_promedio", "brecha_horas", "energia_activa_total",
        "n_pqr_total", "n_empresas_con_pqr", "id_empresa_principal", "nombre_empresa_principal", "estado_pqr",
    ]]
    pqr_vs_horas = anadir_trazabilidad(anadir_frescura(pqr_vs_horas, estados, en_cobertura.to_numpy()), [traza_pr, traza_pq], reglas_union)

    # PQR por empresa-municipio con las horas del municipio (LEFT JOIN desde la PQR).
    horas_ms = mun_sem[["id_municipio", "anio", "semestre", "n_localidades", "horas_servicio_promedio", "brecha_horas"]]
    emp = fact_pqr[["id_municipio", "anio", "semestre", "id_empresa", "nombre_empresa", "n_pqr", "n_con_respuesta", "pct_con_respuesta"]].merge(
        horas_ms, on=["id_municipio", "anio", "semestre"], how="left",
    ).merge(geo, on="id_municipio", how="left")
    emp["tiene_datos_prestacion"] = emp["horas_servicio_promedio"].notna()
    emp = emp.sort_values(["anio", "semestre", "n_pqr", "id_municipio", "id_empresa"], ascending=[True, True, False, True, True])
    emp["ranking_pqr_en_semestre"] = emp.groupby(["anio", "semestre"]).cumcount() + 1
    emp = emp.sort_values(["id_municipio", "anio", "semestre", "id_empresa"]).reset_index(drop=True)
    emp = emp[[
        "id_municipio", "nombre_municipio", "id_departamento", "nombre_departamento", "anio", "semestre", "id_empresa", "nombre_empresa",
        "n_pqr", "n_con_respuesta", "pct_con_respuesta", "ranking_pqr_en_semestre", "tiene_datos_prestacion",
        "n_localidades", "horas_servicio_promedio", "brecha_horas",
    ]]
    sem_completo = pd.Series([(int(a), int(s)) in sem_pqr for a, s in zip(emp["anio"], emp["semestre"])], index=emp.index)
    empresa_municipio = anadir_trazabilidad(
        anadir_frescura(emp, estados, (sem_completo & emp["tiene_datos_prestacion"]).to_numpy()),
        [traza_pr, traza_pq], reglas_union,
    )

    # Peor desempeño combinado en los semestres con cobertura de ambas fuentes.
    ventana = fact[fact["es_comparable_pqr"]]
    horas_mpio = ventana.groupby("id_municipio", sort=True).agg(
        n_localidades=("clave_localidad", "nunique"),
        n_observaciones_horas=("horas_servicio_promedio_dia", "count"),
        horas_servicio_promedio=("horas_servicio_promedio_dia", "mean"),
    ).reset_index()
    comparables = union[union["estado_pqr"] != "sin dato vigente"]
    pqr_mpio = comparables.groupby("id_municipio", sort=True).agg(
        n_semestres_comparables=("semestre", "size"), n_pqr_total=("n_pqr_total", "sum"),
    ).reset_index()
    peor = horas_mpio.merge(pqr_mpio, on="id_municipio", how="left").dropna(subset=["horas_servicio_promedio"]).copy()
    peor["n_pqr_total"] = peor["n_pqr_total"].fillna(0).astype("int64")
    peor["brecha_horas"] = (HORAS_DIA - peor["horas_servicio_promedio"]).round(4)
    peor["percentil_brecha_horas"] = peor["brecha_horas"].rank(pct=True, method="average").round(4)
    peor["percentil_pqr"] = peor["n_pqr_total"].rank(pct=True, method="average").round(4)
    peor["puntaje_combinado"] = ((peor["percentil_brecha_horas"] + peor["percentil_pqr"]) / 2).round(4)
    peor = peor.sort_values(["puntaje_combinado", "id_municipio"], ascending=[False, True]).reset_index(drop=True)
    peor["ranking_peor_desempeno"] = np.arange(1, len(peor) + 1)
    peor = peor.merge(geo, on="id_municipio", how="left")
    peor = peor[[
        "id_municipio", "nombre_municipio", "id_departamento", "nombre_departamento", "n_localidades", "n_semestres_comparables",
        "n_observaciones_horas", "horas_servicio_promedio", "brecha_horas", "n_pqr_total", "percentil_brecha_horas",
        "percentil_pqr", "puntaje_combinado", "ranking_peor_desempeno",
    ]].sort_values("id_municipio").reset_index(drop=True)
    peor_desempeno = anadir_trazabilidad(
        anadir_frescura(peor, estados, True), [traza_pr, traza_pq],
        reglas_union + ["brecha_horas_respecto_a_24", "ranking_peor_desempeno_combinado"],
    )

    # Localidades con menos horas de servicio dentro de la misma ventana comparable.
    loc = ventana.groupby(["id_municipio", "clave_localidad"], sort=True).agg(
        n_meses=("periodo", "nunique"),
        horas_servicio_promedio=("horas_servicio_promedio_dia", "mean"),
        energia_activa_total=("energia_activa", "sum"),
    ).reset_index().dropna(subset=["horas_servicio_promedio"])
    loc = loc.sort_values(["id_municipio", "horas_servicio_promedio", "clave_localidad"])
    loc["ranking_menos_horas_en_municipio"] = loc.groupby("id_municipio").cumcount() + 1
    loc = loc.merge(dim_localidad[["clave_localidad", "nombre_localidad"]], on="clave_localidad", how="left").merge(geo, on="id_municipio", how="left")
    loc["brecha_horas"] = (HORAS_DIA - loc["horas_servicio_promedio"]).round(4)
    loc = loc[[
        "clave_localidad", "nombre_localidad", "id_municipio", "nombre_municipio", "n_meses", "horas_servicio_promedio", "brecha_horas",
        "energia_activa_total", "ranking_menos_horas_en_municipio",
    ]].sort_values("clave_localidad").reset_index(drop=True)
    menos_horas = anadir_trazabilidad(
        anadir_frescura(loc, estados, True), [traza_pr, traza_pq],
        reglas_union + ["brecha_horas_respecto_a_24", "ranking_peor_desempeno_combinado"],
    )
    return {
        "ind_pqr_vs_horas_municipio": pqr_vs_horas,
        "ind_pqr_empresa_municipio": empresa_municipio,
        "ind_peor_desempeno_municipio": peor_desempeno,
        "ind_localidades_menos_horas": menos_horas,
    }


# ---------------------------------------------------------------------------
# Metadatos
# ---------------------------------------------------------------------------
def construir_meta_fuentes(estados: dict[str, EstadoFuente], fecha_referencia: pd.Timestamp) -> pd.DataFrame:
    """Frescura y cobertura por fuente, con la advertencia que debe mostrar el tablero."""
    filas = []
    for nombre, e in estados.items():
        if e.estado_frescura == "vigente":
            advertencia = ""
        elif e.estado_frescura == "desactualizada":
            advertencia = f"dato no actualizado: corte {e.fecha_corte:%Y-%m-%d}"
        else:
            advertencia = f"fuente congelada: corte {e.fecha_corte:%Y-%m-%d}; fuera de su ventana el periodo no es comparable"
        filas.append({
            "fuente": nombre, "fuente_id": e.fuente_id, "nombre_fuente": CONFIG["fuentes"][nombre]["nombre"],
            "frecuencia_nominal_meses": e.frecuencia_meses, "actualizacion_nominal": e.actualizacion_nominal,
            "primer_periodo_datos": e.primer_periodo.start_time.normalize(), "ultimo_periodo_datos": e.ultimo_periodo.start_time.normalize(),
            "n_meses_cubiertos": len(e.meses_cubiertos), "fecha_corte_fuente": e.fecha_corte,
            "fecha_actualizacion_portal": e.fecha_actualizacion_portal, "fecha_referencia": fecha_referencia,
            "periodos_retraso": round(e.periodos_retraso, 2), "estado_frescura": e.estado_frescura,
            "advertencia": advertencia, "filas_silver": e.filas,
        })
    return pd.DataFrame(filas).sort_values("fuente").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Construcción completa de gold
# ---------------------------------------------------------------------------
def leer_silver() -> dict[str, pd.DataFrame]:
    """Lee las tres tablas silver; falla con un mensaje claro si falta alguna."""
    silver = {}
    for nombre in CONFIG["fuentes"]:
        ruta = RUTA_SILVER / f"{nombre}.parquet"
        if not ruta.exists():
            raise FileNotFoundError(f"No existe {ruta}; corre la etapa silver primero.")
        silver[nombre] = pd.read_parquet(ruta)
    return silver


def construir_tablas(silver: dict[str, pd.DataFrame]) -> ResultadoGold:
    """Construye todas las tablas gold (sin los KPI) a partir de silver, ejecutando antes de
    cada unión las pruebas de calidad. Es determinista: la misma silver da las mismas tablas."""
    pr, op, pq = silver["prestacion"], silver["operacion_diaria"], silver["pqr"]
    fecha_referencia = _a_fecha_naive(max(df["_fecha_carga"].max() for df in silver.values()))

    estados = {
        "prestacion": construir_estado_fuente(
            "prestacion", periodos_de(pr["anio"], pr["mes"]),
            _a_fecha_naive(pr["_fecha_corte_fuente"].max()), fecha_referencia, len(pr)),
        "operacion_diaria": construir_estado_fuente(
            "operacion_diaria", pd.PeriodIndex(op["fecha"].dt.to_period("M")),
            _a_fecha_naive(op["_fecha_corte_fuente"].max()), fecha_referencia, len(op)),
        "pqr": construir_estado_fuente(
            "pqr", periodos_de(pq["car_carg_ano"], pq["car_carg_periodo"]),
            _a_fecha_naive(pq["_fecha_corte_fuente"].max()), fecha_referencia, len(pq)),
    }
    e_pr, e_op, e_pq = estados["prestacion"], estados["operacion_diaria"], estados["pqr"]
    t_pr, t_op, t_pq = traza_de_silver(pr), traza_de_silver(op), traza_de_silver(pq)
    sem_pqr = semestres_completos(e_pq.meses_cubiertos)
    LOGGER.info(
        "Cobertura observada -> prestacion %s..%s (%s), operacion_diaria %s..%s (%s), pqr %s..%s (%s); fecha de referencia %s",
        e_pr.primer_periodo, e_pr.ultimo_periodo, e_pr.estado_frescura, e_op.primer_periodo, e_op.ultimo_periodo,
        e_op.estado_frescura, e_pq.primer_periodo, e_pq.ultimo_periodo, e_pq.estado_frescura, fecha_referencia.date(),
    )

    # 1) Dimensiones y entidades por fuente (no dependen de ninguna unión).
    dim_municipio = construir_dim_municipio(pr, op, pq)
    dim_localidad = construir_dim_localidad(pr, dim_municipio)
    fact_base = construir_fact_prestacion_base(pr, e_pr, e_op, e_pq)
    o = preparar_operacion(op)
    evidencia = construir_evidencia_operador_mes(o)
    principal = elegir_operador_principal(evidencia)
    puente_base = construir_puente_base(o)
    fact_pqr = construir_fact_pqr(pq, e_pq, e_pr, t_pq)
    ids_enlazables = set(evidencia["id_localidad_enlace"].unique()) | set(puente_base["id_localidad"].dropna().unique())

    # 2) Pruebas de calidad ANTES de cada unión.
    mun_sem_pr = fact_base.groupby(["id_municipio", "anio", "semestre"], as_index=False).agg(n=("clave_localidad", "size"))
    pqr_mun_sem = fact_pqr.groupby(["id_municipio", "anio", "semestre"], as_index=False).agg(n_pqr_total=("n_pqr", "sum"))
    filas_a, res_a = evaluar_union_prestacion_operador(fact_base, op, evidencia, ids_enlazables)
    filas_b, res_b = evaluar_union_prestacion_pqr(mun_sem_pr, fact_pqr, pqr_mun_sem, sem_pqr)
    filas_c, res_c = evaluar_union_operador_pqr(op, pq)
    resumen = [res_a, res_b, res_c]
    for r in resumen:
        LOGGER.info("Unión %s (%s): %s - %s", r["union"], r["nivel"], r["resultado_union"], r["motivo"])
    # "union" es palabra reservada de SQL: en la tabla la columna se llama nombre_union.
    meta_uniones = pd.DataFrame(filas_a + filas_b + filas_c).rename(columns={"union": "nombre_union"})
    resumen_por_union = pd.DataFrame(resumen).rename(columns={"union": "nombre_union"})[["nombre_union", "resultado_union", "motivo"]]
    meta_uniones = meta_uniones.merge(resumen_por_union, on="nombre_union", how="left").sort_values(
        ["nombre_union", "prueba", "objeto_evaluado"],
    ).reset_index(drop=True)

    # 3) Tablas que dependen de las uniones aprobadas.
    fact = enriquecer_con_operador(fact_base, principal, ids_enlazables, res_a["habilitada"])
    fact_prestacion = finalizar_fact_prestacion(fact, t_pr, res_a["habilitada"])
    puente = finalizar_puente(puente_base, dim_localidad, e_op, e_pr, t_op)

    tablas: dict[str, pd.DataFrame] = {}
    tablas["dim_municipio"] = anadir_trazabilidad(
        anadir_frescura(dim_municipio, [e_pr, e_op, e_pq], True), [t_pr, t_op, t_pq], ["frescura_por_fuente"],
    )
    tablas["dim_localidad"] = anadir_trazabilidad(
        anadir_frescura(dim_localidad, [e_pr], True), [t_pr], ["localidad_entidad_codigo_y_nombre", "frescura_por_fuente"],
    )
    tablas["fact_prestacion"] = fact_prestacion
    tablas["fact_pqr"] = fact_pqr
    tablas["puente_operador_localidad"] = puente
    tablas.update(construir_indicadores_servicio(fact_prestacion, dim_municipio, e_pr, t_pr))
    if res_a["habilitada"]:
        tablas.update(construir_indicadores_operador(fact_prestacion, dim_localidad, e_pr, e_op, t_pr, t_op))
    tablas.update(construir_indicadores_pqr(
        fact_prestacion, fact_pqr, dim_municipio, dim_localidad, e_pr, e_pq, t_pr, t_pq, sem_pqr, res_b["habilitada"],
    ))
    tablas["meta_fuentes"] = construir_meta_fuentes(estados, fecha_referencia)
    tablas["meta_uniones"] = meta_uniones
    return ResultadoGold(tablas=tablas, resumen_uniones=resumen)


# ---------------------------------------------------------------------------
# KPI del pipeline (data/gold/kpis_pipeline.csv)
# ---------------------------------------------------------------------------
def _cumple_minimo(valor: float, meta: float) -> bool:
    return bool(valor >= meta)


def _cumple_maximo(valor: float, meta: float) -> bool:
    return bool(valor <= meta)


def verificar_estandarizacion(silver: dict[str, pd.DataFrame]) -> tuple[int, int, list[str]]:
    """Cuántas de las variables a estandarizar cumplen su formato esperado en silver."""
    cumplen, total, fallan = 0, 0, []
    for fuente, columnas in ESPECIFICACION_ESTANDARIZACION.items():
        df = silver[fuente]
        for columna, especificacion in columnas.items():
            total += 1
            serie = df[columna] if columna in df.columns else None
            tipo = especificacion[0]
            if serie is None:
                ok = False
            elif tipo == "dane":
                valores = serie.dropna().astype(str)
                ok = bool(len(valores)) and bool(valores.str.fullmatch(rf"\d{{{especificacion[1]}}}").all())
            elif tipo == "entero":
                ok = tipos.is_integer_dtype(serie)
            elif tipo == "numerico":
                ok = tipos.is_numeric_dtype(serie) and not tipos.is_bool_dtype(serie)
            elif tipo == "fecha":
                ok = tipos.is_datetime64_any_dtype(serie)
            else:
                ok = tipos.is_string_dtype(serie)
            cumplen += int(ok)
            if not ok:
                fallan.append(f"{fuente}.{columna}")
    return cumplen, total, fallan


def calcular_kpis(
    silver: dict[str, pd.DataFrame], tablas: dict[str, pd.DataFrame], reproducibles: dict[str, bool],
    estadisticas_limpieza: dict[str, dict[str, int]],
) -> pd.DataFrame:
    """Los 8 KPI del pipeline definidos en la sección 5 del diseño, con meta y cumplimiento."""
    metas = CONFIG["kpis_metas"]
    umbrales = CONFIG["umbrales_calidad"]
    tablas_de_datos = {n: t for n, t in tablas.items() if n.startswith(PREFIJOS_TABLAS_CON_TRAZABILIDAD)}
    filas = []

    def kpi(indicador: str, valor: float, unidad: str, meta: float, sentido: str, detalle: dict) -> None:
        cumple = _cumple_minimo(valor, meta) if sentido == ">=" else _cumple_maximo(valor, meta)
        filas.append({
            "indicador": indicador, "valor": round(float(valor), 4), "unidad": unidad, "meta": meta,
            "sentido_meta": sentido, "cumple": cumple, "detalle": json.dumps(detalle, ensure_ascii=False, default=str),
        })

    # 1) Fuentes integradas: fuentes con registros en alguna tabla gold de datos.
    en_gold = {fuente_id for t in tablas_de_datos.values() if len(t) for fuente_id in t["fuentes_origen"].iloc[0].split("|")}
    ids = {nombre: datos["id"] for nombre, datos in CONFIG["fuentes"].items()}
    integradas = sorted(n for n, i in ids.items() if i in en_gold)
    kpi("pct_fuentes_integradas", 100 * len(integradas) / len(ids), "%", metas["pct_fuentes_integradas"], ">=",
        {"integradas": integradas, "total": len(ids)})

    # 2) Variables estandarizadas en silver.
    cumplen, total, fallan = verificar_estandarizacion(silver)
    kpi("pct_variables_estandarizadas", 100 * cumplen / total, "%", metas["pct_variables_estandarizadas"], ">=",
        {"variables_evaluadas": total, "cumplen": cumplen, "no_cumplen": fallan})

    # 3) Registros duplicados remanentes en las llaves declaradas de gold (post-tratamiento).
    duplicadas, evaluadas = 0, 0
    for nombre, tabla in tablas_de_datos.items():
        res = qc.probar_unicidad_llave(tabla, CLAVES_TABLAS[nombre])
        duplicadas += res.detalle.get("filas_en_duplicados", 0)
        evaluadas += len(tabla)
    kpi("pct_registros_duplicados", 100 * duplicadas / max(evaluadas, 1), "%", umbrales["duplicados_pct_maximo"], "<=",
        {"filas_duplicadas_en_gold": duplicadas, "filas_evaluadas": evaluadas,
         "duplicados_exactos_eliminados_en_silver": {f: s.get("duplicados_exactos_eliminados", 0) for f, s in estadisticas_limpieza.items()}})

    # 4) Registros con trazabilidad: fuente, fecha de carga, lote y regla aplicada presentes.
    con_traza, filas_totales = 0, 0
    for tabla in tablas_de_datos.values():
        ok = (
            tabla["fuentes_origen"].notna() & (tabla["fuentes_origen"].astype(str) != "")
            & tabla["fecha_carga"].notna()
            & tabla["lote_id"].notna() & (tabla["lote_id"].astype(str) != "")
            & tabla["reglas_aplicadas"].notna() & (tabla["reglas_aplicadas"].astype(str) != "")
        )
        con_traza += int(ok.sum())
        filas_totales += len(tabla)
    kpi("pct_registros_con_trazabilidad", 100 * con_traza / max(filas_totales, 1), "%", metas["pct_registros_con_trazabilidad"], ">=",
        {"tablas": sorted(tablas_de_datos), "filas": filas_totales})

    # 5) Campos críticos completos en silver: % de registros con todos sus campos críticos; se
    #    reporta la PEOR fuente para que una tabla grande no diluya el problema de una pequeña.
    por_fuente = {
        fuente: qc.probar_campos_criticos_completos(df, CONFIG["fuentes"][fuente]["campos_criticos"]).metrica
        for fuente, df in silver.items()
    }
    kpi("pct_campos_criticos_completos", min(por_fuente.values()), "%", umbrales["campos_criticos_completos_pct_minimo"], ">=",
        {"por_fuente (registros con todos los campos críticos)": por_fuente, "criterio": "peor fuente"})

    # 6) Errores de transformación controlados en esta corrida.
    errores = obtener_errores_controlados()
    kpi("numero_errores_transformacion", len(errores), "errores", metas["errores_transformacion_max"], "<=",
        {"errores_controlados": errores, "errores_sin_controlar": 0})

    # 7) Reglas de negocio documentadas: las que el pipeline escribe vs. el registro de config.yaml.
    usadas = {r for t in tablas_de_datos.values() for texto in t["reglas_aplicadas"].dropna().unique() for r in str(texto).split("; ") if r}
    documentadas = {r for r, v in CONFIG["reglas_negocio"].items() if v.get("descripcion")}
    sin_documentar = sorted(usadas - documentadas)
    kpi("pct_reglas_negocio_documentadas", 100 * len(usadas & documentadas) / max(len(usadas), 1), "%", metas["pct_reglas_negocio_documentadas"], ">=",
        {"reglas_usadas": len(usadas), "sin_documentar": sin_documentar})

    # 8) Información reproducible: tablas idénticas en dos construcciones independientes.
    iguales = sorted(n for n, ok in reproducibles.items() if ok)
    kpi("pct_informacion_reproducible", 100 * len(iguales) / max(len(reproducibles), 1), "%", metas["pct_informacion_reproducible"], ">=",
        {"tablas_comparadas": len(reproducibles), "tablas_diferentes": sorted(set(reproducibles) - set(iguales))})
    return pd.DataFrame(filas)


def construir_gold(silver: dict[str, pd.DataFrame] | None = None) -> ResultadoGold:
    """Construye gold dos veces (para medir la reproducibilidad) y agrega los KPI del pipeline."""
    silver = silver if silver is not None else leer_silver()
    primero = construir_tablas(silver)
    segundo = construir_tablas(silver)
    reproducibles = {n: hash_tabla(t) == hash_tabla(segundo.tablas[n]) for n, t in primero.tablas.items()}
    estadisticas = {}
    if ARCHIVO_ESTADISTICAS_SILVER.exists():
        estadisticas = json.loads(ARCHIVO_ESTADISTICAS_SILVER.read_text(encoding="utf-8"))
    primero.tablas["kpis_pipeline"] = calcular_kpis(silver, primero.tablas, reproducibles, estadisticas)
    return primero


# ---------------------------------------------------------------------------
# Escritura
# ---------------------------------------------------------------------------
def escribir_gold(resultado: ResultadoGold) -> dict[str, dict]:
    """Escribe cada tabla en parquet y csv (utf-8 con BOM, abre bien en Excel/Power BI),
    kpis_pipeline.csv y un manifiesto con filas, columnas y huella de cada tabla."""
    RUTA_GOLD.mkdir(parents=True, exist_ok=True)
    for ruta in RUTA_GOLD.glob("*"):
        if ruta.suffix in {".parquet", ".csv", ".json"}:
            ruta.unlink()
    manifiesto = {}
    for nombre, tabla in resultado.tablas.items():
        tabla.to_parquet(RUTA_GOLD / f"{nombre}.parquet", index=False, engine="pyarrow")
        tabla.to_csv(RUTA_GOLD / f"{nombre}.csv", index=False, encoding="utf-8-sig")
        manifiesto[nombre] = {"filas": len(tabla), "columnas": len(tabla.columns), "hash": hash_tabla(tabla)}
    (RUTA_GOLD / "_manifiesto_gold.json").write_text(json.dumps(manifiesto, indent=2, sort_keys=True), encoding="utf-8")
    return manifiesto


def ejecutar_gold() -> ResultadoGold:
    """Lee silver, construye gold, lo escribe en data/gold y devuelve el resultado."""
    resultado = construir_gold()
    manifiesto = escribir_gold(resultado)
    for union in resultado.resumen_uniones:
        LOGGER.info("Unión %s: %s", union["union"], union["resultado_union"])
    LOGGER.info("Gold escrito en %s: %s tablas", RUTA_GOLD, len(manifiesto))
    return resultado


def main() -> None:
    """Punto de entrada de línea de comandos."""
    try:
        resultado = ejecutar_gold()
    except Exception as error:  # noqa: BLE001 - se informa y se sale con error
        registrar_error_controlado("gold", str(error))
        LOGGER.exception("Error construyendo gold")
        sys.exit(1)
    kpis = resultado.tablas["kpis_pipeline"]
    print(kpis[["indicador", "valor", "meta", "sentido_meta", "cumple"]].to_string(index=False))


if __name__ == "__main__":
    main()
