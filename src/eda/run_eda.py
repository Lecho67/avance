"""Análisis exploratorio (EDA) del modelo gold: figuras (PNG), tablas de apoyo (CSV), hallazgos.json e INDICE.md.

Lee las tablas de data/gold (las mismas que se cargan a PostgreSQL) y, para la figura de operación diaria,
data/silver/operacion_diaria.parquet. Todo se escribe en docs/eda:

    docs/eda/figuras/*.png     16 figuras (Matplotlib), una por hallazgo
    docs/eda/tablas/*.csv      la versión en tabla de cada figura
    docs/eda/hallazgos.json    cifras clave (las usan el notebook y la presentación)
    docs/eda/INDICE.md         qué muestra cada figura y qué pregunta del diseño responde

Es determinista: con los mismos datos de gold produce los mismos archivos.

Uso (desde la raíz del proyecto, con el entorno virtual activado):
    python src/eda/run_eda.py                         # todo
    python src/eda/run_eda.py --figuras fig07 fig10   # solo las figuras cuyo nombre contenga esos textos
    python src/eda/run_eda.py --diapositivas          # figuras de la presentación (sin título ni pie) -> docs/presentacion
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_RAIZ_PROYECTO = Path(__file__).resolve().parent.parent.parent
if str(_RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_PROYECTO))

from src import RAIZ_PROYECTO, cargar_configuracion, obtener_logger, registrar_error_controlado  # noqa: E402
from src.eda import analysis as an  # noqa: E402
from src.eda import charts  # noqa: E402
from src.eda import style as st  # noqa: E402

CONFIG = cargar_configuracion()
LOGGER = obtener_logger("eda", "eda.log")
RUTA_SALIDA = RAIZ_PROYECTO / CONFIG["rutas"]["eda"]
RUTA_PRESENTACION = RAIZ_PROYECTO / CONFIG["rutas"]["presentacion"]
PARAMETROS = CONFIG["eda"]


class ErrorEDA(RuntimeError):
    """Falla controlada del análisis exploratorio (faltan datos o alguna figura no se pudo generar)."""


def _nativo(valor):
    """Convierte numpy/pandas a tipos de Python para escribir JSON (sin marcas de tiempo; floats a 4 decimales)."""
    if isinstance(valor, dict):
        return {str(clave): _nativo(v) for clave, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [_nativo(v) for v in valor]
    if isinstance(valor, (bool, np.bool_)):
        return bool(valor)
    if isinstance(valor, (int, np.integer)):
        return int(valor)
    if isinstance(valor, (float, np.floating)):
        return None if np.isnan(valor) else round(float(valor), 4)
    if isinstance(valor, pd.Timestamp):
        return valor.strftime("%Y-%m-%d")
    return valor


def _escribir_indice(ruta: Path, figuras: dict[str, dict], tablas: list[str], hallazgos: dict) -> None:
    """INDICE.md: tabla de figuras (con el hallazgo de cada una) y de tablas de apoyo. Las cifras salen de `hallazgos`."""
    atraso = next(f["meses_sin_datos_nuevos"] for f in hallazgos["fuentes"] if f["fuente"] == "prestacion")
    cobertura, alcance = hallazgos["cobertura"], hallazgos["alcance"]
    lineas = [
        "# Análisis exploratorio (EDA)",
        "",
        "Generado por `python main.py --etapa eda` (o `python src/eda/run_eda.py`) a partir del modelo gold. Cada figura tiene su",
        "versión en tabla en `tablas/` y las cifras clave están en `hallazgos.json`. El título de cada figura es su hallazgo.",
        "",
        "| Figura | Sección | Hallazgo (título de la figura) |",
        "|---|---|---|",
    ]
    for nombre, datos in figuras.items():
        lineas.append(f"| [{nombre}](figuras/{nombre}.png) | {datos['seccion']} | {datos['titulo']} |")
    lineas += ["", "## Tablas de apoyo", ""]
    lineas += [f"- [`{nombre}.csv`](tablas/{nombre}.csv)" for nombre in tablas]
    lineas += [
        "",
        "## Cómo leer las figuras",
        "",
        "- P1 a P6 son las preguntas del MVP del documento de diseño (sección 6.1): P1 estado actual, P2 brechas, P3 evolución,",
        "  P4 operadores, P5 PQR y P6 peor desempeño combinado.",
        "- Un color fijo por departamento en todas las figuras: Cauca (azul), Nariño (naranja), Valle del Cauca (verde), Putumayo (amarillo).",
        "- Las PQR son de distribuidoras de **gas**: se usan como contexto municipal, no como quejas del servicio eléctrico.",
        f"- Las fuentes no llegan a hoy (prestación: {atraso} meses sin datos nuevos; operación diaria y PQR congeladas) y la cobertura de prestación es irregular",
        f"  ({cobertura['minimo']} a {cobertura['maximo']} de {alcance['localidades']} localidades por mes): por eso las comparaciones en el tiempo se hacen contra la propia localidad.",
        "",
    ]
    ruta.write_text("\n".join(lineas), encoding="utf-8")


def ejecutar_eda(
    ruta_gold: Path | str | None = None,
    ruta_salida: Path | str | None = None,
    ruta_operacion: Path | str | None = None,
    solo: list[str] | None = None,
) -> dict:
    """Genera figuras, tablas de apoyo, hallazgos e índice. Devuelve un resumen de lo escrito.

    Una figura que falle no impide generar las demás; al final, si alguna falló, se lanza ErrorEDA para que el
    orquestador la cuente como error controlado. Si no existe silver/operacion_diaria, solo se omite la figura 16.
    """
    salida = Path(ruta_salida) if ruta_salida else RUTA_SALIDA
    carpeta_figuras = salida / PARAMETROS["figuras_subcarpeta"]
    carpeta_tablas = salida / PARAMETROS["tablas_subcarpeta"]
    try:
        gold = an.cargar_gold(ruta_gold)
    except FileNotFoundError as error:
        raise ErrorEDA(str(error)) from error
    operacion = an.cargar_operacion_diaria(ruta_operacion)
    if operacion is None:
        LOGGER.warning("No se encontró silver/operacion_diaria.parquet: se omite la figura de operación diaria.")

    carpeta_figuras.mkdir(parents=True, exist_ok=True)
    carpeta_tablas.mkdir(parents=True, exist_ok=True)
    generadas: dict[str, dict] = {}
    fallidas: dict[str, str] = {}
    dpi = int(PARAMETROS["dpi"])
    for nombre, figura in charts.FIGURAS.items():
        if solo and not any(texto in nombre for texto in solo):
            continue
        if figura.requiere_operacion and operacion is None:
            continue
        try:
            with st.tema():
                fig = figura.funcion(gold, operacion) if figura.requiere_operacion else figura.funcion(gold)
            titulo = fig.metadatos_zni["titulo"]
            ruta = st.guardar(fig, carpeta_figuras / f"{nombre}.png", dpi=dpi)
            generadas[nombre] = {"ruta": str(ruta), "seccion": figura.seccion, "titulo": titulo}
            LOGGER.info("Figura %s: %s", nombre, titulo)
        except Exception as error:  # noqa: BLE001 - una figura que falla no tumba las demás
            fallidas[nombre] = f"{type(error).__name__}: {error}"
            LOGGER.error("La figura %s falló: %s", nombre, fallidas[nombre])

    tablas = an.tablas_de_apoyo(gold)
    for nombre, tabla in tablas.items():
        tabla.to_csv(carpeta_tablas / f"{nombre}.csv", index=False, encoding="utf-8-sig")
    hallazgos = _nativo(an.calcular_hallazgos(gold, operacion))
    ruta_hallazgos = salida / "hallazgos.json"
    ruta_hallazgos.write_text(json.dumps(hallazgos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not solo:
        _escribir_indice(salida / "INDICE.md", generadas, list(tablas), hallazgos)

    LOGGER.info("EDA: %d figuras, %d tablas, hallazgos en %s", len(generadas), len(tablas), ruta_hallazgos)
    if fallidas:
        raise ErrorEDA(f"figuras con error: {fallidas}")
    return {"figuras": generadas, "tablas": list(tablas), "hallazgos": str(ruta_hallazgos)}


def generar_figuras_diapositiva(
    ruta_gold: Path | str | None = None,
    ruta_salida: Path | str | None = None,
    ruta_operacion: Path | str | None = None,
) -> dict[str, dict]:
    """Genera en `docs/presentacion/figuras` las figuras de la presentación en modo diapositiva.

    Son las mismas figuras (mismos cálculos y colores) sin título ni pie, porque la diapositiva ya trae el suyo, y con
    el lienzo más angosto para que el texto se vea más grande. Devuelve, por figura, su ruta, el tamaño en píxeles y el
    título, subtítulo y pie del informe (la presentación los reutiliza). Lista en `eda.figuras_diapositiva` (config).
    """
    carpeta = (Path(ruta_salida) if ruta_salida else RUTA_PRESENTACION) / "figuras"
    try:
        gold = an.cargar_gold(ruta_gold)
    except FileNotFoundError as error:
        raise ErrorEDA(str(error)) from error
    operacion = an.cargar_operacion_diaria(ruta_operacion)
    carpeta.mkdir(parents=True, exist_ok=True)
    generadas: dict[str, dict] = {}
    for nombre in PARAMETROS["figuras_diapositiva"]:
        figura = charts.FIGURAS[nombre]
        if figura.requiere_operacion and operacion is None:
            LOGGER.warning("Se omite %s: falta silver/operacion_diaria.parquet.", nombre)
            continue
        with st.tema(), st.modo_diapositiva():
            fig = figura.funcion(gold, operacion) if figura.requiere_operacion else figura.funcion(gold)
        ruta = st.guardar(fig, carpeta / f"{nombre}.png", dpi=int(PARAMETROS["dpi"]))
        ancho_px, alto_px = (int(round(v * PARAMETROS["dpi"])) for v in fig.get_size_inches())
        generadas[nombre] = {"ruta": str(ruta), "ancho_px": ancho_px, "alto_px": alto_px, **fig.metadatos_zni}
    LOGGER.info("Figuras para la presentación: %d en %s", len(generadas), carpeta)
    return generadas


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Análisis exploratorio del modelo gold (figuras, tablas y hallazgos).")
    parser.add_argument("--figuras", nargs="*", help="Solo las figuras cuyo nombre contenga alguno de estos textos (p. ej. fig07 fig10).")
    parser.add_argument("--diapositivas", action="store_true", help="Genera las figuras de la presentación (modo diapositiva) en docs/presentacion/figuras.")
    args = parser.parse_args(argv)
    try:
        if args.diapositivas:
            generadas = generar_figuras_diapositiva()
            print(f"{len(generadas)} figuras para la presentación en {RUTA_PRESENTACION / 'figuras'}")
            return
        resumen = ejecutar_eda(solo=args.figuras)
    except ErrorEDA as error:
        registrar_error_controlado("eda", str(error))
        LOGGER.error("%s", error)
        raise SystemExit(1) from error
    print(f"{len(resumen['figuras'])} figuras y {len(resumen['tablas'])} tablas en {RUTA_SALIDA}")


if __name__ == "__main__":
    main()
