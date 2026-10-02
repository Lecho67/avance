"""Figuras del análisis exploratorio (Matplotlib). Una función por figura; todas reciben las tablas gold.

Cada figura sigue la misma receta: el TÍTULO dice el hallazgo (con cifras calculadas de los datos, nunca
escritas a mano), el subtítulo dice qué se mide y en qué periodo, y el pie cita la fuente y las salvedades.
Los colores de departamento son fijos (ver style.py); en gráficos de dispersión no se pintan los cuatro
departamentos a la vez.

Las figuras se registran en FIGURAS (nombre de archivo -> FiguraEDA) y se generan con `python main.py --etapa eda`.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable, NamedTuple

import matplotlib.dates as mdates
import numpy as np
import pandas as pd
from matplotlib.colors import to_rgba
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
from matplotlib.ticker import MultipleLocator

_RAIZ_PROYECTO = Path(__file__).resolve().parent.parent.parent
if str(_RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_PROYECTO))

from src.eda import analysis as an  # noqa: E402
from src.eda import style as st  # noqa: E402

HORAS_DIA = an.HORAS_DIA
TABLAS = dict[str, pd.DataFrame]


def _nombre_dep(codigo) -> str:
    return st.NOMBRE_DEPARTAMENTO.get(str(codigo), str(codigo))


def _color_dep(codigo) -> str:
    return st.COLOR_DEPARTAMENTO.get(str(codigo), st.GRIS_CONTEXTO)


_titulo_localidad = an.titulo_nombre


def _etiquetas_localidades(df: pd.DataFrame) -> list[str]:
    """'Localidad  ·  Municipio' para cada fila; si dos localidades se llaman igual, se agrega su código DANE."""
    base = pd.DataFrame(
        {
            "texto": [f"{_titulo_localidad(n)}  ·  {_titulo_localidad(m)}" for n, m in zip(df["nombre_localidad"], df["nombre_municipio"])],
            "codigo": df["clave_localidad"].astype(str).str.split("-").str[0],
        }
    )
    return st.etiquetas_unicas(base, "texto", "codigo")


def _meses_entre(desde: pd.Timestamp, hasta: pd.Timestamp) -> int:
    return (hasta.year - desde.year) * 12 + (hasta.month - desde.month)


# ---------------------------------------------------------------------------
# 01. Frescura y cobertura de las fuentes
# ---------------------------------------------------------------------------
def fig_frescura_fuentes(g: TABLAS) -> Figure:
    meta = g["meta_fuentes"].copy()
    orden = {"prestacion": 0, "operacion_diaria": 1, "pqr": 2}
    meta = meta.sort_values("fuente", key=lambda s: s.map(orden)).reset_index(drop=True)
    etiquetas = {
        "prestacion": ("Prestación del servicio", "MinEnergía / IPSE · mensual"),
        "operacion_diaria": ("Operación diaria", "Superservicios · semestral"),
        "pqr": ("Quejas y reclamos (PQR)", "Superservicios · semestral"),
    }
    referencia = pd.Timestamp(meta["fecha_referencia"].iloc[0])
    retraso = {
        fila.fuente: _meses_entre(pd.Timestamp(fila.ultimo_periodo_datos), referencia)
        for fila in meta.itertuples()
    }
    congeladas = meta[meta["actualizacion_nominal"] == "congelada"]
    titulo = (
        f"Ninguna fuente llega a hoy: la principal va {retraso['prestacion']} meses atrasada "
        f"y las otras dos están congeladas desde hace {min(retraso[f] for f in congeladas['fuente'])} meses o más"
    )
    fecha_referencia = f"{referencia.day} de {st.MESES_COMPLETOS[referencia.month - 1]} de {referencia.year}"
    subtitulo = f"Periodo con datos de cada fuente frente a la fecha de referencia del pipeline ({fecha_referencia}), en los 4 departamentos."
    pie = (
        "Fuente: gold.meta_fuentes (datos.gov.co: 3ebi-d83g, qwe5-ycap, 5wua-nr2d). La cobertura observada es menor que la fecha de "
        "actualización del portal: operacion_diaria figura actualizada en jun-2023 pero sus datos terminan en mar-2022."
    )
    fig = st.nuevo_lienzo(titulo, subtitulo, pie, ancho=12, alto=5.0)
    ax_nombres, ax, ax_estado = fig.subplots(1, 3, width_ratios=[2.7, 7.4, 2.9], sharey=True)
    for lateral in (ax_nombres, ax_estado):
        lateral.set_axis_off()
    transformada_nombres, transformada_estado = ax_nombres.get_yaxis_transform(), ax_estado.get_yaxis_transform()

    num = mdates.date2num
    for fila in meta.itertuples():
        y = len(meta) - 1 - orden[fila.fuente]
        primero = pd.Timestamp(fila.primer_periodo_datos)
        ultimo_mes = pd.Timestamp(fila.ultimo_periodo_datos)
        fin_cobertura = ultimo_mes + pd.DateOffset(months=1)
        ax.barh(y, num(fin_cobertura) - num(primero), left=num(primero), height=0.42, color=st.AZUL, edgecolor=st.SUPERFICIE, linewidth=1)
        ax.barh(y, num(referencia) - num(fin_cobertura), left=num(fin_cobertura), height=0.42, color=st.REJILLA, edgecolor=st.SUPERFICIE, linewidth=1)

        rango = f"{st.mes_corto(primero)} a {st.mes_corto(ultimo_mes)}"
        if num(fin_cobertura) - num(primero) > 1000:
            ax.text(num(primero) + 40, y, rango, va="center", ha="left", fontsize=10, color=st.SUPERFICIE, fontweight="bold")
        else:
            ax.text(num(primero), y + 0.30, rango, va="bottom", ha="left", fontsize=10, color=st.TINTA_SECUNDARIA)
        sin_datos = f"{retraso[fila.fuente]} meses sin datos nuevos"
        if num(referencia) - num(fin_cobertura) > 900:
            ax.text(num(fin_cobertura) + 40, y, sin_datos, va="center", ha="left", fontsize=10, color=st.TINTA_SECUNDARIA)
        else:
            ax.text(num(fin_cobertura) - 40, y + 0.30, sin_datos, va="bottom", ha="right", fontsize=10, color=st.TINTA_SECUNDARIA)

        nombre, detalle = etiquetas[fila.fuente]
        ax_nombres.text(1.0, y + 0.10, nombre, ha="right", va="center", fontsize=11.5, fontweight="bold", color=st.TINTA, transform=transformada_nombres)
        ax_nombres.text(1.0, y - 0.08, detalle, ha="right", va="top", fontsize=9.5, color=st.TINTA_SECUNDARIA, transform=transformada_nombres)

        # Estado: icono + texto (el color nunca va solo)
        activa = fila.actualizacion_nominal == "activa"
        marcador, color_estado = ("^", st.ESTADO_ADVERTENCIA) if activa else ("s", st.ESTADO_GRAVE)
        etiqueta_estado = {"vigente": "Vigente", "desactualizada": "Desactualizada", "congelada": "Congelada"}.get(fila.estado_frescura, fila.estado_frescura)
        ax_estado.plot([0.05], [y + 0.10], marker=marcador, markersize=9, color=color_estado, transform=transformada_estado, clip_on=False, linestyle="")
        ax_estado.text(0.13, y + 0.10, etiqueta_estado, ha="left", va="center", fontsize=11.5, fontweight="bold", color=st.TINTA, transform=transformada_estado)
        ax_estado.text(0.13, y - 0.08, f"corte de la fuente: {st.mes_corto(fila.fecha_corte_fuente)}", ha="left", va="top", fontsize=9.5, color=st.TINTA_SECUNDARIA, transform=transformada_estado)

    ax.axvline(num(referencia), color=st.TINTA, linewidth=1.2)
    ax.text(num(referencia) - 25, len(meta) - 0.42, f"Referencia: {referencia.day} {st.MESES_ABREVIADOS[referencia.month - 1]} {referencia.year}", ha="right", va="bottom", fontsize=9.5, color=st.TINTA, fontweight="bold")
    ax.set_xlim(num(pd.Timestamp("2019-10-01")), num(referencia + pd.DateOffset(months=3)))
    ax.set_ylim(-0.6, len(meta) - 0.1)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    st.estilizar_eje(ax, rejilla="x")
    ax.set_yticks([])
    return fig


# ---------------------------------------------------------------------------
# 02. Cobertura mensual: cuántas localidades reportan
# ---------------------------------------------------------------------------
def fig_cobertura_mensual(g: TABLAS) -> Figure:
    fact = g["fact_prestacion"]
    cobertura = an.cobertura_mensual(fact)
    total = cobertura.sum(axis=1)
    total_localidades = fact["clave_localidad"].nunique()
    mes_min, mes_max = total.idxmin(), total.idxmax()
    titulo = f"Cada mes reportan entre {int(total.min())} y {int(total.max())} de las {total_localidades} localidades: la serie es incompleta"
    subtitulo = f"Localidades con registro de prestación en cada mes, por departamento ({st.mes_corto(cobertura.index.min())} a {st.mes_corto(cobertura.index.max())})."
    pie = (
        "Fuente: gold.fact_prestacion. Una localidad cuenta como reportada si tiene registro ese mes. La cobertura cambia de un mes a otro "
        f"(p. ej., {st.mes_corto(mes_min)}: {int(total.min())}; {st.mes_corto(mes_max)}: {int(total.max())}), "
        "así que un promedio mensual no siempre compara las mismas localidades."
    )
    fig = st.nuevo_lienzo(titulo, subtitulo, pie, ancho=12, alto=5.8)
    ax = fig.subplots()
    num = mdates.date2num
    fondo = np.zeros(len(cobertura))
    for codigo in st.ORDEN_DEPARTAMENTOS:
        if codigo not in cobertura.columns:
            continue
        valores = cobertura[codigo].to_numpy()
        ax.bar(num(cobertura.index), valores, bottom=fondo, width=24, color=_color_dep(codigo), edgecolor=st.SUPERFICIE, linewidth=0.9, label=_nombre_dep(codigo))
        fondo += valores
    st.leyenda_departamentos(ax, [c for c in st.ORDEN_DEPARTAMENTOS if c in cobertura.columns])
    for mes, etiqueta in ((mes_min, "mínimo"), (mes_max, "máximo")):
        vecinos = total[(total.index >= mes - pd.DateOffset(months=4)) & (total.index <= mes + pd.DateOffset(months=4))]
        st.anotar(
            ax, f"{etiqueta}: {int(total[mes])}", xy=(num(mes), total[mes]), xytext=(num(mes), vecinos.max() + 6),
            ha="center", va="bottom", conector=True,
        )
    ax.set_ylim(0, total.max() * 1.28)
    ax.xaxis_date()
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.set_ylabel("Localidades que reportan")
    st.estilizar_eje(ax, rejilla="y")
    return fig


# ---------------------------------------------------------------------------
# 03. Mapa de reporte: localidad x mes
# ---------------------------------------------------------------------------
def fig_mapa_reporte_localidades(g: TABLAS) -> Figure:
    matriz, orden = an.matriz_reporte(g["fact_prestacion"], g["dim_localidad"])
    n_meses_total = matriz.shape[1]
    umbral_continuo = int(np.ceil(0.8 * n_meses_total))
    casi_todos = int((orden["meses"] >= umbral_continuo).sum())
    pocos = int((orden["meses"] <= 12).sum())
    titulo = f"Solo {casi_todos} localidades reportan casi todos los meses; {pocos} reportan 12 meses o menos"
    subtitulo = (
        f"Horas de servicio por día de cada localidad ({len(orden)}) en cada mes ({st.mes_corto(matriz.columns.min())} a {st.mes_corto(matriz.columns.max())}). "
        "Celda vacía: la localidad no reportó ese mes."
    )
    pie = (
        f"Fuente: gold.fact_prestacion. 'Casi todos los meses' = al menos el 80 % de los {n_meses_total} ({umbral_continuo} meses). Filas agrupadas por departamento y ordenadas "
        "por continuidad del reporte (más meses arriba). La escala satura en 12 h; Puerto Leguízamo (~24 h) y Puerto Merizalde (desde 2022) son de las filas más oscuras."
    )
    fig = st.nuevo_lienzo(titulo, subtitulo, pie, ancho=12, alto=9.6)
    ax = fig.subplots()
    cmap = st.CMAP_SECUENCIAL.with_extremes(bad=st.NEUTRO)
    imagen = ax.imshow(np.ma.masked_invalid(matriz.to_numpy(float)), cmap=cmap, vmin=0, vmax=12, aspect="auto", interpolation="nearest")
    # Bloques por departamento: banda de color a la izquierda, nombre y número de localidades
    inicio = 0
    for codigo in st.ORDEN_DEPARTAMENTOS:
        n = int((orden["id_departamento"] == codigo).sum())
        if n == 0:
            continue
        ax.add_patch(Rectangle((-3.2, inicio - 0.5), 1.4, n, facecolor=_color_dep(codigo), edgecolor="none", clip_on=False, transform=ax.transData))
        ax.text(-3.8, inicio + n / 2 - 0.5, f"{_nombre_dep(codigo)}\n{n} localidades", ha="right", va="center", fontsize=10.5, color=st.TINTA, linespacing=1.3)
        if inicio > 0:
            ax.axhline(inicio - 0.5, color=st.SUPERFICIE, linewidth=3)
        inicio += n
    meses = list(matriz.columns)
    posiciones = [i for i, mes in enumerate(meses) if mes.month == 1]
    ax.set_xticks(posiciones)
    ax.set_xticklabels([str(meses[i].year) for i in posiciones])
    ax.set_yticks([])
    ax.set_xlim(-0.5, n_meses_total - 0.5)
    for lado in ("top", "right", "left", "bottom"):
        ax.spines[lado].set_visible(False)
    ax.tick_params(length=0)
    barra = fig.colorbar(imagen, ax=ax, orientation="horizontal", location="bottom", shrink=0.34, aspect=34, pad=0.025, extend="max", ticks=[0, 3, 6, 9, 12])
    barra.set_label("Horas de servicio por día")
    barra.outline.set_visible(False)
    barra.ax.tick_params(length=0, labelsize=9.5)
    barra.ax.set_xticklabels(["0", "3", "6", "9", "12 o más"])
    return fig


# ---------------------------------------------------------------------------
# 04. Distribución de las horas de servicio
# ---------------------------------------------------------------------------
def fig_distribucion_horas(g: TABLAS) -> Figure:
    datos = an.horas_observadas(g["fact_prestacion"])
    horas = datos["horas"]
    q1, mediana, q3 = horas.quantile([0.25, 0.5, 0.75])
    casi_continuo = float((horas >= 23).mean() * 100)
    sin_servicio = int((horas <= 0).sum())
    titulo = (
        f"La mitad de las observaciones recibe entre {st.num(q1, 1)} y {st.num(q3, 1)} horas de energía al día; "
        f"solo el {st.num(casi_continuo, 0)} % tiene servicio casi continuo"
    )
    subtitulo = f"Horas de servicio por día de {st.num(len(horas))} observaciones localidad-mes ({st.mes_corto(datos['periodo'].min())} a {st.mes_corto(datos['periodo'].max())}); abajo, por departamento."
    pie = (
        f"Fuente: gold.fact_prestacion. 'Casi continuo' = 23 horas o más. {sin_servicio} observaciones tienen 0 horas (sin energía en el mes). "
        "Caja: mitad central de las observaciones del departamento; línea oscura: mediana; puntos: cada observación."
    )
    fig = st.nuevo_lienzo(titulo, subtitulo, pie, ancho=12, alto=6.9)
    ax_hist, ax_caja = fig.subplots(2, 1, sharex=True, height_ratios=[2.3, 1.6])

    contenedores = np.arange(0, 24.01, 1.0)  # el último intervalo es cerrado: incluye las observaciones de exactamente 24 h
    cuentas, bordes = np.histogram(horas, bins=contenedores)
    ax_hist.bar(bordes[:-1] + 0.5, cuentas, width=1.0, color=st.AZUL, edgecolor=st.SUPERFICIE, linewidth=1.2)
    ax_hist.axvspan(q1, q3, color=st.AZUL, alpha=0.10, linewidth=0)
    ax_hist.axvline(mediana, color=st.TINTA, linewidth=1.6)
    ax_hist.text(mediana + 0.25, cuentas.max() * 0.97, f"mediana {st.horas(mediana)}", ha="left", va="top", fontsize=10.5, color=st.TINTA, fontweight="bold")
    ax_hist.text(q3 + 0.25, cuentas.max() * 0.80, f"mitad central: {st.num(q1, 1)} a {st.num(q3, 1)} h", ha="left", va="top", fontsize=10, color=st.TINTA_SECUNDARIA)
    cola = int(((horas >= 23)).sum())
    st.anotar(ax_hist, f"{cola} observaciones\ncon 23 h o más", xy=(23.5, cuentas[-1] + 4), xytext=(20.2, cuentas.max() * 0.42), ha="center", va="bottom")
    ax_hist.set_ylabel("Observaciones")
    ax_hist.yaxis.set_major_formatter(st.formateador_numero())
    st.estilizar_eje(ax_hist, rejilla="y")

    generador = np.random.default_rng(an.PARAMETROS["semilla"])
    codigos = [c for c in st.ORDEN_DEPARTAMENTOS if c in set(datos["id_departamento"])]
    for fila, codigo in enumerate(reversed(codigos)):
        h = datos.loc[datos["id_departamento"] == codigo, "horas"].to_numpy(float)
        color = _color_dep(codigo)
        ax_caja.scatter(h, fila + generador.uniform(-0.17, 0.17, len(h)), s=9, color=color, alpha=0.30, linewidths=0)
        p25, p50, p75 = np.percentile(h, [25, 50, 75])
        ax_caja.add_patch(Rectangle((p25, fila - 0.2), p75 - p25, 0.4, facecolor=to_rgba(color, 0.30), edgecolor=color, linewidth=1.6))
        ax_caja.plot([p50, p50], [fila - 0.2, fila + 0.2], color=st.TINTA, linewidth=2.2, solid_capstyle="butt")
        ax_caja.text(24.4, fila, f"mediana {st.num(p50, 1)} h", ha="left", va="center", fontsize=9.5, color=st.TINTA_SECUNDARIA)
    ax_caja.set_yticks(range(len(codigos)))
    ax_caja.set_yticklabels([_nombre_dep(c) for c in reversed(codigos)], fontsize=10.5, color=st.TINTA)
    ax_caja.set_ylim(-0.6, len(codigos) - 0.4)
    ax_caja.set_xlim(0, 24)
    ax_caja.set_xticks(range(0, 25, 3))
    ax_caja.xaxis.set_major_formatter(st.formateador_horas())
    ax_caja.set_xlabel("Horas de servicio por día")
    st.estilizar_eje(ax_caja, rejilla="x")
    return fig


# ---------------------------------------------------------------------------
# 05. Concentración de la energía
# ---------------------------------------------------------------------------
def fig_concentracion_energia(g: TABLAS) -> Figure:
    conc = an.concentracion_energia(g["fact_prestacion"], g["dim_localidad"])
    n80 = an.localidades_para_participacion(conc, 0.8)
    primera = conc.iloc[0]
    top = conc.head(10).reset_index(drop=True)
    palabras = {1: "Una", 2: "Dos", 3: "Tres", 4: "Cuatro", 5: "Cinco", 6: "Seis", 7: "Siete", 8: "Ocho", 9: "Nueve", 10: "Diez"}
    titulo = (
        f"{palabras.get(n80, str(n80))} localidades concentran el 80 % de la energía; "
        f"{_titulo_localidad(primera['nombre_localidad'])} sola, el {st.num(primera['participacion'] * 100, 0)} %"
    )
    subtitulo = f"Participación de cada localidad en la energía activa acumulada ({len(conc)} localidades), las 10 con mayor participación."
    pie = (
        "Fuente: gold.fact_prestacion. Suma de energía activa en los meses reportados: una localidad que reporta menos meses acumula menos. "
        "Los puntos son la participación acumulada de la fila y las anteriores."
    )
    fig = st.nuevo_lienzo(titulo, subtitulo, pie, ancho=12, alto=6.2)
    ax = fig.subplots()
    y = np.arange(len(top))[::-1]
    for fila, yy in zip(top.itertuples(), y):
        ax.barh(yy, fila.participacion * 100, height=0.5, color=_color_dep(fila.id_departamento), edgecolor=st.SUPERFICIE, linewidth=1)
        ax.plot([fila.participacion_acumulada * 100], [yy], marker="o", markersize=7, color=st.TINTA, markeredgecolor=st.SUPERFICIE, markeredgewidth=1.5, linestyle="")
        porcentaje = fila.participacion * 100
        if porcentaje > 12:  # barra larga: la etiqueta va dentro (tinta oscura sobre el color), para no chocar con el punto
            ax.text(porcentaje - 1.2, yy, st.porcentaje(porcentaje, 1), ha="right", va="center", fontsize=10.5, fontweight="bold", color=st.TINTA)
        else:
            ax.text(porcentaje + 1.2, yy, st.porcentaje(porcentaje, 1), ha="left", va="center", fontsize=10, color=st.TINTA_SECUNDARIA)
    ax.axvline(80, color=st.TINTA, linewidth=1.1)
    ax.text(80.8, len(top) - 0.35, "80 % de la energía", ha="left", va="bottom", fontsize=10, color=st.TINTA, fontweight="bold")
    ax.set_yticks(y)
    ax.set_yticklabels(_etiquetas_localidades(top), fontsize=10, color=st.TINTA)
    ax.set_xlim(0, 100)
    ax.set_ylim(-0.7, len(top) - 0.1)
    ax.xaxis.set_major_formatter(st.formateador_porcentaje())
    ax.set_xlabel("Participación en la energía activa acumulada")
    st.estilizar_eje(ax, rejilla="x")
    punto = Line2D([0], [0], marker="o", linestyle="", markersize=7, markerfacecolor=st.TINTA, markeredgecolor=st.SUPERFICIE, label="participación acumulada")
    st.leyenda_departamentos(ax, [c for c in st.ORDEN_DEPARTAMENTOS if c in set(top["id_departamento"])], ncols=5, extras=[punto])
    return fig


# ---------------------------------------------------------------------------
# 06. Correlaciones y relación horas-energía
# ---------------------------------------------------------------------------
def fig_correlaciones(g: TABLAS) -> Figure:
    fact = g["fact_prestacion"]
    corr = an.correlaciones_spearman(fact)
    rho_energia = corr.loc["Horas de servicio", "Energía activa"]
    rho_potencia = corr.loc["Horas de servicio", "Potencia máxima"]
    titulo = f"A más energía, más horas de servicio (ρ = {st.num(rho_energia, 2)}); la potencia máxima casi no las explica (ρ = {st.num(rho_potencia, 2)})"
    subtitulo = "Correlación de Spearman entre las variables de prestación (izquierda) y horas frente a energía activa de cada localidad-mes (derecha)."
    pie = (
        "Fuente: gold.fact_prestacion. Spearman compara posiciones (robusto a valores extremos). La relación no prueba causa: más horas también "
        "significan más energía consumida. En escala logarítmica no se grafican las observaciones sin energía (sin servicio); la potencia de dic-2025 y ene-2026 se excluye por el cambio de formato de la fuente."
    )
    fig = st.nuevo_lienzo(titulo, subtitulo, pie, ancho=12, alto=5.9)
    ax_corr, ax_dis = fig.subplots(1, 2, width_ratios=[1.0, 1.25])

    nombres = list(corr.columns)
    valores = corr.to_numpy(float)
    imagen = ax_corr.imshow(valores, cmap=st.CMAP_DIVERGENTE, vmin=-1, vmax=1)
    for i in range(len(nombres)):
        for j in range(len(nombres)):
            oscuro = abs(valores[i, j]) > 0.62
            ax_corr.text(j, i, st.num(valores[i, j], 2), ha="center", va="center", fontsize=11, fontweight="bold" if i == j else "normal", color=st.SUPERFICIE if oscuro else st.TINTA)
    ax_corr.set_xticks(range(len(nombres)))
    ax_corr.set_xticklabels([n.replace(" ", "\n", 1) for n in nombres], fontsize=9.5, color=st.TINTA_SECUNDARIA)
    ax_corr.set_yticks(range(len(nombres)))
    ax_corr.set_yticklabels(nombres, fontsize=9.5, color=st.TINTA_SECUNDARIA)
    ax_corr.xaxis.tick_top()
    for lado in ax_corr.spines.values():
        lado.set_visible(False)
    ax_corr.tick_params(length=0)
    for k in range(len(nombres) + 1):
        ax_corr.axhline(k - 0.5, color=st.SUPERFICIE, linewidth=2)
        ax_corr.axvline(k - 0.5, color=st.SUPERFICIE, linewidth=2)
    barra = fig.colorbar(imagen, ax=ax_corr, orientation="horizontal", location="bottom", shrink=0.8, aspect=24, pad=0.04, ticks=[-1, -0.5, 0, 0.5, 1])
    barra.outline.set_visible(False)
    barra.ax.tick_params(length=0, labelsize=9)
    barra.ax.xaxis.set_major_formatter(st.formateador_numero(1))
    barra.set_label("ρ de Spearman (−1 a 1)")

    datos = an.horas_observadas(fact)
    con_energia = datos[datos["energia"] > 0]
    x = np.log10(con_energia["energia"].to_numpy(float))
    y = con_energia["horas"].to_numpy(float)
    ax_dis.scatter(x, y, s=12, color=st.AZUL, alpha=0.28, linewidths=0)
    # mediana de horas por tramos de energía (línea de tendencia sin supuestos)
    tramos = np.linspace(x.min(), x.max(), 9)
    centros, medianas = [], []
    for inferior, superior in zip(tramos[:-1], tramos[1:]):
        mascara = (x >= inferior) & (x <= superior)
        if mascara.sum() >= 15:
            centros.append(x[mascara].mean())
            medianas.append(np.median(y[mascara]))
    ax_dis.plot(centros, medianas, color=st.TINTA, linewidth=2.0, marker="o", markersize=5, markeredgecolor=st.SUPERFICIE, markeredgewidth=1.2)
    st.anotar(ax_dis, "mediana por tramo de energía", xy=(centros[len(centros) // 2], medianas[len(medianas) // 2]), xytext=(centros[len(centros) // 2] - 0.6, medianas[len(medianas) // 2] + 6.5), ha="center", va="bottom")
    cumbre = con_energia.loc[con_energia["horas"] > 20]
    if len(cumbre):
        st.anotar(ax_dis, "Puerto Leguízamo y Puerto\nMerizalde (desde 2022)", xy=(np.log10(cumbre["energia"].median()), 22), xytext=(np.log10(cumbre["energia"].median()) - 1.0, 21.2), ha="right", va="center")
    ax_dis.set_xlabel("Energía activa del mes (escala logarítmica)")
    ax_dis.set_ylabel("Horas de servicio por día")
    ax_dis.set_ylim(0, 25)
    ax_dis.set_yticks(range(0, 25, 6))
    ax_dis.xaxis.set_major_formatter(st.FuncFormatter(lambda v, _p: st.num(10 ** v, 0)))
    st.estilizar_eje(ax_dis, rejilla="y")
    return fig


# ---------------------------------------------------------------------------
# 07. Estado reciente por departamento (medidores)
# ---------------------------------------------------------------------------
def fig_estado_departamentos(g: TABLAS) -> Figure:
    fact = g["fact_prestacion"]
    estado = an.estado_reciente(fact)
    regional = estado[estado["codigo"] == "REGION"].iloc[0]
    deptos = estado[estado["codigo"] != "REGION"].set_index("codigo")
    ultimo = an.ultimo_mes_con_datos(fact)
    datos = an.horas_observadas(fact)
    ventana = datos[datos["periodo"] >= regional["desde"]]
    rango = ventana.groupby(["id_departamento", "clave_localidad"])["horas"].mean().groupby("id_departamento").agg(["min", "max", "size"])
    techo = int(np.ceil(max(deptos.loc[c, "horas"] for c in ("19", "52") if c in deptos.index)))
    titulo = f"En el último año con datos la región recibió {st.num(regional['horas'], 1)} de 24 horas de energía al día; Cauca y Nariño, menos de {techo}"
    subtitulo = (
        f"Horas de servicio por día, promedio de {st.mes_corto(regional['desde'])} a {st.mes_corto(regional['hasta'])}. "
        f"En {st.mes_corto(ultimo['periodo'])} reportaron {ultimo['localidades_reportadas']} localidades y {ultimo['localidades_con_servicio']} tuvieron energía."
    )
    pie = (
        "Fuente: gold.fact_prestacion. Promedio de las observaciones localidad-mes de la ventana; el color más claro es lo que falta hasta 24 horas (la brecha). "
        "El promedio de un departamento depende de qué localidades reporten: en Putumayo mezcla una localidad con ~24 h y otra con ~6 h."
    )
    fig = st.nuevo_lienzo(titulo, subtitulo, pie, ancho=12, alto=5.2)
    ax = fig.subplots()
    filas = [c for c in st.ORDEN_DEPARTAMENTOS if c in deptos.index] + ["REGION"]
    n = len(filas)
    for posicion, codigo in enumerate(filas):
        y = n - 1 - posicion + (-0.25 if codigo == "REGION" else 0)
        fila = regional if codigo == "REGION" else deptos.loc[codigo]
        color = st.TINTA_SECUNDARIA if codigo == "REGION" else _color_dep(codigo)
        pista = st.REJILLA if codigo == "REGION" else to_rgba(color, 0.20)
        ax.barh(y, HORAS_DIA, height=0.46, color=pista, edgecolor="none")
        ax.barh(y, fila["horas"], height=0.46, color=color, edgecolor=st.SUPERFICIE, linewidth=1)
        ax.text(fila["horas"] + 0.35, y, st.horas(fila["horas"]), ha="left", va="center", fontsize=12, fontweight="bold", color=st.TINTA)
        nombre = st.NOMBRE_REGION if codigo == "REGION" else _nombre_dep(codigo)
        if codigo == "REGION":
            detalle = f"{int(fila['localidades'])} localidades"
        else:
            r = rango.loc[codigo]
            detalle = f"{int(r['size'])} localidades, de {st.num(r['min'], 1)} a {st.num(r['max'], 1)} h"
        ax.text(-0.4, y + 0.04, nombre, ha="right", va="bottom", fontsize=11.5, fontweight="bold", color=st.TINTA)
        ax.text(-0.4, y - 0.06, detalle, ha="right", va="top", fontsize=9.5, color=st.TINTA_SECUNDARIA)
        ax.text(HORAS_DIA - 0.3, y, f"brecha {st.horas(fila['brecha'])}", ha="right", va="center", fontsize=10, color=st.TINTA_SECUNDARIA)
    ax.set_xlim(0, HORAS_DIA)
    ax.set_ylim(-0.95, n - 0.35)
    ax.set_yticks([])
    ax.set_xticks(range(0, 25, 6))
    ax.xaxis.set_major_formatter(st.formateador_horas())
    ax.set_xlabel("Horas de servicio por día (el total de la pista son 24 h)")
    st.estilizar_eje(ax, rejilla="x")
    ax.axhline(0.55, color=st.REJILLA, linewidth=0.9)
    return fig


# ---------------------------------------------------------------------------
# 08. Brechas por municipio
# ---------------------------------------------------------------------------
def fig_brechas_municipios(g: TABLAS) -> Figure:
    ranking = an.ranking_municipios_brecha(g["fact_prestacion"], g["dim_municipio"])
    primero = ranking.iloc[0]
    diez = ranking.head(10)
    solo_narino_cauca = bool(diez["id_departamento"].isin(["19", "52"]).all())
    cola = (
        f"los {len(diez)} municipios con más brecha son de Nariño o Cauca"
        if solo_narino_cauca
        else f"el {_nombre_dep(ranking.iloc[1]['id_departamento'])} le sigue con {st.horas(ranking.iloc[1]['brecha'])}"
    )
    titulo = f"{_titulo_localidad(primero['nombre_municipio'])} tiene la mayor brecha: recibe {st.num(primero['horas'], 1)} de 24 horas; {cola}"
    subtitulo = "Brecha = 24 horas menos las horas de servicio promedio por día, por municipio con prestación (todo el periodo disponible)."
    pie = (
        "Fuente: gold.fact_prestacion. Promedio de las observaciones localidad-mes de cada municipio, 2020-2026. "
        "El número de observaciones y de localidades muestra cuánta evidencia respalda cada barra; los municipios con pocos datos aparecen con color tenue."
    )
    fig = st.nuevo_lienzo(titulo, subtitulo, pie, ancho=12, alto=6.5)
    ax = fig.subplots()
    n = len(ranking)
    for posicion, fila in enumerate(ranking.itertuples()):
        y = n - 1 - posicion
        color = _color_dep(fila.id_departamento)
        ax.barh(y, fila.brecha, height=0.52, color=to_rgba(color, 0.45 if fila.evidencia_baja else 1.0), edgecolor=st.SUPERFICIE, linewidth=1)
        ax.text(fila.brecha + 0.3, y, st.horas(fila.brecha), ha="left", va="center", fontsize=10.5, fontweight="bold", color=st.TINTA)
        ax.text(HORAS_DIA + 4.2, y, f"{st.num(fila.observaciones)} obs. · {fila.localidades} loc.", ha="right", va="center", fontsize=9.5, color=st.TINTA_SECUNDARIA)
    ax.set_yticks(range(n))
    ax.set_yticklabels([_titulo_localidad(m) for m in ranking["nombre_municipio"][::-1]], fontsize=10.5, color=st.TINTA)
    ax.set_xlim(0, HORAS_DIA + 4.4)
    ax.set_xticks(range(0, 25, 6))
    ax.xaxis.set_major_formatter(st.formateador_horas())
    ax.set_ylim(-0.7, n - 0.2)
    ax.set_xlabel("Brecha de horas de servicio por día")
    ax.axvline(HORAS_DIA, color=st.LINEA_BASE, linewidth=1.0)
    ax.text(HORAS_DIA, n - 0.15, "24 h = sin servicio", ha="right", va="bottom", fontsize=9, color=st.TINTA_APAGADA)
    st.estilizar_eje(ax, rejilla="x")
    st.leyenda_departamentos(ax, [c for c in st.ORDEN_DEPARTAMENTOS if c in set(ranking["id_departamento"])])
    return fig


# ---------------------------------------------------------------------------
# 09. Evolución mensual por departamento
# ---------------------------------------------------------------------------
def fig_evolucion_departamentos(g: TABLAS) -> Figure:
    fact = g["fact_prestacion"]
    evo = an.evolucion_departamentos(g["ind_horas_servicio_departamento"])
    region = an.evolucion_region(fact)
    cambio = an.cambio_por_localidad(fact, g["dim_localidad"])
    datos = an.horas_observadas(fact)
    mayor = cambio.iloc[0]
    titulo = (
        f"Sin mejora generalizada: el salto de {_nombre_dep(mayor['id_departamento'])} es una sola localidad, "
        f"{_titulo_localidad(mayor['nombre_localidad'])} (de {st.num(mayor['horas_antes'], 0)} a {st.num(mayor['horas_despues'], 0)} horas)"
    )
    subtitulo = "Horas de servicio por día, promedio móvil de 6 meses por departamento (gris: región); en negro, la localidad que más cambió."
    pie = (
        "Fuente: gold.ind_horas_servicio_departamento y gold.fact_prestacion. El promedio de un departamento cambia cuando cambian las localidades que reportan "
        "(figura 02), por eso el de Putumayo (solo 2 o 3 localidades, una con ~24 h y otra con ~6 h) oscila tanto y el de Valle del Cauca baja en 2025, cuando "
        f"entran muchas localidades de pocas horas. Cambio medido entre {an.PARAMETROS['ventana_inicial'][0]}-{an.PARAMETROS['ventana_inicial'][-1]} y "
        f"{an.PARAMETROS['ventana_final'][0]}-{an.PARAMETROS['ventana_final'][-1]} (figura 10)."
    )
    fig = st.nuevo_lienzo(titulo, subtitulo, pie, ancho=12, alto=7.4)
    ejes = fig.subplots(2, 2, sharex=True, sharey=True)
    for ax, codigo in zip(ejes.flat, st.ORDEN_DEPARTAMENTOS):
        color = _color_dep(codigo)
        serie = evo[evo["id_departamento"] == codigo]
        ax.plot(region["periodo"], region["horas_movil"], color=st.LINEA_BASE, linewidth=1.6, zorder=1)
        ax.plot(serie["periodo"], serie["horas_movil"], color=color, linewidth=2.6, zorder=3)

        # La localidad del departamento con mayor cambio absoluto, para ver quién mueve el promedio
        candidatas = cambio[cambio["id_departamento"] == codigo]
        if len(candidatas):
            destacada = candidatas.iloc[int(candidatas["cambio"].abs().to_numpy().argmax())]
            propia = datos[datos["clave_localidad"] == destacada["clave_localidad"]].set_index("periodo")["horas"].sort_index()
            propia = propia.reindex(pd.date_range(propia.index.min(), propia.index.max(), freq="MS"))  # los meses sin reporte cortan la línea
            ax.plot(propia.index, propia.to_numpy(), color=st.TINTA, linewidth=1.1, alpha=0.8, zorder=2)
            ultimo = propia.dropna()
            ax.text(ultimo.index[-1], ultimo.iloc[-1] + 0.9, _titulo_localidad(destacada["nombre_localidad"]), ha="right", va="bottom", fontsize=9, color=st.TINTA)

        localidades = serie["localidades"].dropna()
        ax.plot([0.0], [1.14], marker="o", markersize=9, color=color, markeredgecolor=st.SUPERFICIE, markeredgewidth=1.5, transform=ax.transAxes, clip_on=False, linestyle="")
        ax.text(0.03, 1.10, _nombre_dep(codigo), transform=ax.transAxes, ha="left", va="bottom", fontsize=12, fontweight="bold", color=st.TINTA)
        ax.text(0.03, 1.01, f"{int(localidades.min())} a {int(localidades.max())} localidades reportan por mes", transform=ax.transAxes, ha="left", va="bottom", fontsize=9.5, color=st.TINTA_SECUNDARIA)
        ax.set_ylim(0, 25)
        ax.set_yticks(range(0, 25, 6))
        ax.yaxis.set_major_formatter(st.formateador_horas())
        ax.xaxis.set_major_locator(mdates.YearLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        st.estilizar_eje(ax, rejilla="y")
    return fig


# ---------------------------------------------------------------------------
# 10. Antes -> después por localidad
# ---------------------------------------------------------------------------
def fig_cambio_localidades(g: TABLAS) -> Figure:
    cambio = an.cambio_por_localidad(g["fact_prestacion"], g["dim_localidad"])
    resumen = an.resumen_cambio(cambio)
    antes, despues = an.PARAMETROS["ventana_inicial"], an.PARAMETROS["ventana_final"]
    etiqueta_antes = f"{antes[0]}-{antes[-1]}"
    etiqueta_despues = f"{despues[0]}-{despues[-1]}"
    fuertes = cambio[cambio["cambio"] > 5]
    nombres_fuertes = " y ".join(_titulo_localidad(n) for n in fuertes["nombre_localidad"].head(2))
    titulo = (
        f"De {resumen['localidades']} localidades, solo {len(fuertes)} mejoraron mucho ({nombres_fuertes}); "
        f"el cambio típico es de {'+' if resumen['mediana'] >= 0 else '−'}{st.num(abs(resumen['mediana']), 1)} horas"
    )
    subtitulo = f"Horas de servicio por día de cada localidad en {etiqueta_antes} (círculo claro) y en {etiqueta_despues} (círculo oscuro); solo localidades con datos en ambos periodos."
    pie = (
        f"Fuente: gold.fact_prestacion. Se exigen al menos {an.PARAMETROS['observaciones_minimas_ventana']} meses reportados en cada periodo. Mediana del cambio: "
        f"{st.num(resumen['mediana'], 1)} h (intervalo del 95 %: {st.num(resumen['mediana_inferior'], 1)} a {st.num(resumen['mediana_superior'], 1)}). "
        f"{resumen['mejoran']} mejoran, {resumen['empeoran']} empeoran y {resumen['se_mantienen']} se mantienen (±{st.num(resumen['umbral_horas'], 1)} h). "
        f"El cambio promedio ({st.num(resumen['media'], 1)} h) cae a {st.num(resumen['media_sin_las_dos_mayores_mejoras'], 1)} h sin las dos mayores mejoras."
    )
    alto = max(5.2, 1.7 + 0.25 * len(cambio))
    fig = st.nuevo_lienzo(titulo, subtitulo, pie, ancho=12, alto=alto)
    ax = fig.subplots()
    n = len(cambio)
    for posicion, fila in enumerate(cambio.itertuples()):
        y = n - 1 - posicion
        color = _color_dep(fila.id_departamento)
        ax.plot([fila.horas_antes, fila.horas_despues], [y, y], color=color, linewidth=2.2, solid_capstyle="round", zorder=2)
        ax.plot([fila.horas_antes], [y], marker="o", markersize=8, markerfacecolor=to_rgba(color, 0.30), markeredgecolor=color, markeredgewidth=1.6, linestyle="", zorder=3)
        ax.plot([fila.horas_despues], [y], marker="o", markersize=8, markerfacecolor=color, markeredgecolor=st.SUPERFICIE, markeredgewidth=1.3, linestyle="", zorder=4)
        signo = "+" if fila.cambio >= 0 else "−"
        ax.text(max(fila.horas_antes, fila.horas_despues) + 0.45, y, f"{signo}{st.num(abs(fila.cambio), 1)} h", ha="left", va="center", fontsize=9.5, color=st.TINTA_SECUNDARIA, fontweight="bold" if abs(fila.cambio) > 5 else "normal")
    ax.set_yticks(range(n))
    ax.set_yticklabels(_etiquetas_localidades(cambio)[::-1], fontsize=9.5, color=st.TINTA)
    ax.set_xlim(0, 26.5)
    ax.set_xticks(range(0, 25, 6))
    ax.xaxis.set_major_formatter(st.formateador_horas())
    ax.set_ylim(-0.7, n - 0.3)
    ax.set_xlabel("Horas de servicio por día")
    st.estilizar_eje(ax, rejilla="x")
    st.leyenda_departamentos(ax, [c for c in st.ORDEN_DEPARTAMENTOS if c in set(cambio["id_departamento"])])
    return fig


# ---------------------------------------------------------------------------
# 11. Estacionalidad
# ---------------------------------------------------------------------------
def fig_estacionalidad(g: TABLAS) -> Figure:
    desviacion = an.desviacion_respecto_a_la_localidad_anio(g["fact_prestacion"])
    perfil = an.media_con_intervalo(desviacion, "mes")
    mejor, peor = perfil.loc[perfil["media"].idxmax()], perfil.loc[perfil["media"].idxmin()]
    mes = lambda m: st.MESES_COMPLETOS[int(m) - 1]  # noqa: E731
    titulo = f"{mes(mejor['mes']).capitalize()} es el mes con más horas de servicio ({'+' if mejor['media'] >= 0 else '−'}{st.num(abs(mejor['media']), 1)} h) y {mes(peor['mes'])} el de menos ({'+' if peor['media'] >= 0 else '−'}{st.num(abs(peor['media']), 1)} h)"
    subtitulo = "Horas de servicio de cada mes frente al promedio de la misma localidad en el mismo año, con intervalo de confianza del 95 %."
    pie = (
        f"Fuente: gold.fact_prestacion. Localidad-años con al menos {an.PARAMETROS['meses_minimos_localidad_anio']} meses reportados "
        f"({st.num(desviacion['clave_localidad'].nunique())} localidades, {st.num(len(desviacion))} observaciones). Intervalos por remuestreo de localidades. "
        "Los datos no explican la causa; una hipótesis (no probada) es la mayor demanda de fin de año. Círculo relleno: el intervalo no incluye 0."
    )
    fig = st.nuevo_lienzo(titulo, subtitulo, pie, ancho=12, alto=5.4)
    ax = fig.subplots()
    ax.axhline(0, color=st.LINEA_BASE, linewidth=1.2)
    for fila in perfil.itertuples():
        significativo = fila.inferior > 0 or fila.superior < 0
        color = st.AZUL if significativo else st.TINTA_APAGADA
        ax.plot([fila.mes, fila.mes], [fila.inferior, fila.superior], color=color, linewidth=2.0, solid_capstyle="round", zorder=2)
        ax.plot([fila.mes], [fila.media], marker="o", markersize=10, markerfacecolor=color if significativo else st.SUPERFICIE, markeredgecolor=color, markeredgewidth=1.8, linestyle="", zorder=3)
    for fila, desplazamiento in ((mejor, 0.16), (peor, -0.16)):
        etiqueta = f"{'+' if fila['media'] >= 0 else '−'}{st.num(abs(fila['media']), 1)} h"
        ax.text(fila["mes"] + 0.22, fila["media"], etiqueta, ha="left", va="center", fontsize=11, fontweight="bold", color=st.TINTA)
    ax.set_xticks(range(1, 13))
    ax.set_xticklabels([m.capitalize() for m in st.MESES_ABREVIADOS], fontsize=10.5)
    ax.set_xlim(0.4, 12.9)
    limite = np.ceil(max(abs(perfil["inferior"].min()), abs(perfil["superior"].max())) * 2) / 2
    ax.set_ylim(-limite, limite)
    ax.yaxis.set_major_locator(MultipleLocator(0.5))
    ax.set_ylabel("Horas frente al promedio de la localidad en el año")
    ax.yaxis.set_major_formatter(FuncFormatterSigno())
    st.estilizar_eje(ax, rejilla="y")
    ax.text(0.45, -limite * 0.96, "menos horas que su promedio ▼", ha="left", va="bottom", fontsize=9, color=st.TINTA_APAGADA)
    ax.text(0.45, limite * 0.96, "más horas que su promedio ▲", ha="left", va="top", fontsize=9, color=st.TINTA_APAGADA)
    return fig


def FuncFormatterSigno():
    """Formateador de ticks con signo explícito (+0,5 / −0,5)."""
    return st.FuncFormatter(lambda v, _p: "0" if abs(v) < 1e-9 else f"{'+' if v > 0 else '−'}{st.num(abs(v), 1)}")


# ---------------------------------------------------------------------------
# 12. Operadores
# ---------------------------------------------------------------------------
def fig_operadores(g: TABLAS) -> Figure:
    ops = g["ind_comparacion_operadores"].copy()
    ops["corto"] = ops["nombre_operador"].map(an.abreviar_operador)
    ops = ops.sort_values("horas_servicio_promedio", ascending=False).reset_index(drop=True)
    mejor, peor = ops.iloc[0], ops.iloc[-1]
    ambos_unicos = int(mejor["n_localidades"]) == 1 and int(peor["n_localidades"]) == 1
    diferencia = mejor["horas_servicio_promedio"] - peor["horas_servicio_promedio"]
    titulo = f"Los operadores difieren hasta {st.num(diferencia, 0)} horas{', pero los dos extremos se miden con una sola localidad' if ambos_unicos else ''}"
    desde, hasta = pd.Timestamp(ops["periodo_desde"].min()), pd.Timestamp(ops["periodo_hasta"].max())
    subtitulo = f"Horas de servicio por día en las localidades de cada operador, {st.mes_corto(desde)} a {st.mes_corto(hasta)} ({len(ops)} operadores con localidades enlazadas a prestación)."
    ponderado = float((ops["horas_servicio_promedio"] * ops["n_observaciones_horas"]).sum() / ops["n_observaciones_horas"].sum())
    pie = (
        "Fuente: gold.ind_comparacion_operadores (prestación unida a operación diaria; solo localidades enlazables por código DIVIPOLA y meses con cobertura de operador). "
        "El registro de operador está congelado desde mar-2022. Barras tenues: operador observado menos de 3 meses, evidencia limitada."
    )
    fig = st.nuevo_lienzo(titulo, subtitulo, pie, ancho=12, alto=6.6)
    ax = fig.subplots()
    n = len(ops)
    for posicion, fila in enumerate(ops.itertuples()):
        y = n - 1 - posicion
        debil = fila.n_meses < 3
        ax.barh(y, fila.horas_servicio_promedio, height=0.52, color=to_rgba(st.AZUL, 0.38 if debil else 1.0), edgecolor=st.SUPERFICIE, linewidth=1)
        ax.text(fila.horas_servicio_promedio + 0.3, y, st.horas(fila.horas_servicio_promedio), ha="left", va="center", fontsize=10.5, fontweight="bold", color=st.TINTA, zorder=5)
        loc = "localidad" if fila.n_localidades == 1 else "localidades"
        mes_txt = "mes" if fila.n_meses == 1 else "meses"
        ax.text(HORAS_DIA + 0.6, y, f"{fila.n_localidades} {loc} · {fila.n_meses} {mes_txt}", ha="right", va="center", fontsize=9.5, color=st.TINTA_SECUNDARIA)
    ax.axvline(ponderado, color=st.LINEA_BASE, linewidth=1.6, zorder=1)
    ax.text(ponderado + 0.2, n - 0.15, f"promedio ponderado {st.horas(ponderado)}", ha="left", va="bottom", fontsize=9.5, color=st.TINTA, fontweight="bold")
    ax.set_yticks(range(n))
    ax.set_yticklabels(list(ops["corto"][::-1]), fontsize=10, color=st.TINTA)
    ax.set_xlim(0, HORAS_DIA + 0.8)
    ax.set_ylim(-0.7, n + 0.2)
    ax.set_xticks(range(0, 25, 6))
    ax.xaxis.set_major_formatter(st.formateador_horas())
    ax.set_xlabel("Horas de servicio por día")
    st.estilizar_eje(ax, rejilla="x")
    return fig


# ---------------------------------------------------------------------------
# 13. PQR
# ---------------------------------------------------------------------------
def fig_pqr(g: TABLAS) -> Figure:
    top = an.pqr_por_municipio(g["ind_pqr_empresa_municipio"], cuantos=10)
    comparables = an.pqr_frente_a_horas(g["ind_pqr_vs_horas_municipio"])
    correlacion = an.correlacion_pqr_horas(comparables)
    total = int(g["ind_pqr_empresa_municipio"]["n_pqr"].sum())
    primeros = top.head(3)
    nombres = ", ".join(_titulo_localidad(n) for n in primeros["nombre_municipio"][:-1]) + " y " + _titulo_localidad(primeros["nombre_municipio"].iloc[-1])
    participacion = float(primeros["n_pqr"].sum() / total * 100)
    rho = correlacion["rho"]
    titulo = f"{nombres} concentran el {st.num(participacion, 0)} % de las PQR, que no se relacionan con las horas de servicio (ρ = {st.num(rho, 2)})"
    subtitulo = f"Casos de PQR acumulados por municipio (izquierda, {st.num(total)} casos en total) y casos frente a horas de servicio por municipio y semestre (derecha)."
    pie = (
        "Fuente: gold.ind_pqr_empresa_municipio y gold.ind_pqr_vs_horas_municipio. ATENCIÓN: las PQR son de distribuidoras de GAS, no del servicio eléctrico: son contexto municipal. "
        f"A la derecha solo entran los {correlacion['pares']} municipio-semestre con prestación y semestre cubierto por PQR; el círculo hueco indica semestre cubierto sin casos (0)."
    )
    fig = st.nuevo_lienzo(titulo, subtitulo, pie, ancho=12, alto=6.0)
    ax_top, ax_dis = fig.subplots(1, 2, width_ratios=[1.15, 1.0])
    n = len(top)
    for posicion, fila in enumerate(top.itertuples()):
        y = n - 1 - posicion
        ax_top.barh(y, fila.n_pqr, height=0.5, color=_color_dep(fila.id_departamento), edgecolor=st.SUPERFICIE, linewidth=1)
        ax_top.text(fila.n_pqr + top["n_pqr"].max() * 0.015, y, st.num(fila.n_pqr), ha="left", va="center", fontsize=10, fontweight="bold", color=st.TINTA)
    ax_top.set_yticks(range(n))
    ax_top.set_yticklabels([_titulo_localidad(m) for m in top["nombre_municipio"][::-1]], fontsize=10, color=st.TINTA)
    ax_top.set_xlim(0, top["n_pqr"].max() * 1.16)
    ax_top.xaxis.set_major_formatter(st.formateador_numero())
    ax_top.set_xlabel("Casos de PQR")
    st.estilizar_eje(ax_top, rejilla="x")
    st.leyenda_departamentos(ax_top, [c for c in st.ORDEN_DEPARTAMENTOS if c in set(top["id_departamento"])], ncols=3)

    con_casos = comparables[comparables["casos"] > 0]
    sin_casos = comparables[comparables["casos"] == 0]
    ax_dis.scatter(con_casos["horas"], con_casos["casos"], s=70, color=st.AZUL, edgecolor=st.SUPERFICIE, linewidth=1.4, zorder=3)
    ax_dis.scatter(sin_casos["horas"], sin_casos["casos"], s=70, facecolor=st.SUPERFICIE, edgecolor=st.AZUL, linewidth=1.8, zorder=3)
    ax_dis.set_yscale("symlog", linthresh=1)
    mayor = con_casos.sort_values("casos", ascending=False).iloc[0] if len(con_casos) else None
    if mayor is not None:
        de_mayor = con_casos[con_casos["id_municipio"] == mayor["id_municipio"]]
        texto = f"{_titulo_localidad(mayor['nombre_municipio'])}\n({len(de_mayor)} semestres)"
        st.anotar(ax_dis, texto, xy=(de_mayor["horas"].max(), mayor["casos"]), xytext=(de_mayor["horas"].max() + 2.2, mayor["casos"]), ha="left", va="center")
    ax_dis.set_ylim(-0.4, max(500, comparables["casos"].max() * 1.6))
    ax_dis.set_yticks([0, 1, 10, 100])
    ax_dis.yaxis.set_major_formatter(st.formateador_numero())
    ax_dis.set_xlim(2, 18)
    ax_dis.xaxis.set_major_formatter(st.formateador_horas())
    ax_dis.set_xlabel("Horas de servicio por día en el municipio")
    ax_dis.set_ylabel("Casos de PQR en el semestre (escala logarítmica, con el 0)")
    st.estilizar_eje(ax_dis, rejilla="y")
    return fig


# ---------------------------------------------------------------------------
# 14. Peor desempeño combinado
# ---------------------------------------------------------------------------
def fig_peor_desempeno(g: TABLAS) -> Figure:
    pd_mun = g["ind_peor_desempeno_municipio"].sort_values("ranking_peor_desempeno").reset_index(drop=True)
    tres = ", ".join(_titulo_localidad(n) for n in pd_mun["nombre_municipio"].head(3))
    semestres = int(pd_mun["n_semestres_comparables"].max())
    titulo = f"{tres}: el peor desempeño combinado entre {len(pd_mun)} municipios"
    subtitulo = "Puntaje = promedio del percentil de la brecha de horas y del percentil de casos de PQR (1 = el peor). Izquierda: ranking; derecha: dónde cae cada municipio."
    pie = (
        f"Fuente: gold.ind_peor_desempeno_municipio ({semestres} semestres comparables con prestación y PQR). ATENCIÓN: las PQR son de distribuidoras de GAS; "
        "el puntaje las usa solo como contexto y no normaliza por población. Un municipio con muchas PQR y pocas horas puntúa más alto, pero el ranking por horas solas es otro (ver figura 08)."
    )
    fig = st.nuevo_lienzo(titulo, subtitulo, pie, ancho=12, alto=6.4)
    ax_rank, ax_cuad = fig.subplots(1, 2, width_ratios=[1.05, 1.0])
    n = len(pd_mun)
    for fila in pd_mun.itertuples():
        y = n - fila.ranking_peor_desempeno
        ax_rank.barh(y, fila.puntaje_combinado, height=0.52, color=_color_dep(fila.id_departamento), edgecolor=st.SUPERFICIE, linewidth=1)
        ax_rank.text(fila.puntaje_combinado + 0.015, y, st.num(fila.puntaje_combinado, 2), ha="left", va="center", fontsize=10, fontweight="bold", color=st.TINTA)
        ax_rank.text(-0.02, y, str(fila.ranking_peor_desempeno), ha="right", va="center", fontsize=10, color=st.TINTA_APAGADA)
    ax_rank.set_yticks(range(n))
    ax_rank.set_yticklabels([_titulo_localidad(m) for m in pd_mun.sort_values("ranking_peor_desempeno", ascending=False)["nombre_municipio"]], fontsize=10, color=st.TINTA)
    ax_rank.tick_params(axis="y", pad=22)
    ax_rank.set_xlim(0, 1.0)
    ax_rank.xaxis.set_major_formatter(st.formateador_numero(1))
    ax_rank.set_xlabel("Puntaje combinado (0 a 1)")
    st.estilizar_eje(ax_rank, rejilla="x")
    st.leyenda_departamentos(ax_rank, [c for c in st.ORDEN_DEPARTAMENTOS if c in set(pd_mun["id_departamento"])], ncols=4)

    ax_cuad.axvline(0.5, color=st.REJILLA, linewidth=1.0)
    ax_cuad.axhline(0.5, color=st.REJILLA, linewidth=1.0)
    for fila in pd_mun.itertuples():
        ax_cuad.scatter(fila.percentil_brecha_horas, fila.percentil_pqr, s=330, color=st.AZUL, edgecolor=st.SUPERFICIE, linewidth=1.5, zorder=3)
        ax_cuad.text(fila.percentil_brecha_horas, fila.percentil_pqr, str(fila.ranking_peor_desempeno), ha="center", va="center", fontsize=9.5, fontweight="bold", color=st.SUPERFICIE, zorder=4)
    ax_cuad.text(0.99, 0.99, "más brecha y más PQR", ha="right", va="top", fontsize=9.5, color=st.TINTA_APAGADA, transform=ax_cuad.transAxes)
    ax_cuad.text(0.01, 0.01, "menos brecha, menos PQR", ha="left", va="bottom", fontsize=9.5, color=st.TINTA_APAGADA, transform=ax_cuad.transAxes)
    ax_cuad.set_xlim(-0.04, 1.08)
    ax_cuad.set_ylim(-0.04, 1.08)
    ax_cuad.xaxis.set_major_formatter(st.formateador_numero(1))
    ax_cuad.yaxis.set_major_formatter(st.formateador_numero(1))
    ax_cuad.set_xlabel("Percentil de la brecha de horas (1 = mayor brecha)")
    ax_cuad.set_ylabel("Percentil de casos de PQR (1 = más casos)")
    st.estilizar_eje(ax_cuad, rejilla=None)
    return fig


# ---------------------------------------------------------------------------
# 15. Localidades con menos horas
# ---------------------------------------------------------------------------
def fig_localidades_menos_horas(g: TABLAS) -> Figure:
    menos = an.localidades_con_menos_horas(g["fact_prestacion"], g["dim_localidad"], cuantas=15)
    peor_municipio = menos["nombre_municipio"].value_counts()
    municipio, cuantas = peor_municipio.index[0], int(peor_municipio.iloc[0])
    ocho = menos.head(8)
    en_ocho = int((ocho["nombre_municipio"] == municipio).sum())
    bajo_3 = int((menos["horas"] < 3).sum())
    titulo = f"{_titulo_localidad(municipio)} concentra a las localidades con menos horas: {en_ocho} de las {len(ocho)} peores; {bajo_3} reciben menos de 3 horas al día"
    subtitulo = f"Las 15 localidades con menos horas de servicio por día en promedio, con al menos {an.PARAMETROS['meses_minimos_ranking_localidad']} meses reportados."
    pie = (
        "Fuente: gold.fact_prestacion. 'Meses' = meses reportados de la localidad; entre paréntesis, meses con energía activa igual a 0 (sin servicio). "
        "Las localidades con pocos meses reportados tienen un promedio menos estable."
    )
    fig = st.nuevo_lienzo(titulo, subtitulo, pie, ancho=12, alto=6.5)
    ax = fig.subplots()
    n = len(menos)
    for posicion, fila in enumerate(menos.itertuples()):
        y = n - 1 - posicion
        ax.barh(y, fila.horas, height=0.52, color=_color_dep(fila.id_departamento), edgecolor=st.SUPERFICIE, linewidth=1)
        ax.text(fila.horas + 0.2, y, st.horas(fila.horas), ha="left", va="center", fontsize=10.5, fontweight="bold", color=st.TINTA)
        sin = f" ({fila.meses_sin_servicio} sin servicio)" if fila.meses_sin_servicio else ""
        ax.text(1.0, y, f"{fila.meses} meses{sin}", ha="right", va="center", fontsize=9.5, color=st.TINTA_SECUNDARIA, transform=ax.get_yaxis_transform())
    ax.set_yticks(range(n))
    ax.set_yticklabels(_etiquetas_localidades(menos)[::-1], fontsize=10, color=st.TINTA)
    limite = max(12, int(np.ceil((menos["horas"].max() + 4) / 3) * 3))  # deja sitio a la etiqueta de valor y a la columna de meses
    ax.set_xlim(0, limite)
    ax.set_ylim(-0.7, n - 0.2)
    ax.set_xticks(range(0, limite + 1, 3))
    ax.xaxis.set_major_formatter(st.formateador_horas())
    ax.set_xlabel("Horas de servicio por día (promedio)")
    st.estilizar_eje(ax, rejilla="x")
    st.leyenda_departamentos(ax, [c for c in st.ORDEN_DEPARTAMENTOS if c in set(menos["id_departamento"])], ncols=4)
    return fig


# ---------------------------------------------------------------------------
# 16. Operación diaria: flota y horas declaradas
# ---------------------------------------------------------------------------
def fig_operacion_diaria(g: TABLAS, operacion: pd.DataFrame) -> Figure:
    ctx = an.contexto_operacion_diaria(operacion)
    porcentaje = ctx["proporcion_4_5_u_8_horas"] * 100
    titulo = (
        f"La bitácora diaria declara casi siempre 4, 5 u 8 horas ({st.num(porcentaje, 0)} % de los registros): "
        "parece un horario fijo, no una medición"
    )
    subtitulo = (
        f"Operación diaria {st.mes_corto(ctx['desde'])} a {st.mes_corto(ctx['hasta'])}: {st.num(ctx['registros'])} registros, "
        f"{st.num(ctx['localidades'])} localidades y {st.num(ctx['generadores'])} generadores en {ctx['municipios']} municipios."
    )
    pie = (
        f"Fuente: silver.operacion_diaria (qwe5-ycap). El {st.num(ctx['proporcion_calculado'] * 100, 0)} % del tiempo de servicio figura como 'CALCULADO', no medido; por eso "
        "las horas de la bitácora no sirven para comparar operadores y se usan las de prestación. Marcas tal como las reportan los operadores (PERKIN y PERKINS aparecen separadas)."
    )
    fig = st.nuevo_lienzo(titulo, subtitulo, pie, ancho=12, alto=5.6)
    ax_marcas, ax_capacidad, ax_horas = fig.subplots(1, 3, width_ratios=[1.0, 1.0, 1.1])

    marcas = ctx["marcas"].head(8)
    n = len(marcas)
    for posicion, fila in enumerate(marcas.itertuples()):
        y = n - 1 - posicion
        ax_marcas.barh(y, fila.generadores, height=0.5, color=st.AZUL, edgecolor=st.SUPERFICIE, linewidth=1)
        ax_marcas.text(fila.generadores + marcas["generadores"].max() * 0.02, y, st.num(fila.generadores), ha="left", va="center", fontsize=9.5, color=st.TINTA)
    ax_marcas.set_yticks(range(n))
    ax_marcas.set_yticklabels([str(m).title() for m in marcas["marca"][::-1]], fontsize=9.5, color=st.TINTA)
    ax_marcas.set_xlim(0, marcas["generadores"].max() * 1.18)
    ax_marcas.set_title("Generadores por marca", fontsize=11.5)
    ax_marcas.xaxis.set_major_formatter(st.formateador_numero())
    st.estilizar_eje(ax_marcas, rejilla="x")

    capacidad = ctx["capacidad"].dropna()
    limite = 200.0
    contenedores = np.arange(0, limite + 0.1, 10)
    cuentas, bordes = np.histogram(capacidad.clip(upper=limite - 0.01), bins=contenedores)
    ax_capacidad.bar(bordes[:-1] + 5, cuentas, width=10, color=st.AZUL, edgecolor=st.SUPERFICIE, linewidth=1)
    mediana = float(capacidad.median())
    ax_capacidad.axvline(mediana, color=st.TINTA, linewidth=1.5)
    st.anotar(ax_capacidad, f"mediana {st.num(mediana, 0)}", xy=(mediana, cuentas.max() * 0.80), xytext=(mediana + 55, cuentas.max() * 0.80), ha="left", va="center", color=st.TINTA)
    ax_capacidad.set_title("Capacidad por generador", fontsize=11.5)
    ax_capacidad.set_xlabel("Capacidad de generación (unidad de la fuente)")
    ax_capacidad.set_xlim(0, limite)
    ax_capacidad.set_xticks([0, 50, 100, 150, 200])
    ax_capacidad.set_xticklabels(["0", "50", "100", "150", "200 o más"])
    ax_capacidad.yaxis.set_major_formatter(st.formateador_numero())
    st.estilizar_eje(ax_capacidad, rejilla="y")

    dist = ctx["distribucion_horas"]
    todas = pd.DataFrame({"horas": range(0, 13)}).merge(dist, on="horas", how="left").fillna({"proporcion": 0.0})
    colores = [st.AZUL if h in (4, 5, 8) else to_rgba(st.AZUL, 0.35) for h in todas["horas"]]
    ax_horas.bar(todas["horas"], todas["proporcion"] * 100, width=0.78, color=colores, edgecolor=st.SUPERFICIE, linewidth=1)
    for fila in todas.itertuples():
        if fila.horas in (4, 5, 8):
            ax_horas.text(fila.horas, fila.proporcion * 100 + 1.2, st.porcentaje(fila.proporcion * 100, 0), ha="center", va="bottom", fontsize=9.5, fontweight="bold", color=st.TINTA)
    ax_horas.set_title("Horas declaradas por registro", fontsize=11.5)
    ax_horas.set_xlabel("Horas de servicio declaradas en el día")
    ax_horas.set_xticks(range(0, 13, 2))
    ax_horas.set_xticklabels([str(h) if h < 12 else "12+" for h in range(0, 13, 2)])
    ax_horas.set_ylim(0, todas["proporcion"].max() * 100 * 1.16)
    ax_horas.yaxis.set_major_formatter(st.formateador_porcentaje())
    st.estilizar_eje(ax_horas, rejilla="y")
    return fig


# ---------------------------------------------------------------------------
# Registro de figuras: nombre de archivo -> FiguraEDA
# ---------------------------------------------------------------------------
class FiguraEDA(NamedTuple):
    funcion: Callable[..., Figure]
    requiere_operacion: bool  # la figura necesita silver/operacion_diaria además de gold
    seccion: str  # P1 a P6 son las preguntas del MVP del documento de diseño (sección 6.1)


FIGURAS: dict[str, FiguraEDA] = {
    "fig01_frescura_fuentes": FiguraEDA(fig_frescura_fuentes, False, "Preanálisis: calidad y cobertura"),
    "fig02_cobertura_mensual": FiguraEDA(fig_cobertura_mensual, False, "Preanálisis: calidad y cobertura"),
    "fig03_mapa_reporte_localidades": FiguraEDA(fig_mapa_reporte_localidades, False, "Preanálisis: calidad y cobertura"),
    "fig04_distribucion_horas": FiguraEDA(fig_distribucion_horas, False, "Preanálisis: distribuciones y relaciones"),
    "fig05_concentracion_energia": FiguraEDA(fig_concentracion_energia, False, "Preanálisis: distribuciones y relaciones"),
    "fig06_correlaciones": FiguraEDA(fig_correlaciones, False, "Preanálisis: distribuciones y relaciones"),
    "fig07_estado_departamentos": FiguraEDA(fig_estado_departamentos, False, "P1 · Estado actual"),
    "fig08_brechas_municipios": FiguraEDA(fig_brechas_municipios, False, "P2 · Brechas"),
    "fig09_evolucion_departamentos": FiguraEDA(fig_evolucion_departamentos, False, "P3 · Evolución"),
    "fig10_cambio_localidades": FiguraEDA(fig_cambio_localidades, False, "P3 · Evolución"),
    "fig11_estacionalidad": FiguraEDA(fig_estacionalidad, False, "P3 · Evolución"),
    "fig12_operadores": FiguraEDA(fig_operadores, False, "P4 · Operadores"),
    "fig13_pqr": FiguraEDA(fig_pqr, False, "P5 · PQR"),
    "fig14_peor_desempeno": FiguraEDA(fig_peor_desempeno, False, "P6 · Peor desempeño"),
    "fig15_localidades_menos_horas": FiguraEDA(fig_localidades_menos_horas, False, "P6 · Peor desempeño"),
    "fig16_operacion_diaria": FiguraEDA(fig_operacion_diaria, True, "Contexto: operación diaria"),
}
