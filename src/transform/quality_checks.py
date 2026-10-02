"""Pruebas de calidad reutilizables (sección 5 del diseño): cada función recibe datos ya
en silver (o conjuntos derivados de ellos) y devuelve una métrica más un aprobado/no
aprobado. Pensadas para usarse tanto en Fase 3 (validar silver) como en Fase 4 (decidir
qué uniones se implementan en gold: "ninguna unión se construye si no pasa estas pruebas").
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

_RAIZ_PROYECTO = Path(__file__).resolve().parent.parent.parent
if str(_RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_PROYECTO))

from src import cargar_configuracion  # noqa: E402

CONFIG = cargar_configuracion()


@dataclass
class ResultadoCalidad:
    """Resultado estandarizado de una prueba de calidad."""

    nombre_prueba: str
    metrica: float
    aprobado: bool
    detalle: dict[str, Any] = field(default_factory=dict)


def probar_unicidad_llave(df: pd.DataFrame, columnas_llave: list[str]) -> ResultadoCalidad:
    """Unicidad de la llave candidata de una fuente: aprueba solo con 0 duplicados.

    Si hay duplicados, el resultado los documenta (grupos y filas afectadas) para que se
    traten explícitamente antes de construir cualquier unión, como pide el diseño; esta
    función no decide por su cuenta cómo tratarlos (p. ej. sumar, quedarse con uno).
    """
    total = len(df)
    if total == 0:
        return ResultadoCalidad("unicidad_llave", 0.0, True, {"columnas_llave": columnas_llave, "filas_totales": 0})
    conteos = df.groupby(columnas_llave, dropna=False).size()
    grupos_duplicados = conteos[conteos > 1]
    filas_en_duplicados = int(grupos_duplicados.sum())
    pct_filas_duplicadas = round(100 * filas_en_duplicados / total, 2)
    return ResultadoCalidad(
        nombre_prueba="unicidad_llave",
        metrica=pct_filas_duplicadas,
        aprobado=(filas_en_duplicados == 0),
        detalle={
            "columnas_llave": columnas_llave,
            "filas_totales": total,
            "grupos_duplicados": int(len(grupos_duplicados)),
            "filas_en_duplicados": filas_en_duplicados,
        },
    )


def probar_validez_dane(
    serie: pd.Series, longitud_esperada: int, catalogo_valido: set[str] | None = None,
) -> ResultadoCalidad:
    """Validez del código DANE: % de valores con `longitud_esperada` dígitos (después de
    normalizar con ceros a la izquierda) y, si se pasa un catálogo DIVIPOLA, pertenencia
    a él. Sin catálogo, solo valida formato (no se inventa uno: ver sección 0 del prompt)."""
    umbral = CONFIG["umbrales_calidad"]["dane_valido_pct_minimo"]
    valores = serie.dropna().astype(str)
    total = len(valores)
    if total == 0:
        return ResultadoCalidad("validez_dane", 0.0, False, {"longitud_esperada": longitud_esperada, "motivo": "serie vacía"})

    formato_valido = valores.str.fullmatch(r"\d+").fillna(False) & (valores.str.len() == longitud_esperada)
    catalogo_usado = catalogo_valido is not None
    if catalogo_valido is not None:
        formato_valido = formato_valido & valores.isin(catalogo_valido)

    pct_valido = round(100 * formato_valido.mean(), 2)
    return ResultadoCalidad(
        nombre_prueba="validez_dane",
        metrica=pct_valido,
        aprobado=(pct_valido >= umbral),
        detalle={
            "longitud_esperada": longitud_esperada,
            "total_valores": total,
            "catalogo_divipola_usado": catalogo_usado,
            "umbral_minimo": umbral,
        },
    )


def probar_cruce_entre_fuentes(
    valores_a: pd.Series | set[str], valores_b: pd.Series | set[str], nombre_union: str,
) -> ResultadoCalidad:
    """% de llaves de A sin cruce en B para una unión candidata. Es un reporte (el diseño
    pide documentar el % sin cruce, no exige un umbral mínimo), por eso aprobado=True
    salvo que no se pueda calcular."""
    conjunto_a = set(valores_a.dropna()) if isinstance(valores_a, pd.Series) else set(valores_a)
    conjunto_b = set(valores_b.dropna()) if isinstance(valores_b, pd.Series) else set(valores_b)
    if not conjunto_a:
        return ResultadoCalidad(f"cruce_{nombre_union}", 0.0, False, {"motivo": "conjunto A vacío"})
    interseccion = conjunto_a & conjunto_b
    pct_sin_cruce = round(100 * (1 - len(interseccion) / len(conjunto_a)), 2)
    return ResultadoCalidad(
        nombre_prueba=f"cruce_{nombre_union}",
        metrica=pct_sin_cruce,
        aprobado=True,
        detalle={
            "n_valores_a": len(conjunto_a),
            "n_valores_b": len(conjunto_b),
            "n_interseccion": len(interseccion),
            "pct_sin_cruce": pct_sin_cruce,
        },
    )


def probar_cardinalidad_maxima(
    df: pd.DataFrame, columnas_llave: list[str], columna_a_contar: str, maximo_esperado: int,
) -> ResultadoCalidad:
    """Cardinalidad observada vs. esperada (matriz 4.1): máximo de valores distintos de
    columna_a_contar por grupo de columnas_llave (p. ej. ¿una localidad-mes tiene más de
    un operador?)."""
    conteos = df.groupby(columnas_llave, dropna=False)[columna_a_contar].nunique()
    maximo_observado = int(conteos.max()) if len(conteos) else 0
    grupos_que_exceden = int((conteos > maximo_esperado).sum())
    return ResultadoCalidad(
        nombre_prueba="cardinalidad_maxima",
        metrica=float(maximo_observado),
        aprobado=(maximo_observado <= maximo_esperado),
        detalle={
            "columnas_llave": columnas_llave,
            "columna_a_contar": columna_a_contar,
            "maximo_esperado": maximo_esperado,
            "grupos_totales": int(len(conteos)),
            "grupos_que_exceden": grupos_que_exceden,
        },
    )


def probar_identificador_empresa_comun(valores_a: pd.Series, valores_b: pd.Series) -> ResultadoCalidad:
    """Identificador de empresa común entre operacion_diaria y pqr (umbral >= 95%, sección 5).

    Perfilado (2026-09-30): en los datos reales este identificador NO es común entre las
    dos fuentes (0% de cruce; pqr resultó ser de empresas de gas, no de energía), así que
    se espera que esta prueba reporte aprobado=False — es el resultado correcto, no un
    error del código. Según la regla de respaldo del diseño, la unión operador-pqr se
    limita entonces a municipio.
    """
    umbral = CONFIG["umbrales_calidad"]["identificador_empresa_comun_pct_minimo"]
    conjunto_a = set(valores_a.dropna().astype(str))
    conjunto_b = set(valores_b.dropna().astype(str))
    if not conjunto_a or not conjunto_b:
        return ResultadoCalidad("identificador_empresa_comun", 0.0, False, {"motivo": "algún conjunto está vacío"})
    interseccion = conjunto_a & conjunto_b
    pct_comun = round(100 * len(interseccion) / len(conjunto_a), 2)
    return ResultadoCalidad(
        nombre_prueba="identificador_empresa_comun",
        metrica=pct_comun,
        aprobado=(pct_comun >= umbral),
        detalle={
            "n_valores_a": len(conjunto_a),
            "n_valores_b": len(conjunto_b),
            "n_interseccion": len(interseccion),
            "umbral_minimo": umbral,
        },
    )


def probar_campos_criticos_completos(df: pd.DataFrame, columnas: list[str]) -> ResultadoCalidad:
    """Campos críticos completos (KR2): % de REGISTROS que tienen presentes todos sus campos
    críticos. Aprueba si alcanza el umbral `campos_criticos_completos_pct_minimo` (98%).

    Es por registro (no por celda) para ser consistente con los otros indicadores de KR2: un
    registro al que le falta un solo campo crítico cuenta como incompleto.
    """
    umbral = CONFIG["umbrales_calidad"]["campos_criticos_completos_pct_minimo"]
    faltantes = [c for c in columnas if c not in df.columns]
    if faltantes or df.empty:
        return ResultadoCalidad(
            "campos_criticos_completos", 0.0, False,
            {"motivo": "columnas inexistentes o tabla vacía", "columnas_faltantes": faltantes},
        )
    no_nulos = df[columnas].notna()
    registros_completos = no_nulos.all(axis=1)
    pct = round(100 * float(registros_completos.mean()), 2)
    return ResultadoCalidad(
        nombre_prueba="campos_criticos_completos",
        metrica=pct,
        aprobado=(pct >= umbral),
        detalle={
            "umbral_minimo": umbral,
            "registros_evaluados": int(len(df)),
            "registros_completos": int(registros_completos.sum()),
            "pct_celdas_completas": round(100 * float(no_nulos.to_numpy().mean()), 2),
            "por_columna": {c: round(100 * float(no_nulos[c].mean()), 2) for c in columnas},
        },
    )


# Campos que, tras la limpieza de silver, SÍ son códigos DANE de longitud fija y estándar.
# codigo_localidad (operacion_diaria) usa un esquema propio de 13 dígitos y car_t1554_dane_mpio
# (pqr) es solo el consecutivo de 3 dígitos DENTRO del departamento (el municipio completo es
# id_mpio, ya compuesto): por eso no se validan sueltos como códigos de 5 u 8 dígitos.
CAMPOS_DANE_ESTANDAR: dict[str, list[tuple[str, int]]] = {
    "prestacion": [("id_dpto", 2), ("id_mpio", 5), ("id_localidad", 8)],
    "operacion_diaria": [("id_mpio", 5)],
    "pqr": [("id_mpio", 5)],
}


def diagnosticar_silver(silver: dict[str, pd.DataFrame]) -> list[dict]:
    """Corre sobre silver las pruebas que no comparan dos fuentes: unicidad de la llave, campos
    críticos completos y validez DANE. Las de cruce, cardinalidad e identificador de empresa las
    ejecuta gold antes de construir cada unión. Devuelve una fila por prueba."""
    filas: list[dict] = []

    def agregar(fuente: str, objeto: str, res: ResultadoCalidad, informativa: bool = False) -> None:
        filas.append({
            "fuente": fuente, "prueba": res.nombre_prueba, "objeto": objeto,
            "metrica": res.metrica, "aprobado": res.aprobado, "informativa": informativa,
        })

    for nombre, df in silver.items():
        cfg = CONFIG["fuentes"][nombre]
        # La llave de pqr es AGREGADA (municipio-año-semestre-empresa): sus filas crudas son casos
        # individuales, así que no se espera unicidad y la prueba se reporta solo como información.
        agregar(nombre, ", ".join(cfg["campos_llave"]), probar_unicidad_llave(df, cfg["campos_llave"]),
                informativa=bool(cfg.get("llave_es_agregada", False)))
        agregar(nombre, ", ".join(cfg["campos_criticos"]), probar_campos_criticos_completos(df, cfg["campos_criticos"]))
        for campo, longitud in CAMPOS_DANE_ESTANDAR.get(nombre, []):
            if campo in df.columns:
                agregar(nombre, f"{campo} ({longitud} dígitos)", probar_validez_dane(df[campo], longitud))
    return filas


if __name__ == "__main__":
    RUTA_SILVER = Path(CONFIG["rutas"]["silver"])
    silver_actual = {}
    for nombre in CONFIG["fuentes"]:
        ruta = RUTA_SILVER / f"{nombre}.parquet"
        if ruta.exists():
            silver_actual[nombre] = pd.read_parquet(ruta)
        else:
            print(f"[{nombre}] silver no encontrado en {ruta}; corre la etapa silver primero.")
    print("Autodiagnóstico de quality_checks.py contra data/silver/*.parquet")
    for fila in diagnosticar_silver(silver_actual):
        marca = "informativa" if fila["informativa"] else ("aprobada" if fila["aprobado"] else "NO aprobada")
        print(f"[{fila['fuente']}] {fila['prueba']} ({fila['objeto']}): {fila['metrica']}% -> {marca}")
