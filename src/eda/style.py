"""Tema visual compartido por las figuras del análisis exploratorio (Matplotlib).

Decisiones de diseño (una sola vez, para que las 16 figuras se lean como un sistema):

- Paleta categórica de referencia ya validada (separación para daltonismo y contraste): un color FIJO por
  departamento, en el orden del código DANE (19, 52, 76, 86). El color sigue a la entidad, nunca al ranking.
  Con cuatro series solo se usan formas "adyacentes" (barras, líneas, apiladas) con etiquetas directas; en
  gráficos de dispersión no se pintan los cuatro departamentos a la vez (el naranja y el amarillo se confunden).
- Un solo eje y por gráfico (nunca doble eje), marcas finas, rejilla de líneas continuas casi invisibles.
- Rampa secuencial de un solo tono (azul) para magnitudes continuas.
- El texto usa tintas neutras, nunca el color de la serie; el color lo lleva la marca que acompaña al texto.
- Números a la usanza colombiana: coma decimal y punto de miles.

Las figuras se crean con la API orientada a objetos (Figure), sin pyplot: no hay estado global ni hace falta
una ventana, así que el mismo código sirve en el pipeline, en las pruebas y en el notebook.
"""
from __future__ import annotations

import textwrap
from contextlib import contextmanager
from pathlib import Path

import matplotlib as mpl
import pandas as pd
from matplotlib import font_manager
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter

# ---------------------------------------------------------------------------
# Paleta (superficie clara)
# ---------------------------------------------------------------------------
SUPERFICIE = "#fcfcfb"
TINTA = "#0b0b0b"
TINTA_SECUNDARIA = "#52514e"
TINTA_APAGADA = "#898781"
REJILLA = "#e1e0d9"
LINEA_BASE = "#c3c2b7"
NEUTRO = "#f0efec"
GRIS_CONTEXTO = "#c3c2b7"

AZUL = "#2a78d6"
NARANJA = "#eb6834"
AQUA = "#1baf7a"
AMARILLO = "#eda100"
ROJO = "#e34948"

# Rampa secuencial azul, de claro a oscuro (pasos 100 a 700 de la paleta de referencia).
RAMPA_AZUL = [
    "#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5",
    "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b",
]
CMAP_SECUENCIAL = LinearSegmentedColormap.from_list("zni_azul", RAMPA_AZUL)
CMAP_DIVERGENTE = LinearSegmentedColormap.from_list("zni_azul_rojo", [ROJO, NEUTRO, "#256abf"])

# Estado (reservado: solo cuando el color SIGNIFICA bueno/malo, siempre con icono y texto).
ESTADO_ADVERTENCIA = "#fab219"
ESTADO_GRAVE = "#ec835a"
ESTADO_CRITICO = "#d03b3b"

# Departamentos: el orden por código DANE fija el color en todas las figuras.
ORDEN_DEPARTAMENTOS = ["19", "52", "76", "86"]
NOMBRE_DEPARTAMENTO = {"19": "Cauca", "52": "Nariño", "76": "Valle del Cauca", "86": "Putumayo"}
COLOR_DEPARTAMENTO = {"19": AZUL, "52": NARANJA, "76": AQUA, "86": AMARILLO}
NOMBRE_REGION = "Suroccidente (4 departamentos)"

MESES_ABREVIADOS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
MESES_COMPLETOS = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]

# ---------------------------------------------------------------------------
# Medidas de la composición (en pulgadas, independientes del alto de cada figura)
# ---------------------------------------------------------------------------
MARGEN_LATERAL_IN = 0.45
ALTO_PIE_IN = 0.42
TAMANO_TITULO = 17
TAMANO_SUBTITULO = 11.5
TAMANO_PIE = 8.8

def _fuente_disponible(preferidas=("Segoe UI", "Helvetica Neue", "Arial")) -> str:
    """Primera fuente de la lista que esté instalada (Matplotlib avisa por cada texto si se le pide una ausente)."""
    instaladas = {fuente.name for fuente in font_manager.fontManager.ttflist}
    return next((nombre for nombre in preferidas if nombre in instaladas), "DejaVu Sans")


RC_TEMA = {
    "figure.facecolor": SUPERFICIE,
    "axes.facecolor": SUPERFICIE,
    "savefig.facecolor": SUPERFICIE,
    "font.family": [_fuente_disponible()],
    "font.size": 11,
    "text.color": TINTA,
    "axes.edgecolor": LINEA_BASE,
    "axes.labelcolor": TINTA_SECUNDARIA,
    "axes.labelsize": 10.5,
    "axes.titlesize": 12,
    "axes.titleweight": "bold",
    "axes.titlelocation": "left",
    "axes.titlecolor": TINTA,
    "axes.titlepad": 10,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.spines.left": False,
    "axes.axisbelow": True,
    "axes.grid": False,
    "grid.color": REJILLA,
    "grid.linewidth": 0.8,
    "grid.linestyle": "-",
    "xtick.color": TINTA_APAGADA,
    "ytick.color": TINTA_APAGADA,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "xtick.major.size": 0,
    "ytick.major.size": 0,
    "xtick.major.pad": 6,
    "ytick.major.pad": 6,
    "legend.frameon": False,
    "legend.fontsize": 10,
    "lines.linewidth": 2.0,
    "lines.solid_capstyle": "round",
    "lines.solid_joinstyle": "round",
    "patch.linewidth": 0,
    "savefig.dpi": 150,
}


def tema():
    """Contexto de Matplotlib con el tema del proyecto (se usa con `with tema(): ...`)."""
    return mpl.rc_context(RC_TEMA)


# ---------------------------------------------------------------------------
# Formato de números y fechas (es-CO)
# ---------------------------------------------------------------------------
def num(valor, decimales: int = 0) -> str:
    """Formatea un número con coma decimal y punto de miles (1234.5 -> '1.234,5')."""
    if valor is None or pd.isna(valor):
        return "s. d."
    valor = float(valor)
    if round(valor, decimales) == 0:
        valor = 0.0  # evita '-0,0'
    texto = f"{valor:,.{decimales}f}".translate(str.maketrans({",": ".", ".": ","}))
    return texto.replace("-", "−")  # signo menos tipográfico


def horas(valor, decimales: int = 1) -> str:
    """'7,4 h' (horas de servicio por día)."""
    return f"{num(valor, decimales)} h"


def porcentaje(valor, decimales: int = 0) -> str:
    """'65 %' (con espacio, como en el resto del proyecto)."""
    return f"{num(valor, decimales)} %"


def mes_corto(fecha) -> str:
    """'ene-2026'."""
    fecha = pd.Timestamp(fecha)
    return f"{MESES_ABREVIADOS[fecha.month - 1]}-{fecha.year}"


def formateador_numero(decimales: int = 0) -> FuncFormatter:
    """Formateador de ticks con el formato es-CO."""
    return FuncFormatter(lambda valor, _pos: num(valor, decimales))


def formateador_horas() -> FuncFormatter:
    return FuncFormatter(lambda valor, _pos: f"{num(valor, 0)} h")


def formateador_porcentaje(escala: float = 1.0) -> FuncFormatter:
    return FuncFormatter(lambda valor, _pos: f"{num(valor * escala, 0)} %")


# ---------------------------------------------------------------------------
# Lienzo con encabezado (título = hallazgo) y pie (fuente y salvedades)
# ---------------------------------------------------------------------------
def _envolver(texto: str, ancho_in: float, tamano_pt: float, factor: float = 0.50) -> list[str]:
    """Parte un texto en líneas que quepan en `ancho_in` pulgadas (aprox. por ancho medio de carácter)."""
    caracteres = max(20, int(ancho_in * 72 / (tamano_pt * factor)))
    return textwrap.wrap(texto, width=caracteres) or [""]


_MODO = {"diapositiva": False}
ANCHO_DIAPOSITIVA_IN = 10.0
MARGEN_DIAPOSITIVA = 0.012


@contextmanager
def modo_diapositiva(activo: bool = True):
    """Dentro de este contexto las figuras salen sin título ni pie y con el lienzo más angosto.

    Una diapositiva ya trae su propio título y su fuente, y cada pulgada de alto que no ocupa un encabezado es
    alto para el gráfico; con el lienzo de 10 pulgadas (en vez de 12) el mismo texto se ve ~20 % más grande al
    ocupar el ancho de la diapositiva. El título, el subtítulo y el pie se conservan en `fig.metadatos_zni`.
    """
    anterior = _MODO["diapositiva"]
    _MODO["diapositiva"] = activo
    try:
        yield
    finally:
        _MODO["diapositiva"] = anterior


def es_modo_diapositiva() -> bool:
    return _MODO["diapositiva"]


def nuevo_lienzo(
    titulo: str,
    subtitulo: str | None = None,
    fuente: str | None = None,
    ancho: float = 12.0,
    alto: float = 6.75,
) -> Figure:
    """Crea la figura con encabezado y pie fuera del área de gráficos.

    El título dice el hallazgo (no el tema); el subtítulo dice qué se mide y en qué periodo; el pie cita la
    fuente y las salvedades que el lector necesita para no sobre-interpretar. Las medidas del encabezado y
    del pie están en pulgadas, así que no cambian con el alto de la figura. En modo diapositiva
    (`modo_diapositiva`) no se dibujan: solo queda el área de gráficos.
    """
    ancho_texto = ancho - 2 * MARGEN_LATERAL_IN
    lineas_titulo = _envolver(titulo, ancho_texto, TAMANO_TITULO, factor=0.56)
    lineas_subtitulo = _envolver(subtitulo, ancho_texto, TAMANO_SUBTITULO) if subtitulo else []
    lineas_pie = _envolver(fuente, ancho_texto, TAMANO_PIE, factor=0.48) if fuente else []

    alto_titulo = len(lineas_titulo) * 0.32
    alto_subtitulo = len(lineas_subtitulo) * 0.22
    alto_encabezado = 0.22 + alto_titulo + (0.06 + alto_subtitulo if lineas_subtitulo else 0) + 0.12
    alto_pie = max(ALTO_PIE_IN, 0.18 + len(lineas_pie) * 0.15)
    metadatos = {"titulo": titulo, "subtitulo": subtitulo or "", "pie": fuente or ""}

    if _MODO["diapositiva"]:
        alto_util = alto - alto_encabezado - alto_pie  # el área de gráficos que tendría la figura del informe
        fig = Figure(figsize=(ANCHO_DIAPOSITIVA_IN, alto_util * ANCHO_DIAPOSITIVA_IN / ancho + 0.2), facecolor=SUPERFICIE, layout="constrained")
        fig.get_layout_engine().set(
            rect=(MARGEN_DIAPOSITIVA, MARGEN_DIAPOSITIVA, 1 - 2 * MARGEN_DIAPOSITIVA, 1 - 2 * MARGEN_DIAPOSITIVA),
            w_pad=0.08, h_pad=0.08, wspace=0.04, hspace=0.05,
        )
        fig.metadatos_zni = metadatos
        return fig

    fig = Figure(figsize=(ancho, alto), facecolor=SUPERFICIE, layout="constrained")
    x_texto = MARGEN_LATERAL_IN / ancho
    y_titulo = 1 - 0.20 / alto
    fig.text(x_texto, y_titulo, "\n".join(lineas_titulo), ha="left", va="top", fontsize=TAMANO_TITULO, fontweight="bold", color=TINTA, linespacing=1.15)
    if lineas_subtitulo:
        y_subtitulo = 1 - (0.20 + alto_titulo + 0.06) / alto
        fig.text(x_texto, y_subtitulo, "\n".join(lineas_subtitulo), ha="left", va="top", fontsize=TAMANO_SUBTITULO, color=TINTA_SECUNDARIA, linespacing=1.25)
    if lineas_pie:
        fig.text(x_texto, 0.14 / alto, "\n".join(lineas_pie), ha="left", va="bottom", fontsize=TAMANO_PIE, color=TINTA_APAGADA, linespacing=1.3)

    izquierda = MARGEN_LATERAL_IN / ancho
    fig.get_layout_engine().set(
        rect=(izquierda, alto_pie / alto, 1 - 2 * izquierda, 1 - (alto_pie + alto_encabezado) / alto),
        w_pad=0.08,
        h_pad=0.08,
        wspace=0.04,
        hspace=0.05,
    )
    fig.metadatos_zni = metadatos
    return fig


def fijar_layout(fig: Figure, decimales: int = 4) -> None:
    """Resuelve el layout automático una vez, redondea la posición de los ejes y lo congela.

    El motor 'constrained' de Matplotlib recorre estructuras sin orden garantizado y puede dar posiciones que
    difieren en ~1e-12 entre corridas; al dibujar, ese ruido mueve una línea o un texto un píxel. Redondear las
    posiciones (a 1e-4 del lienzo, ~0,1 píxel) hace que la misma figura salga siempre idéntica, byte a byte.
    """
    fig.draw_without_rendering()
    fig.set_layout_engine("none")
    for eje in fig.axes:
        x, y, ancho, alto = eje.get_position().bounds
        eje.set_position([round(x, decimales), round(y, decimales), round(ancho, decimales), round(alto, decimales)])


def guardar(fig: Figure, ruta: Path, dpi: int = 150) -> Path:
    """Guarda la figura como PNG (crea la carpeta si hace falta) con el layout fijado para que sea reproducible."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fijar_layout(fig)
    fig.savefig(ruta, dpi=dpi, facecolor=SUPERFICIE)
    return ruta


# ---------------------------------------------------------------------------
# Piezas de ejes
# ---------------------------------------------------------------------------
def estilizar_eje(ax, rejilla: str | None = "y", base: bool = True) -> None:
    """Ejes recesivos: sin marco, rejilla de línea fina continua y línea base discreta."""
    ax.set_axisbelow(True)
    if rejilla:
        ax.grid(axis=rejilla, color=REJILLA, linewidth=0.8, linestyle="-")
    for lado in ("top", "right", "left"):
        ax.spines[lado].set_visible(False)
    ax.spines["bottom"].set_visible(base)
    ax.spines["bottom"].set_color(LINEA_BASE)
    ax.tick_params(length=0)


def clave_departamento(codigo: str) -> str:
    return NOMBRE_DEPARTAMENTO.get(str(codigo), str(codigo))


def leyenda_departamentos(ax, codigos=None, ncols: int = 4, extras=(), **kwargs):
    """Leyenda de colores de departamento, en una fila sobre el gráfico (marca de color + texto neutro).

    `extras` son manijas adicionales (por ejemplo, el punto de 'participación acumulada').
    """
    codigos = list(codigos) if codigos is not None else ORDEN_DEPARTAMENTOS
    manijas = [
        Line2D([0], [0], marker="o", linestyle="", markersize=8, markerfacecolor=COLOR_DEPARTAMENTO[c], markeredgecolor=SUPERFICIE, markeredgewidth=1.5, label=NOMBRE_DEPARTAMENTO[c])
        for c in codigos
    ] + list(extras)
    parametros = dict(handles=manijas, ncols=ncols, loc="lower left", bbox_to_anchor=(0.0, 1.0), handletextpad=0.2, columnspacing=1.6, labelcolor=TINTA_SECUNDARIA)
    parametros.update(kwargs)
    return ax.legend(**parametros)


def etiqueta_valor(ax, x, y, texto: str, ha: str = "left", va: str = "center", color: str = TINTA_SECUNDARIA, tamano: float = 9.5, peso: str = "normal", **kwargs):
    """Etiqueta de valor en el extremo de una marca (siempre en tinta de texto, nunca en el color de la serie)."""
    return ax.text(x, y, texto, ha=ha, va=va, color=color, fontsize=tamano, fontweight=peso, **kwargs)


def anotar(ax, texto: str, xy, xytext, ha: str = "left", va: str = "center", color: str = TINTA_SECUNDARIA, tamano: float = 9.5, conector: bool = True):
    """Anotación con línea guía fina (para no apilar etiquetas separadas de su marca)."""
    flecha = dict(arrowstyle="-", color=LINEA_BASE, linewidth=0.9, shrinkA=2, shrinkB=3) if conector else None
    return ax.annotate(texto, xy=xy, xytext=xytext, ha=ha, va=va, color=color, fontsize=tamano, arrowprops=flecha)


def etiquetas_unicas(df: pd.DataFrame, columna_texto: str, columna_codigo: str) -> list[str]:
    """Etiquetas para mostrar; si dos filas comparten texto se les agrega su código para distinguirlas."""
    texto = df[columna_texto].astype(str)
    repetido = texto.duplicated(keep=False)
    return [f"{t} ({c})" if r else t for t, c, r in zip(texto, df[columna_codigo].astype(str), repetido)]


def sin_datos(ax, mensaje: str = "Sin datos para esta figura") -> None:
    """Deja un mensaje en un eje vacío (una figura nunca debe fallar por falta de datos)."""
    ax.set_axis_off()
    ax.text(0.5, 0.5, mensaje, ha="center", va="center", color=TINTA_APAGADA, fontsize=12, transform=ax.transAxes)
