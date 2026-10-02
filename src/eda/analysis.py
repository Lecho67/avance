"""Cálculos del análisis exploratorio (EDA) sobre el modelo gold: solo pandas/numpy, sin Matplotlib.

Cada función recibe tablas gold (o derivados) y devuelve un DataFrame o un diccionario listo para graficar,
de modo que las mismas cifras alimentan las figuras (src/eda/charts.py), las tablas de apoyo (docs/eda/tablas),
el notebook y la presentación: nada se transcribe a mano.

Dos precauciones guían el análisis (ver README, sección de limitaciones):

1. La cobertura de `prestacion` es irregular: cada mes reportan entre 14 y 44 de las 97 localidades. Un promedio
   de "todas las observaciones" mezcla cambios reales con cambios de QUÉ localidades reportan. Por eso la
   evolución se mide también "contra la propia localidad" (desviación respecto a su promedio) y con intervalos
   de confianza obtenidos remuestreando localidades.
2. Las PQR son de distribuidoras de gas: se analizan como contexto municipal, no como quejas del servicio eléctrico.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_RAIZ_PROYECTO = Path(__file__).resolve().parent.parent.parent
if str(_RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_PROYECTO))

from src import RAIZ_PROYECTO, cargar_configuracion  # noqa: E402

CONFIG = cargar_configuracion()
PARAMETROS = CONFIG["eda"]
HORAS_DIA = CONFIG["plausibilidad"]["horas_servicio_max_dia"]
RUTA_GOLD = RAIZ_PROYECTO / CONFIG["rutas"]["gold"]
RUTA_SILVER = RAIZ_PROYECTO / CONFIG["rutas"]["silver"]

# Tablas gold que el análisis necesita; si falta alguna, se avisa con un error claro.
TABLAS_REQUERIDAS = [
    "fact_prestacion", "dim_localidad", "dim_municipio", "meta_fuentes", "kpis_pipeline",
    "ind_horas_servicio_departamento", "ind_comparacion_operadores", "ind_pqr_empresa_municipio",
    "ind_pqr_vs_horas_municipio", "ind_peor_desempeno_municipio", "ind_localidades_con_servicio",
]


# ---------------------------------------------------------------------------
# Carga
# ---------------------------------------------------------------------------
def cargar_gold(ruta: Path | str | None = None) -> dict[str, pd.DataFrame]:
    """Lee todas las tablas gold (parquet) de una carpeta. Falla con un mensaje claro si falta alguna necesaria."""
    ruta = Path(ruta) if ruta else RUTA_GOLD
    tablas = {archivo.stem: pd.read_parquet(archivo) for archivo in sorted(ruta.glob("*.parquet"))}
    faltantes = [nombre for nombre in TABLAS_REQUERIDAS if nombre not in tablas]
    if faltantes:
        raise FileNotFoundError(
            f"Faltan tablas gold en {ruta}: {faltantes}. Genera gold primero con: python main.py --etapa gold"
        )
    return tablas


def cargar_operacion_diaria(ruta: Path | str | None = None) -> pd.DataFrame | None:
    """Lee las columnas que usa el EDA de silver/operacion_diaria. Devuelve None si silver no existe."""
    ruta = Path(ruta) if ruta else RUTA_SILVER / "operacion_diaria.parquet"
    if not ruta.exists():
        return None
    columnas = ["serie_generador", "marca", "capacidad_generacion", "tiempo_servicio", "tipo_medida", "codigo_localidad", "id_mpio", "fecha"]
    return pd.read_parquet(ruta, columns=columnas)


# ---------------------------------------------------------------------------
# Preparación común
# ---------------------------------------------------------------------------
def horas_observadas(fact: pd.DataFrame) -> pd.DataFrame:
    """Observaciones localidad-mes con horas de servicio válidas.

    Agrega columnas numéricas planas (`horas`, `energia`) para operar sin tipos anulables de pandas.
    """
    datos = fact.loc[fact["horas_servicio_promedio_dia"].notna()].copy()
    datos["horas"] = datos["horas_servicio_promedio_dia"].astype(float)
    datos["energia"] = pd.to_numeric(datos["energia_activa"], errors="coerce").astype(float)
    datos["periodo"] = pd.to_datetime(datos["periodo"])
    return datos


def perfil_tabla(df: pd.DataFrame) -> pd.DataFrame:
    """Perfil de una tabla: tipo, nulos, valores distintos y resumen de cinco números en las numéricas."""
    filas = []
    for columna in df.columns:
        serie = df[columna]
        fila = {
            "columna": columna,
            "tipo": str(serie.dtype),
            "nulos": int(serie.isna().sum()),
            "pct_nulos": round(100 * float(serie.isna().mean()), 2),
            "distintos": int(serie.nunique(dropna=True)),
        }
        if pd.api.types.is_numeric_dtype(serie) and not pd.api.types.is_bool_dtype(serie) and serie.notna().any():
            valores = serie.dropna().astype(float)
            fila.update(
                minimo=valores.min(), p25=valores.quantile(0.25), mediana=valores.median(),
                p75=valores.quantile(0.75), maximo=valores.max(), promedio=valores.mean(),
            )
        filas.append(fila)
    return pd.DataFrame(filas)


# ---------------------------------------------------------------------------
# Cobertura y estructura
# ---------------------------------------------------------------------------
def cobertura_mensual(fact: pd.DataFrame) -> pd.DataFrame:
    """Localidades que reportan cada mes, por departamento (filas = mes, columnas = código de departamento)."""
    tabla = fact.groupby(["periodo", "id_departamento"])["clave_localidad"].nunique().unstack("id_departamento").fillna(0).astype(int)
    tabla.index = pd.to_datetime(tabla.index)
    return tabla.sort_index()


def matriz_reporte(fact: pd.DataFrame, dim_localidad: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Matriz localidad x mes con las horas de servicio (nulo = la localidad no reportó ese mes).

    Devuelve (matriz, orden): `orden` trae el departamento y el número de meses de cada localidad, y las
    filas de la matriz ya vienen ordenadas por departamento (código DANE) y, dentro de cada uno, por
    continuidad del reporte (más meses primero).
    """
    datos = horas_observadas(fact)
    matriz = datos.pivot(index="clave_localidad", columns="periodo", values="horas")
    todos_los_meses = pd.date_range(matriz.columns.min(), matriz.columns.max(), freq="MS")
    matriz = matriz.reindex(columns=todos_los_meses)
    orden = (
        datos.groupby("clave_localidad")
        .agg(id_departamento=("id_departamento", "first"), meses=("periodo", "nunique"), horas_promedio=("horas", "mean"))
        .reset_index()
    )
    nombres = dim_localidad[["clave_localidad", "nombre_localidad", "nombre_municipio"]]
    orden = orden.merge(nombres, on="clave_localidad", how="left")
    orden = orden.sort_values(["id_departamento", "meses", "horas_promedio"], ascending=[True, False, False]).reset_index(drop=True)
    return matriz.reindex(orden["clave_localidad"]), orden


def concentracion_energia(fact: pd.DataFrame, dim_localidad: pd.DataFrame) -> pd.DataFrame:
    """Energía activa acumulada por localidad, su participación y la participación acumulada (de mayor a menor)."""
    datos = horas_observadas(fact)
    total = datos.groupby("clave_localidad")["energia"].sum().sort_values(ascending=False).rename("energia_total").reset_index()
    total["participacion"] = total["energia_total"] / total["energia_total"].sum()
    total["participacion_acumulada"] = total["participacion"].cumsum()
    total["rango"] = np.arange(1, len(total) + 1)
    nombres = dim_localidad[["clave_localidad", "nombre_localidad", "nombre_municipio", "id_departamento"]]
    return total.merge(nombres, on="clave_localidad", how="left")


def localidades_para_participacion(concentracion: pd.DataFrame, umbral: float = 0.8) -> int:
    """Cuántas localidades (de mayor a menor energía) hacen falta para acumular `umbral` de la energía."""
    return int((concentracion["participacion_acumulada"] < umbral).sum() + 1)


def correlaciones_spearman(fact: pd.DataFrame) -> pd.DataFrame:
    """Correlación de Spearman (por rangos: robusta a la asimetría) entre horas, energías y potencia máxima."""
    datos = horas_observadas(fact)
    columnas = {
        "horas": "Horas de servicio",
        "energia": "Energía activa",
        "energia_reactiva": "Energía reactiva",
        "potencia_maxima": "Potencia máxima",
    }
    tabla = datos.assign(
        energia_reactiva=pd.to_numeric(datos["energia_reactiva"], errors="coerce").astype(float),
        potencia_maxima=pd.to_numeric(datos["potencia_maxima"], errors="coerce").astype(float),
    )[list(columnas)].corr(method="spearman")
    return tabla.rename(index=columnas, columns=columnas)


# ---------------------------------------------------------------------------
# Estado, brechas y rankings
# ---------------------------------------------------------------------------
def estado_reciente(fact: pd.DataFrame, meses: int | None = None) -> pd.DataFrame:
    """Horas de servicio por departamento en los últimos `meses` meses con datos (más una fila de región).

    Columnas: `codigo` (DANE o 'REGION'), `horas`, `brecha` (24 - horas), observaciones, localidades que
    reportaron en la ventana, y la ventana (`desde`, `hasta`).
    """
    meses = meses or PARAMETROS["ventana_estado_reciente_meses"]
    datos = horas_observadas(fact)
    hasta = datos["periodo"].max()
    desde = (hasta.to_period("M") - (meses - 1)).to_timestamp()
    ventana = datos[datos["periodo"] >= desde]

    def resumir(grupo: pd.DataFrame, codigo: str) -> dict:
        return {
            "codigo": codigo,
            "horas": grupo["horas"].mean(),
            "brecha": HORAS_DIA - grupo["horas"].mean(),
            "observaciones": int(len(grupo)),
            "localidades": int(grupo["clave_localidad"].nunique()),
            "sin_servicio": int((~grupo["con_servicio"].astype(bool)).sum()),
            "desde": desde,
            "hasta": hasta,
        }

    filas = [resumir(grupo, str(codigo)) for codigo, grupo in ventana.groupby("id_departamento")]
    filas.append(resumir(ventana, "REGION"))
    return pd.DataFrame(filas)


def ultimo_mes_con_datos(fact: pd.DataFrame) -> dict:
    """Foto del último mes con datos: localidades que reportaron, con servicio y horas promedio."""
    datos = horas_observadas(fact)
    ultimo = datos["periodo"].max()
    mes = datos[datos["periodo"] == ultimo]
    return {
        "periodo": ultimo,
        "localidades_reportadas": int(mes["clave_localidad"].nunique()),
        "localidades_con_servicio": int(mes.loc[mes["con_servicio"].astype(bool), "clave_localidad"].nunique()),
        "horas_promedio": float(mes["horas"].mean()),
        "energia_activa_total": float(mes["energia"].sum()),
    }


def ranking_municipios_brecha(fact: pd.DataFrame, dim_municipio: pd.DataFrame) -> pd.DataFrame:
    """Brecha de horas (24 - horas promedio) por municipio con prestación, de mayor a menor brecha."""
    datos = horas_observadas(fact)
    resumen = (
        datos.groupby("id_municipio")
        .agg(
            id_departamento=("id_departamento", "first"),
            horas=("horas", "mean"),
            observaciones=("horas", "size"),
            localidades=("clave_localidad", "nunique"),
            meses=("periodo", "nunique"),
        )
        .reset_index()
    )
    resumen["brecha"] = HORAS_DIA - resumen["horas"]
    resumen["evidencia_baja"] = resumen["observaciones"] < PARAMETROS["observaciones_minimas_evidencia"]
    nombres = dim_municipio[["id_municipio", "nombre_municipio"]]
    resumen = resumen.merge(nombres, on="id_municipio", how="left")
    return resumen.sort_values("brecha", ascending=False).reset_index(drop=True)


def localidades_con_menos_horas(fact: pd.DataFrame, dim_localidad: pd.DataFrame, cuantas: int = 15, meses_minimos: int | None = None) -> pd.DataFrame:
    """Las localidades con menos horas de servicio promedio, exigiendo un mínimo de meses reportados."""
    meses_minimos = meses_minimos or PARAMETROS["meses_minimos_ranking_localidad"]
    datos = horas_observadas(fact)
    resumen = (
        datos.groupby("clave_localidad")
        .agg(id_departamento=("id_departamento", "first"), horas=("horas", "mean"), meses=("periodo", "nunique"), meses_sin_servicio=("con_servicio", lambda s: int((~s.astype(bool)).sum())))
        .reset_index()
    )
    resumen = resumen[resumen["meses"] >= meses_minimos]
    nombres = dim_localidad[["clave_localidad", "nombre_localidad", "nombre_municipio"]]
    resumen = resumen.merge(nombres, on="clave_localidad", how="left").sort_values(["horas", "clave_localidad"]).head(cuantas)
    resumen["brecha"] = HORAS_DIA - resumen["horas"]
    return resumen.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Evolución
# ---------------------------------------------------------------------------
def evolucion_departamentos(ind_horas_departamento: pd.DataFrame, ventana_movil: int = 6) -> pd.DataFrame:
    """Serie mensual de horas promedio por departamento, con promedio móvil de `ventana_movil` meses.

    La serie se completa mes a mes (los meses sin reporte quedan nulos) para que el promedio móvil se mida en
    meses de calendario y no en filas.
    """
    datos = ind_horas_departamento[["id_departamento", "periodo", "horas_servicio_promedio", "n_localidades_reportadas"]].copy()
    datos["periodo"] = pd.to_datetime(datos["periodo"])
    meses = pd.date_range(datos["periodo"].min(), datos["periodo"].max(), freq="MS")
    salida = []
    for codigo, grupo in datos.groupby("id_departamento"):
        serie = grupo.set_index("periodo").reindex(meses)
        horas = serie["horas_servicio_promedio"].astype(float)
        salida.append(
            pd.DataFrame(
                {
                    "id_departamento": str(codigo),
                    "periodo": meses,
                    "horas": horas.to_numpy(),
                    "horas_movil": horas.rolling(ventana_movil, min_periods=max(2, ventana_movil // 2)).mean().to_numpy(),
                    "localidades": serie["n_localidades_reportadas"].to_numpy(),
                }
            )
        )
    return pd.concat(salida, ignore_index=True)


def evolucion_region(fact: pd.DataFrame, ventana_movil: int = 6) -> pd.DataFrame:
    """Serie mensual de horas promedio de la región completa (todas las observaciones del mes)."""
    datos = horas_observadas(fact)
    serie = datos.groupby("periodo")["horas"].mean()
    serie = serie.reindex(pd.date_range(serie.index.min(), serie.index.max(), freq="MS"))
    return pd.DataFrame({"periodo": serie.index, "horas": serie.to_numpy(), "horas_movil": serie.rolling(ventana_movil, min_periods=max(2, ventana_movil // 2)).mean().to_numpy()})


def desviacion_respecto_a_la_localidad_anio(fact: pd.DataFrame, meses_minimos: int | None = None) -> pd.DataFrame:
    """Horas menos el promedio de la misma localidad EN EL MISMO AÑO (aísla la variación entre meses del año).

    Al quitar también el nivel de cada año se elimina la tendencia, que de otro modo se confundiría con la
    estacionalidad (enero aparece 7 veces en la serie y los demás meses 6).
    """
    meses_minimos = meses_minimos or PARAMETROS["meses_minimos_localidad_anio"]
    datos = horas_observadas(fact)
    meses = datos.groupby(["clave_localidad", "anio"])["horas"].transform("size")
    datos = datos[meses >= meses_minimos].copy()
    datos["desviacion"] = datos["horas"] - datos.groupby(["clave_localidad", "anio"])["horas"].transform("mean")
    return datos


def media_con_intervalo(
    datos: pd.DataFrame,
    grupo: str,
    valor: str = "desviacion",
    conglomerado: str = "clave_localidad",
    remuestreos: int | None = None,
    semilla: int | None = None,
    nivel: float = 0.95,
) -> pd.DataFrame:
    """Media de `valor` por `grupo` con intervalo de confianza por bootstrap de conglomerados.

    Se remuestrean LOCALIDADES completas (no observaciones sueltas): las observaciones de una misma localidad
    se parecen entre sí, y tratarlas como independientes daría intervalos engañosamente estrechos.
    """
    remuestreos = remuestreos or PARAMETROS["remuestreos_bootstrap"]
    semilla = PARAMETROS["semilla"] if semilla is None else semilla
    grupos = sorted(datos[grupo].unique())
    conglomerados = sorted(datos[conglomerado].unique())
    suma = datos.pivot_table(index=conglomerado, columns=grupo, values=valor, aggfunc="sum", fill_value=0.0).reindex(index=conglomerados, columns=grupos, fill_value=0.0)
    cuenta = datos.pivot_table(index=conglomerado, columns=grupo, values=valor, aggfunc="count", fill_value=0).reindex(index=conglomerados, columns=grupos, fill_value=0)
    sumas, cuentas = suma.to_numpy(float), cuenta.to_numpy(float)

    generador = np.random.default_rng(semilla)
    indices = generador.integers(0, len(conglomerados), size=(remuestreos, len(conglomerados)))
    s, n = sumas[indices].sum(axis=1), cuentas[indices].sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        medias = np.where(n > 0, s / n, np.nan)
    alfa = (1 - nivel) / 2 * 100
    with np.errstate(invalid="ignore"):
        inferior = np.nanpercentile(medias, alfa, axis=0)
        superior = np.nanpercentile(medias, 100 - alfa, axis=0)
    return pd.DataFrame(
        {
            grupo: grupos,
            "media": sumas.sum(axis=0) / np.where(cuentas.sum(axis=0) > 0, cuentas.sum(axis=0), np.nan),
            "inferior": inferior,
            "superior": superior,
            "observaciones": cuentas.sum(axis=0).astype(int),
            "localidades": (cuentas > 0).sum(axis=0).astype(int),
        }
    )


def cambio_por_localidad(
    fact: pd.DataFrame,
    dim_localidad: pd.DataFrame,
    ventana_inicial: tuple[int, ...] | None = None,
    ventana_final: tuple[int, ...] | None = None,
    observaciones_minimas: int | None = None,
) -> pd.DataFrame:
    """Horas promedio de cada localidad en dos ventanas de años y su cambio ("antes" -> "después").

    Compara cada localidad consigo misma, así que el resultado no depende de cuántas ni cuáles localidades
    reportan en cada ventana (el defecto de comparar promedios anuales de toda la región). Solo entran las
    localidades con `observaciones_minimas` meses reportados en AMBAS ventanas. De mayor a menor cambio.
    """
    ventana_inicial = tuple(ventana_inicial or PARAMETROS["ventana_inicial"])
    ventana_final = tuple(ventana_final or PARAMETROS["ventana_final"])
    minimo = observaciones_minimas or PARAMETROS["observaciones_minimas_ventana"]
    datos = horas_observadas(fact)

    def promedio_en(anios: tuple[int, ...], sufijo: str) -> pd.DataFrame:
        resumen = datos[datos["anio"].isin(anios)].groupby("clave_localidad")["horas"].agg(["mean", "size"])
        return resumen.rename(columns={"mean": f"horas_{sufijo}", "size": f"observaciones_{sufijo}"})

    cambio = promedio_en(ventana_inicial, "antes").join(promedio_en(ventana_final, "despues"), how="inner")
    cambio = cambio[(cambio["observaciones_antes"] >= minimo) & (cambio["observaciones_despues"] >= minimo)].reset_index()
    cambio["cambio"] = cambio["horas_despues"] - cambio["horas_antes"]
    nombres = dim_localidad[["clave_localidad", "nombre_localidad", "nombre_municipio", "id_departamento"]]
    cambio = cambio.merge(nombres, on="clave_localidad", how="left")
    return cambio.sort_values(["cambio", "clave_localidad"], ascending=[False, True]).reset_index(drop=True)


def resumen_cambio(
    cambio: pd.DataFrame,
    remuestreos: int | None = None,
    semilla: int | None = None,
    nivel: float = 0.95,
    umbral: float | None = None,
) -> dict:
    """Resume el cambio por localidad: mediana (con intervalo por bootstrap), media y cuántas mejoran o empeoran.

    `umbral` (horas) separa "mejora" y "empeora" de "se mantiene". También se reporta la media sin las dos mayores
    mejoras: si difiere mucho de la media completa, el promedio lo mueven muy pocas localidades.
    """
    remuestreos = remuestreos or PARAMETROS["remuestreos_bootstrap"]
    semilla = PARAMETROS["semilla"] if semilla is None else semilla
    umbral = PARAMETROS["umbral_cambio_horas"] if umbral is None else umbral
    valores = cambio["cambio"].to_numpy(float)
    if len(valores) == 0:
        return {"localidades": 0}
    generador = np.random.default_rng(semilla)
    medianas = np.median(valores[generador.integers(0, len(valores), size=(remuestreos, len(valores)))], axis=1)
    alfa = (1 - nivel) / 2 * 100
    ordenados = np.sort(valores)
    return {
        "localidades": int(len(valores)),
        "mediana": float(np.median(valores)),
        "mediana_inferior": float(np.percentile(medianas, alfa)),
        "mediana_superior": float(np.percentile(medianas, 100 - alfa)),
        "media": float(valores.mean()),
        "media_sin_las_dos_mayores_mejoras": float(ordenados[:-2].mean()) if len(valores) > 2 else float("nan"),
        "mejoran": int((valores > umbral).sum()),
        "empeoran": int((valores < -umbral).sum()),
        "se_mantienen": int((np.abs(valores) <= umbral).sum()),
        "umbral_horas": float(umbral),
    }

# ---------------------------------------------------------------------------
# Operadores
# ---------------------------------------------------------------------------
_FIN = r"(?=\s|$)"
# Razón social (se quita): S.A. E.S.P., E.S.P., E.A.T., S.A.
_RAZON_SOCIAL = [
    r"\bS\.?\s?A\.?\s?S?\.?\s+E\.?\s?S\.?\s?P\.?" + _FIN,
    r"\bE\.?\s?S\.?\s?P\.?" + _FIN,
    r"\bE\.?\s?A\.?\s?T\.?" + _FIN,
    r"\bS\.\s?A\.?" + _FIN,
]
# Fórmulas largas de los nombres de operadores -> abreviatura (solo para mostrar).
_FORMULAS_OPERADOR = [
    (r"EMPRESA ASOCIATIVA DE TRABAJO(?:\s+DE PRESTACION DE SERVICIOS PUBLICOS)?(?:\s+DE)?" + _FIN, "EAT"),
    (r"EMPRESA DE SERVICIOS P[ÚU]BLICOS(?:\s+DOMICILIARIOS)?(?:\s+DE)?" + _FIN, "ESP"),
    (r"ASOCIACI[ÓO]N DE USUARIOS DEL SERVICIO DE ENERG[ÍI]A EL[ÉE]CTRICA DE LA ZONA RURAL DE" + _FIN, "Asoc. usuarios rural"),
    (r"ASOCIACI[ÓO]N DE ENERG[ÍI]A DE LAS ZONAS RURALES DEL MUNICIPIO DE" + _FIN, "Asoc. energía rural"),
    (r"COOPERATIVA DE SERVICIOS P[ÚU]BLICOS DE" + _FIN, "Coop. servicios públicos"),
    (r"EMPRESA DE ENERG[ÍI]A DE LA ZONA RURAL DE" + _FIN, "Energía rural"),
    (r"EMPRESA DE ENERG[ÍI]A(?:\s+DE)?" + _FIN, "Energía"),
]
_PALABRAS_MENORES = {"de", "del", "la", "las", "los", "y", "en"}
_SIGLAS = {"ESP", "EAT"}
# Tildes que algunos nombres de la fuente traen sin escribir (solo para mostrar).
_TILDES = {
    "energia": "energía", "electrica": "eléctrica", "publicos": "públicos", "pacifico": "pacífico", "narino": "nariño",
    "iscuande": "iscuandé", "leguizamo": "leguízamo", "barbara": "bárbara", "guapi": "guapí", "lopez": "lópez",
}


def _formatear_palabra(palabra: str, posicion: int) -> str:
    """Una palabra de un nombre de operador en formato título (siglas en mayúscula, conectores en minúscula)."""
    clave = palabra.lower()
    if palabra.upper() in _SIGLAS:
        return palabra.upper()
    if posicion > 0 and clave in _PALABRAS_MENORES:
        return clave
    if palabra.endswith("."):
        return palabra  # ya viene abreviada ('Asoc.', 'Coop.')
    return _TILDES.get(clave, clave).capitalize()


def abreviar_operador(nombre: str, maximo: int = 48) -> str:
    """Nombre corto de un operador para etiquetas: quita la razón social y abrevia fórmulas largas.

    Si el nombre trae una sigla de marca tras un guion (p. ej. '... - ENERPLASO S.A. E.S.P.') se usa solo la
    sigla. Es una abreviatura para mostrar; el nombre completo viaja en las tablas de apoyo.
    """
    if nombre is None or (isinstance(nombre, float) and np.isnan(nombre)):
        return "s. d."
    texto = re.sub(r"\s+", " ", str(nombre)).strip()
    marca = re.search(r"\s-\s([A-ZÁÉÍÓÚÑ]{4,})\b", texto)
    if marca:
        return marca.group(1).capitalize()
    for patron in _RAZON_SOCIAL:
        texto = re.sub(patron, "", texto, flags=re.IGNORECASE)
    for patron, reemplazo in _FORMULAS_OPERADOR:
        texto = re.sub(patron, reemplazo, texto, flags=re.IGNORECASE)
    texto = re.sub(r"\s+", " ", texto).strip(" -.,")
    corto = " ".join(_formatear_palabra(palabra, posicion) for posicion, palabra in enumerate(texto.split(" ")))
    return corto if len(corto) <= maximo else corto[: maximo - 1].rstrip() + "…"


# ---------------------------------------------------------------------------
# PQR
# ---------------------------------------------------------------------------
def pqr_por_municipio(ind_pqr_empresa_municipio: pd.DataFrame, cuantos: int = 10) -> pd.DataFrame:
    """Casos de PQR acumulados por municipio (todos los semestres cubiertos), de mayor a menor."""
    resumen = (
        ind_pqr_empresa_municipio.groupby(["id_municipio", "nombre_municipio", "id_departamento"], as_index=False)
        .agg(n_pqr=("n_pqr", "sum"), n_con_respuesta=("n_con_respuesta", "sum"), empresas=("id_empresa", "nunique"))
        .sort_values(["n_pqr", "nombre_municipio"], ascending=[False, True])
    )
    return resumen.head(cuantos).reset_index(drop=True)


def pqr_frente_a_horas(ind_pqr_vs_horas: pd.DataFrame) -> pd.DataFrame:
    """Municipio-semestre comparables: casos de PQR (0 si el semestre estaba cubierto y no hubo casos) y horas.

    Se descartan los semestres fuera de la cobertura de PQR ('sin dato vigente'), donde el conteo es nulo y no cero.
    """
    comparables = ind_pqr_vs_horas[ind_pqr_vs_horas["estado_pqr"] != "sin dato vigente"].copy()
    comparables["casos"] = comparables["n_pqr_total"].fillna(0).astype(float)
    comparables["horas"] = comparables["horas_servicio_promedio"].astype(float)
    return comparables.reset_index(drop=True)


def correlacion_pqr_horas(comparables: pd.DataFrame) -> dict:
    """Spearman entre casos de PQR y horas de servicio de los municipio-semestre comparables."""
    if len(comparables) < 3:
        return {"rho": np.nan, "pares": int(len(comparables))}
    return {"rho": float(comparables[["casos", "horas"]].corr(method="spearman").iloc[0, 1]), "pares": int(len(comparables))}


# ---------------------------------------------------------------------------
# Operación diaria (silver): contexto de la flota y de las horas declaradas
# ---------------------------------------------------------------------------
def contexto_operacion_diaria(operacion: pd.DataFrame) -> dict:
    """Resumen de la bitácora diaria: flota por marca, capacidad por generador y horas declaradas por registro."""
    datos = operacion.copy()
    datos["marca"] = datos["marca"].astype("string").str.strip().str.upper()
    datos["tiempo_servicio"] = datos["tiempo_servicio"].astype(float)
    por_generador = (
        datos.groupby("serie_generador")
        .agg(marca=("marca", lambda s: s.mode().iat[0] if not s.mode().empty else "s. d."), capacidad=("capacidad_generacion", "median"))
        .reset_index()
    )
    por_generador["capacidad"] = por_generador["capacidad"].astype(float)
    marcas = por_generador["marca"].value_counts().rename_axis("marca").reset_index(name="generadores")
    horas_registro = datos["tiempo_servicio"].round().clip(upper=12).astype(int)
    distribucion_horas = horas_registro.value_counts(normalize=True).sort_index().rename("proporcion").reset_index().rename(columns={"tiempo_servicio": "horas"})
    return {
        "registros": int(len(datos)),
        "localidades": int(datos["codigo_localidad"].nunique()),
        "municipios": int(datos["id_mpio"].nunique()),
        "generadores": int(len(por_generador)),
        "marcas": marcas,
        "capacidad": por_generador["capacidad"],
        "distribucion_horas": distribucion_horas,
        "proporcion_calculado": float((datos["tipo_medida"].astype("string").str.upper() == "CALCULADO").mean()),
        "proporcion_4_5_u_8_horas": float(datos["tiempo_servicio"].round().isin([4, 5, 8]).mean()),
        "desde": pd.to_datetime(datos["fecha"]).min(),
        "hasta": pd.to_datetime(datos["fecha"]).max(),
    }


# ---------------------------------------------------------------------------
# Texto de presentación
# ---------------------------------------------------------------------------
def titulo_nombre(nombre: str) -> str:
    """'SANTA BÁRBARA (ISCUANDÉ)' -> 'Santa Bárbara (Iscuandé)' (solo para mostrar)."""
    menores = {"de", "del", "la", "las", "los", "y"}
    palabras = []
    for posicion, palabra in enumerate(str(nombre).lower().split()):
        prefijo = "(" if palabra.startswith("(") else ""
        nucleo = palabra[len(prefijo):]
        palabras.append(palabra if posicion > 0 and nucleo in menores else prefijo + nucleo.capitalize())
    return " ".join(palabras)


# ---------------------------------------------------------------------------
# Tablas de apoyo ("la versión en tabla" de cada figura) y hallazgos
# ---------------------------------------------------------------------------
def tablas_de_apoyo(g: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Tablas que respaldan las figuras: cada gráfico tiene su equivalente en tabla (accesibilidad y verificación)."""
    fact, dim_localidad, dim_municipio = g["fact_prestacion"], g["dim_localidad"], g["dim_municipio"]
    desviacion_anio = desviacion_respecto_a_la_localidad_anio(fact)
    operadores = g["ind_comparacion_operadores"].copy()
    operadores.insert(2, "nombre_corto", operadores["nombre_operador"].map(abreviar_operador))
    cobertura = cobertura_mensual(fact)
    cobertura["total"] = cobertura.sum(axis=1)
    cobertura.index.name = "periodo"
    return {
        "perfil_fact_prestacion": perfil_tabla(fact),
        "cobertura_mensual": cobertura.reset_index(),
        "concentracion_energia": concentracion_energia(fact, dim_localidad),
        "correlaciones_spearman": correlaciones_spearman(fact).reset_index(names="variable"),
        "estado_reciente": estado_reciente(fact),
        "ranking_municipios_brecha": ranking_municipios_brecha(fact, dim_municipio),
        "evolucion_departamentos": evolucion_departamentos(g["ind_horas_servicio_departamento"]),
        "cambio_por_localidad": cambio_por_localidad(fact, dim_localidad),
        "estacionalidad": media_con_intervalo(desviacion_anio, "mes"),
        "operadores": operadores,
        "pqr_por_municipio": pqr_por_municipio(g["ind_pqr_empresa_municipio"], cuantos=15),
        "localidades_menos_horas": localidades_con_menos_horas(fact, dim_localidad, cuantas=15),
    }


def _periodo(fecha) -> str:
    return pd.Timestamp(fecha).strftime("%Y-%m")


def _pct_localidades_enlazables(meta_uniones: pd.DataFrame | None) -> float:
    """% de localidades de prestación a las que se puede asignar operador (100 menos las 'sin operador enlazable')."""
    if meta_uniones is None:
        return float("nan")
    fila = meta_uniones[
        (meta_uniones["nombre_union"] == "prestacion_operacion_diaria") & (meta_uniones["prueba"] == "cruce_prestacion_operacion_diaria")
    ]
    return 100 - float(fila["metrica"].iloc[0]) if len(fila) else float("nan")


def calcular_hallazgos(g: dict[str, pd.DataFrame], operacion: pd.DataFrame | None = None) -> dict:
    """Cifras clave del análisis en un diccionario (se guarda como hallazgos.json).

    Las usan las figuras, el notebook y la presentación, para que ningún número se transcriba a mano.
    No lleva marca de tiempo: con los mismos datos el archivo sale idéntico.
    """
    fact, dim_localidad, dim_municipio = g["fact_prestacion"], g["dim_localidad"], g["dim_municipio"]
    datos = horas_observadas(fact)
    horas = datos["horas"]
    por_localidad = datos.groupby("clave_localidad")["horas"].mean()
    cobertura = cobertura_mensual(fact).sum(axis=1)
    meses_por_localidad = datos.groupby("clave_localidad")["periodo"].nunique()
    n_meses = int(datos["periodo"].nunique())
    energia = concentracion_energia(fact, dim_localidad)
    correlaciones = correlaciones_spearman(fact)
    estado = estado_reciente(fact)
    ultimo = ultimo_mes_con_datos(fact)
    ranking = ranking_municipios_brecha(fact, dim_municipio)
    menos = localidades_con_menos_horas(fact, dim_localidad, cuantas=15)
    cambio = cambio_por_localidad(fact, dim_localidad)
    resumen = resumen_cambio(cambio)
    estacional = media_con_intervalo(desviacion_respecto_a_la_localidad_anio(fact), "mes")
    operadores = g["ind_comparacion_operadores"].sort_values("horas_servicio_promedio", ascending=False)
    pqr_municipios = pqr_por_municipio(g["ind_pqr_empresa_municipio"], cuantos=10)
    comparables = pqr_frente_a_horas(g["ind_pqr_vs_horas_municipio"])
    pqr_total = int(g["ind_pqr_empresa_municipio"]["n_pqr"].sum())
    con_respuesta = int(g["ind_pqr_empresa_municipio"]["n_con_respuesta"].sum())
    peor = g["ind_peor_desempeno_municipio"].sort_values("ranking_peor_desempeno")
    meta = g["meta_fuentes"]
    kpis = g["kpis_pipeline"]

    def por_departamento(tabla: pd.DataFrame) -> dict:
        return {
            str(fila.codigo): {"horas": fila.horas, "brecha": fila.brecha, "localidades": fila.localidades, "observaciones": fila.observaciones}
            for fila in tabla.itertuples()
        }

    hallazgos = {
        "alcance": {
            "localidades": int(fact["clave_localidad"].nunique()),
            "municipios_con_prestacion": int(fact["id_municipio"].nunique()),
            "observaciones": int(len(datos)),
            "meses": n_meses,
            "periodo_desde": _periodo(datos["periodo"].min()),
            "periodo_hasta": _periodo(datos["periodo"].max()),
            "fecha_referencia": pd.Timestamp(meta["fecha_referencia"].iloc[0]).strftime("%Y-%m-%d"),
        },
        "horas": {
            "mediana": horas.median(), "promedio": horas.mean(), "p25": horas.quantile(0.25), "p75": horas.quantile(0.75),
            "pct_servicio_casi_continuo": 100 * float((horas >= 23).mean()),
            "observaciones_sin_energia": int((horas <= 0).sum()),
            "mediana_por_localidad": por_localidad.median(),
            "localidades_menos_de_6_horas": int((por_localidad < 6).sum()),
            "localidades_12_horas_o_mas": int((por_localidad >= 12).sum()),
        },
        "cobertura": {
            "minimo": int(cobertura.min()), "mes_minimo": _periodo(cobertura.idxmin()),
            "maximo": int(cobertura.max()), "mes_maximo": _periodo(cobertura.idxmax()),
            "localidades_casi_todos_los_meses": int((meses_por_localidad >= np.ceil(0.8 * n_meses)).sum()),
            "localidades_12_meses_o_menos": int((meses_por_localidad <= 12).sum()),
        },
        "energia": {
            "localidad_principal": titulo_nombre(energia.iloc[0]["nombre_localidad"]),
            "participacion_principal_pct": 100 * float(energia.iloc[0]["participacion"]),
            "localidades_para_80_pct": localidades_para_participacion(energia, 0.8),
        },
        "correlaciones": {
            "horas_energia_activa": correlaciones.loc["Horas de servicio", "Energía activa"],
            "horas_energia_reactiva": correlaciones.loc["Horas de servicio", "Energía reactiva"],
            "horas_potencia_maxima": correlaciones.loc["Horas de servicio", "Potencia máxima"],
        },
        "estado_reciente": {
            "ventana_desde": _periodo(estado["desde"].iloc[0]),
            "ventana_hasta": _periodo(estado["hasta"].iloc[0]),
            "region": por_departamento(estado[estado["codigo"] == "REGION"])["REGION"],
            "departamentos": por_departamento(estado[estado["codigo"] != "REGION"]),
            "ultimo_mes": {
                "periodo": _periodo(ultimo["periodo"]), "localidades_reportadas": ultimo["localidades_reportadas"],
                "localidades_con_servicio": ultimo["localidades_con_servicio"], "horas_promedio": ultimo["horas_promedio"],
            },
        },
        "municipios_mayor_brecha": [
            {"municipio": titulo_nombre(f.nombre_municipio), "departamento": str(f.id_departamento), "horas": f.horas, "brecha": f.brecha, "observaciones": int(f.observaciones), "localidades": int(f.localidades)}
            for f in ranking.head(10).itertuples()
        ],
        "municipios_menor_brecha": [
            {"municipio": titulo_nombre(f.nombre_municipio), "departamento": str(f.id_departamento), "horas": f.horas, "brecha": f.brecha}
            for f in ranking.tail(2).iloc[::-1].itertuples()
        ],
        "localidades_menos_horas": [
            {"localidad": titulo_nombre(f.nombre_localidad), "municipio": titulo_nombre(f.nombre_municipio), "horas": f.horas, "meses": int(f.meses)}
            for f in menos.head(8).itertuples()
        ],
        "cambio_por_localidad": {
            **resumen,
            "ventana_inicial": [int(a) for a in PARAMETROS["ventana_inicial"]],
            "ventana_final": [int(a) for a in PARAMETROS["ventana_final"]],
            "mayores_mejoras": [
                {"localidad": titulo_nombre(f.nombre_localidad), "municipio": titulo_nombre(f.nombre_municipio), "departamento": str(f.id_departamento), "antes": f.horas_antes, "despues": f.horas_despues, "cambio": f.cambio}
                for f in cambio.head(2).itertuples()
            ],
            "tercera_mayor_mejora": float(cambio["cambio"].iloc[2]) if len(cambio) > 2 else float("nan"),
            "mayor_retroceso": float(cambio["cambio"].iloc[-1]) if len(cambio) else float("nan"),
        },
        "estacionalidad": {
            "mes_mas_alto": int(estacional.loc[estacional["media"].idxmax(), "mes"]), "valor_mas_alto": estacional["media"].max(),
            "mes_mas_bajo": int(estacional.loc[estacional["media"].idxmin(), "mes"]), "valor_mas_bajo": estacional["media"].min(),
        },
        "operadores": {
            "total": int(len(operadores)),
            "mejor": {"nombre": abreviar_operador(operadores.iloc[0]["nombre_operador"]), "horas": operadores.iloc[0]["horas_servicio_promedio"], "localidades": int(operadores.iloc[0]["n_localidades"]), "meses": int(operadores.iloc[0]["n_meses"])},
            "peor": {"nombre": abreviar_operador(operadores.iloc[-1]["nombre_operador"]), "horas": operadores.iloc[-1]["horas_servicio_promedio"], "localidades": int(operadores.iloc[-1]["n_localidades"]), "meses": int(operadores.iloc[-1]["n_meses"])},
            "promedio_ponderado": float((operadores["horas_servicio_promedio"] * operadores["n_observaciones_horas"]).sum() / operadores["n_observaciones_horas"].sum()),
            "pct_localidades_con_operador_enlazable": _pct_localidades_enlazables(g.get("meta_uniones")),
            "periodo_desde": _periodo(operadores["periodo_desde"].min()), "periodo_hasta": _periodo(operadores["periodo_hasta"].max()),
        },
        "pqr": {
            "total": pqr_total,
            "pct_con_respuesta": 100 * con_respuesta / pqr_total if pqr_total else float("nan"),
            "tres_municipios_con_mas_casos": [titulo_nombre(n) for n in pqr_municipios["nombre_municipio"].head(3)],
            "participacion_tres_municipios_pct": 100 * float(pqr_municipios["n_pqr"].head(3).sum()) / pqr_total if pqr_total else float("nan"),
            "correlacion_con_horas": correlacion_pqr_horas(comparables),
        },
        "peor_desempeno_combinado": [
            {"municipio": titulo_nombre(f.nombre_municipio), "puntaje": f.puntaje_combinado, "ranking": int(f.ranking_peor_desempeno), "n_pqr": int(f.n_pqr_total), "brecha_horas": f.brecha_horas}
            for f in peor.head(3).itertuples()
        ],
        "fuentes": [
            {"fuente": f.fuente, "estado": f.estado_frescura, "ultimo_periodo": _periodo(f.ultimo_periodo_datos), "meses_sin_datos_nuevos": (pd.Timestamp(f.fecha_referencia).year - pd.Timestamp(f.ultimo_periodo_datos).year) * 12 + (pd.Timestamp(f.fecha_referencia).month - pd.Timestamp(f.ultimo_periodo_datos).month)}
            for f in meta.itertuples()
        ],
        "kpis_pipeline": {f.indicador: {"valor": f.valor, "meta": f.meta, "cumple": bool(f.cumple)} for f in kpis.itertuples()},
    }
    if operacion is not None:
        contexto = contexto_operacion_diaria(operacion)
        hallazgos["operacion_diaria"] = {
            "registros": contexto["registros"], "localidades": contexto["localidades"], "generadores": contexto["generadores"],
            "pct_calculado": 100 * contexto["proporcion_calculado"], "pct_4_5_u_8_horas": 100 * contexto["proporcion_4_5_u_8_horas"],
            "capacidad_mediana": float(contexto["capacidad"].median()),
        }
    return hallazgos
