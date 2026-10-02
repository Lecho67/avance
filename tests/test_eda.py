"""Pruebas del análisis exploratorio (src/eda): cálculos, formato, figuras y orquestador. Sin red.

Los datos de prueba son un mini-mundo sintético de 10 localidades en los 4 departamentos, de 2020-01 a 2025-12, que
pasa por los MISMOS limpiadores y por la construcción real de gold: así el EDA se prueba contra el esquema que gold
produce de verdad (si gold cambia de columnas, estas pruebas lo detectan) y no contra tablas inventadas a mano.
El mundo tiene patrones conocidos: una localidad que mejora mucho (Puerto Merizalde: de 7 a 22 horas desde 2022),
una con servicio casi continuo (Puerto Leguízamo), estacionalidad (diciembre mejor, enero peor) y meses sin reporte.
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from matplotlib.figure import Figure

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import main as orquestador  # noqa: E402
from src import reiniciar_errores_controlados  # noqa: E402
from src.eda import analysis as an  # noqa: E402
from src.eda import charts  # noqa: E402
from src.eda import run_eda  # noqa: E402
from src.eda import style as st  # noqa: E402
from src.transform import clean_excel as limpieza  # noqa: E402
from src.transform import gold_transformations as gold  # noqa: E402

CARGA = pd.Timestamp("2026-09-30 12:00:00", tz="UTC")
PORTAL = pd.Timestamp("2026-03-13 14:42:17", tz="UTC")
IDS_FUENTE = {"prestacion": "3ebi-d83g", "operacion_diaria": "qwe5-ycap", "pqr": "5wua-nr2d"}

# (id_dpto, id_mpio, id_localidad, nombre en la fuente, horas base, meses sin reporte, energía base)
LOCALIDADES = [
    ("19", "19318", "19318008", "LIMONES (GUAPI - CAUCA)", 8.0, (), 9000),
    ("19", "19318", "19318013", "SAN ANTONIO DE GUAJUI (GUAPI - CAUCA)", 6.0, (12, 13, 14, 15, 16, 17, 18, 40, 41, 42), 6000),
    ("19", "19809", "19809003", "COTEJE (TIMBIQUI - CAUCA)", 5.5, (), 7000),
    ("52", "52835", "52835055", "BOCAS DE CURAY (TUMACO - NARIÑO)", 6.0, (), 8000),
    ("52", "52835", "52835016", "PITAL DE LA COSTA (TUMACO - NARIÑO)", 8.0, tuple(range(24, 48)), 9500),
    ("52", "52427", "52427910", "EL ROSARIO (MAGUI - NARIÑO)", 1.0, tuple(range(0, 40)), 400),
    ("76", "76109", "76109028", "PUERTO MERIZALDE (BUENAVENTURA - VALLE DEL CAUCA)", 7.0, (), 30000),
    ("76", "76109", "76109032", "SAN FRANCISCO NAYA (BUENAVENTURA - VALLE DEL CAUCA)", 7.5, (), 8000),
    ("86", "86573", "86573000", "PUERTO LEGUIZAMO (PUERTO LEGUIZAMO - PUTUMAYO)", 23.5, tuple(range(30, 34)), 800000),
    ("86", "86573", "86573009", "PINUNA NEGRO (PUERTO LEGUIZAMO - PUTUMAYO)", 6.0, (), 5000),
]
MESES = pd.date_range("2020-01-01", "2025-12-01", freq="MS")


def _con_trazabilidad(df: pd.DataFrame, fuente: str) -> pd.DataFrame:
    df = df.copy()
    df["_fuente_id"] = IDS_FUENTE[fuente]
    df["_fecha_carga"] = CARGA
    df["_fecha_corte_fuente"] = PORTAL
    df["_lote_id"] = "lote-prueba"
    return df


def _horas_del_mes(indice_loc: int, base: float, posicion: int, fecha: pd.Timestamp, generador: np.random.Generator) -> float:
    """Horas sintéticas con los patrones conocidos del mundo de prueba."""
    horas = base + generador.normal(0, 0.35)
    horas += {12: 1.0, 1: -1.0}.get(fecha.month, 0.0) if base < 12 else 0.0
    if LOCALIDADES[indice_loc][2] == "76109028" and fecha >= pd.Timestamp("2022-01-01"):
        horas = 22.0 + generador.normal(0, 0.8)
    return float(np.clip(horas, 0.0, 24.0))


def bronce_prestacion() -> pd.DataFrame:
    generador = np.random.default_rng(7)
    filas = []
    for indice, (dpto, mpio, id_loc, nombre, base, sin_reporte, energia) in enumerate(LOCALIDADES):
        for posicion, fecha in enumerate(MESES):
            if posicion in sin_reporte:
                continue
            horas = _horas_del_mes(indice, base, posicion, fecha, generador)
            filas.append(
                {
                    "id_dpto": dpto, "dpto": "DPTO", "id_mpio": mpio, "mpio": "MPIO", "id_localidad": id_loc, "localidad": nombre,
                    "anio": str(fecha.year), "mes": str(fecha.month), "energia_activa": str(int(energia * horas / max(base, 1.0))),
                    "energia_reactiva": str(int(energia * 0.3)), "potencia_maxima": str(30 + int(horas * 3)), "dia_demanda_maxima": "lunes",
                    "fecha_demanda_maxima": f"{fecha.year}-{fecha.month:02d}-10T10:00:00.000", "prom_diario_horas": f"{horas:.2f}",
                }
            )
    return _con_trazabilidad(pd.DataFrame(filas), "prestacion")


def bronce_operacion() -> pd.DataFrame:
    """Localidades enlazables (centro poblado distinto de 000) con operador, de 2021-07 a 2022-03."""
    operadores = {
        "1931800800001": ("1892", "EMPRESA DE ENERGIA DE GUAPI S.A. E.S.P."),
        "1980900300001": ("1892", "EMPRESA DE ENERGIA DE GUAPI S.A. E.S.P."),
        "5283505500001": ("26040", "EMPRESA ASOCIATIVA DE TRABAJO DE BOCAS DE CURAY E.S.P."),
        "7610902800001": ("20432", "ELECTRIFICADORA DEL PACIFICO S.A. E.S.P."),
        "7610903200001": ("20432", "ELECTRIFICADORA DEL PACIFICO S.A. E.S.P."),
        "5242791000001": ("25681", "ASOCIACION DE ENERGIA DE LAS ZONAS RURALES DEL MUNICIPIO DE EL CHARCO"),
    }
    filas = []
    for codigo, (empresa, nombre) in operadores.items():
        for fecha in pd.date_range("2021-07-01", "2022-03-01", freq="MS"):
            for dia in (5, 6):
                fila_fecha = f"{fecha.year}-{fecha.month:02d}-{dia:02d}"
                filas.append(
                    {
                        "serie_generador": f"G{codigo[-8:]}", "dane_nom_poblad": "LOC", "energia_generada": "100", "identificador_empresa": empresa,
                        "ano": str(fecha.year), "periodo": str(fecha.month), "marca": "LISTER", "fecha": f"{fila_fecha}T00:00:00.000", "dane_nom_dpto": "DPTO",
                        "nombre_localidad": "LOC", "dane_nom_mpio": "MPIO", "horometro": "100", "codigo_localidad": codigo, "capacidad_generacion": "40",
                        "tipo_medida": "CALCULADO", "nombre": nombre, "tiempo_servicio": "5",
                    }
                )
    return _con_trazabilidad(pd.DataFrame(filas), "operacion_diaria")


def bronce_pqr() -> pd.DataFrame:
    """Casos mensuales en 2021-07..2021-12, 2022-01..2022-06 y 2023-01..2023-06 (semestres 2021-2, 2022-1 y 2023-1)."""
    municipios = [("52", "835"), ("76", "109"), ("19", "318"), ("52", "427")]
    meses = list(pd.date_range("2021-07-01", "2022-06-01", freq="MS")) + list(pd.date_range("2023-01-01", "2023-06-01", freq="MS"))
    filas = []
    for fecha in meses:
        for numero, (depto, mpio) in enumerate(municipios):
            if (depto, mpio) == ("52", "427") and fecha.month % 2:
                continue  # Magüí casi sin casos
            casos = 5 if (depto, mpio) == ("52", "835") else 1
            for k in range(casos):
                radicado = f"{fecha.year}-{fecha.month:02d}-15T00:00:00.000"
                respondido = f"{fecha.year}-{fecha.month:02d}-18T00:00:00.000" if k % 2 == 0 else None
                filas.append(
                    {
                        "identificador_empresa": "6026", "are_esp_nombre": "GAS A S.A. ESP", "car_carg_ano": str(fecha.year), "car_carg_periodo": str(fecha.month),
                        "car_t1554_dane_depto": depto, "dane_nom_dpto": "DPTO", "car_t1554_dane_mpio": mpio, "dane_nom_mpio": "MPIO",
                        "rad_recibido": f"{depto}{mpio}{fecha.year}{fecha.month}{k}{numero}", "rad_fecha": radicado, "respuesta_fecha": respondido,
                        "notifica_fecha": respondido, "fecha_traslado": None,
                    }
                )
    return _con_trazabilidad(pd.DataFrame(filas), "pqr")


@pytest.fixture(scope="module")
def tablas_gold() -> dict[str, pd.DataFrame]:
    silver = {
        "prestacion": limpieza.limpiar_prestacion(bronce_prestacion()),
        "operacion_diaria": limpieza.limpiar_operacion_diaria(bronce_operacion()),
        "pqr": limpieza.limpiar_pqr(bronce_pqr()),
    }
    tablas = dict(gold.construir_tablas(silver).tablas)
    tablas["kpis_pipeline"] = pd.DataFrame(
        {"indicador": ["pct_fuentes_integradas"], "valor": [100.0], "unidad": ["%"], "meta": [100], "sentido_meta": [">="], "cumple": [True], "detalle": ["{}"]}
    )
    return tablas


@pytest.fixture(scope="module")
def silver_operacion() -> pd.DataFrame:
    return limpieza.limpiar_operacion_diaria(bronce_operacion())


@pytest.fixture(scope="module")
def dibujos(tablas_gold, silver_operacion):
    """Cada figura del registro, construida una vez con los datos de prueba."""
    figuras = {}
    with st.tema():
        for nombre, figura in charts.FIGURAS.items():
            figuras[nombre] = figura.funcion(tablas_gold, silver_operacion) if figura.requiere_operacion else figura.funcion(tablas_gold)
    return figuras


# ---------------------------------------------------------------------------
# Formato y estilo
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "valor, decimales, esperado",
    [
        (1234.5, 1, "1.234,5"),
        (4670, 0, "4.670"),
        (0.567, 2, "0,57"),
        (-0.48, 1, "−0,5"),
        (-0.04, 1, "0,0"),  # nunca '-0,0'
        (1234567, 0, "1.234.567"),
        (float("nan"), 1, "s. d."),
        (None, 1, "s. d."),
    ],
)
def test_num_usa_coma_decimal_punto_de_miles_y_signo_menos_tipografico(valor, decimales, esperado):
    assert st.num(valor, decimales) == esperado


def test_horas_y_porcentaje_siguen_la_convencion_del_proyecto():
    assert st.horas(7.04) == "7,0 h"
    assert st.porcentaje(64.6, 1) == "64,6 %"
    assert st.mes_corto("2026-01-15") == "ene-2026"


def test_cada_departamento_tiene_un_color_fijo_y_distinto_en_orden_dane():
    assert st.ORDEN_DEPARTAMENTOS == sorted(st.ORDEN_DEPARTAMENTOS)
    colores = [st.COLOR_DEPARTAMENTO[c] for c in st.ORDEN_DEPARTAMENTOS]
    assert len(set(colores)) == 4
    # los cuatro vienen de la paleta de referencia validada (ranuras 1 a 4)
    assert colores == [st.AZUL, st.NARANJA, st.AQUA, st.AMARILLO]
    assert set(st.NOMBRE_DEPARTAMENTO) == set(st.COLOR_DEPARTAMENTO) == set(st.ORDEN_DEPARTAMENTOS)


def test_etiquetas_unicas_agrega_el_codigo_solo_a_los_nombres_repetidos():
    df = pd.DataFrame({"texto": ["Puerto Leguízamo", "Puerto Leguízamo", "Pital"], "codigo": ["86573000", "86573009", "52835016"]})
    assert st.etiquetas_unicas(df, "texto", "codigo") == ["Puerto Leguízamo (86573000)", "Puerto Leguízamo (86573009)", "Pital"]


@pytest.mark.parametrize(
    "original, esperado",
    [
        ("SANTA BÁRBARA (ISCUANDÉ)", "Santa Bárbara (Iscuandé)"),
        ("SAN JUAN DE LA COSTA", "San Juan de la Costa"),
        ("PUERTO LEGUÍZAMO", "Puerto Leguízamo"),
        ("EL CHARCO", "El Charco"),
    ],
)
def test_titulo_nombre_respeta_conectores_y_parentesis(original, esperado):
    assert an.titulo_nombre(original) == esperado


@pytest.mark.parametrize(
    "original, esperado",
    [
        ("EMPRESA DE ENERGÍA DE GUAPI S.A. E.S.P.", "Energía Guapí"),
        ("ELECTRIFICADORA DEL PACIFICO S.A. E.S.P.", "Electrificadora del Pacífico"),
        ("COOPERATIVA DE SERVICIOS PÚBLICOS DE LÓPEZ DE MICAY", "Coop. Servicios Públicos López de Micay"),
        ("EMPRESA ASOCIATIVA DE TRABAJO ELECTROSOLEDAD DE ISCUANDE", "EAT Electrosoledad de Iscuandé"),
        ("EMPRESA DE SERVICIOS PUBLICOS DEL OCCIDENTE COLOMBIANO S.A.", "ESP del Occidente Colombiano"),
        ("EMPRESA DE SERVICIOS PÚBLICOS DE ENERGÍA ELÉCTRICA DE LAS PLAYAS ASOCIADAS - ENERPLASO S.A. E.S.P.", "Enerplaso"),
        ("ASOCIACION DE ENERGIA DE LAS ZONAS RURALES DEL MUNICIPIO DE EL CHARCO", "Asoc. Energía Rural El Charco"),
    ],
)
def test_abreviar_operador_quita_la_razon_social_y_abrevia_las_formulas_largas(original, esperado):
    assert an.abreviar_operador(original) == esperado


def test_abreviar_operador_trunca_los_nombres_muy_largos_y_tolera_nulos():
    corto = an.abreviar_operador("UNA ASOCIACION CON UN NOMBRE EXTRAORDINARIAMENTE LARGO QUE NO CABE EN UNA ETIQUETA", maximo=30)
    assert len(corto) <= 30 and corto.endswith("…") and corto.startswith("Una Asociacion")
    assert an.abreviar_operador(None) == "s. d."


def test_nuevo_lienzo_pone_el_titulo_primero_y_deja_el_pie_con_la_fuente():
    fig = st.nuevo_lienzo("Un hallazgo", "Qué se mide", "Fuente: prueba", ancho=10, alto=5)
    textos = [t.get_text() for t in fig.texts]
    assert textos[0] == "Un hallazgo" and "Qué se mide" in textos and "Fuente: prueba" in textos


# ---------------------------------------------------------------------------
# Carga
# ---------------------------------------------------------------------------
def test_cargar_gold_falla_con_un_mensaje_que_dice_que_hacer(tmp_path, tablas_gold):
    tablas_gold["dim_municipio"].to_parquet(tmp_path / "dim_municipio.parquet", index=False)
    with pytest.raises(FileNotFoundError, match="python main.py --etapa gold"):
        an.cargar_gold(tmp_path)


def test_cargar_operacion_diaria_devuelve_none_si_no_hay_silver(tmp_path):
    assert an.cargar_operacion_diaria(tmp_path / "no_existe.parquet") is None


# ---------------------------------------------------------------------------
# Cálculos
# ---------------------------------------------------------------------------
def test_horas_observadas_excluye_las_filas_sin_horas_y_deja_columnas_planas(tablas_gold):
    fact = tablas_gold["fact_prestacion"].copy()
    fact.loc[fact.index[:5], "horas_servicio_promedio_dia"] = pd.NA
    datos = an.horas_observadas(fact)
    assert len(datos) == len(fact) - 5
    assert datos["horas"].dtype == float and datos["energia"].dtype == float


def test_cobertura_mensual_cuenta_localidades_distintas_por_mes_y_departamento(tablas_gold):
    cobertura = an.cobertura_mensual(tablas_gold["fact_prestacion"])
    assert list(cobertura.index[:2]) == [pd.Timestamp("2020-01-01"), pd.Timestamp("2020-02-01")]
    # 2020-01: todas reportan salvo El Rosario (Nariño), que arranca en el mes 41
    assert cobertura.loc["2020-01-01"].to_dict() == {"19": 3, "52": 2, "76": 2, "86": 2}
    # 2022-12 (mes 35): Leguízamo no reportó entre los meses 30 y 33; Pital de la Costa sí falta (24 a 47)
    assert cobertura.loc["2022-12-01", "52"] == 1


def test_matriz_reporte_ordena_por_departamento_y_por_continuidad(tablas_gold):
    matriz, orden = an.matriz_reporte(tablas_gold["fact_prestacion"], tablas_gold["dim_localidad"])
    assert matriz.shape == (10, len(MESES))
    assert list(orden["id_departamento"]) == sorted(orden["id_departamento"])
    for _, grupo in orden.groupby("id_departamento"):
        assert list(grupo["meses"]) == sorted(grupo["meses"], reverse=True)
    assert list(matriz.index) == list(orden["clave_localidad"])


def test_concentracion_energia_suma_100_por_ciento_y_ordena_de_mayor_a_menor(tablas_gold):
    conc = an.concentracion_energia(tablas_gold["fact_prestacion"], tablas_gold["dim_localidad"])
    assert conc["participacion"].sum() == pytest.approx(1.0)
    assert conc["participacion_acumulada"].iloc[-1] == pytest.approx(1.0)
    assert conc["energia_total"].is_monotonic_decreasing
    assert "LEGUIZAMO" in conc.iloc[0]["clave_localidad"]
    n80 = an.localidades_para_participacion(conc, 0.8)
    assert conc["participacion_acumulada"].iloc[n80 - 1] >= 0.8 > conc["participacion_acumulada"].iloc[max(n80 - 2, 0)] or n80 == 1


def test_localidades_para_participacion_con_cifras_conocidas():
    conc = pd.DataFrame({"participacion_acumulada": [0.5, 0.7, 0.85, 1.0]})
    assert an.localidades_para_participacion(conc, 0.8) == 3
    assert an.localidades_para_participacion(conc, 0.4) == 1


def test_correlaciones_spearman_es_simetrica_con_diagonal_uno(tablas_gold):
    corr = an.correlaciones_spearman(tablas_gold["fact_prestacion"])
    assert list(corr.index) == list(corr.columns) and len(corr) == 4
    assert np.allclose(np.diag(corr.to_numpy()), 1.0)
    assert np.allclose(corr.to_numpy(), corr.to_numpy().T, equal_nan=True)
    assert corr.loc["Horas de servicio", "Energía activa"] > 0.5  # en el mundo de prueba la energía crece con las horas


def test_estado_reciente_usa_la_ventana_pedida_y_la_brecha_es_24_menos_las_horas(tablas_gold):
    fact = tablas_gold["fact_prestacion"]
    estado = an.estado_reciente(fact, meses=6)
    assert estado["desde"].iloc[0] == pd.Timestamp("2025-07-01") and estado["hasta"].iloc[0] == pd.Timestamp("2025-12-01")
    assert estado["brecha"].tolist() == pytest.approx((24 - estado["horas"]).tolist())
    ventana = fact[fact["periodo"] >= "2025-07-01"]
    esperado = float(ventana["horas_servicio_promedio_dia"].astype(float).mean())
    assert estado.loc[estado["codigo"] == "REGION", "horas"].iloc[0] == pytest.approx(esperado)
    assert set(estado["codigo"]) == {"19", "52", "76", "86", "REGION"}


def test_ultimo_mes_con_datos_cuenta_localidades_y_servicio(tablas_gold):
    ultimo = an.ultimo_mes_con_datos(tablas_gold["fact_prestacion"])
    assert ultimo["periodo"] == pd.Timestamp("2025-12-01")
    assert ultimo["localidades_reportadas"] == 10 and ultimo["localidades_con_servicio"] == 10  # en 2025-12 reportan las 10, todas con energía


def test_ranking_municipios_brecha_ordena_de_mayor_a_menor_y_marca_la_evidencia_baja(tablas_gold, monkeypatch):
    ranking = an.ranking_municipios_brecha(tablas_gold["fact_prestacion"], tablas_gold["dim_municipio"])
    assert ranking["brecha"].is_monotonic_decreasing
    assert ranking.iloc[0]["id_municipio"] == "52427"  # Magüí: la localidad de ~1 hora
    assert ranking["brecha"].tolist() == pytest.approx((24 - ranking["horas"]).tolist())
    assert not ranking["evidencia_baja"].any()
    monkeypatch.setitem(an.PARAMETROS, "observaciones_minimas_evidencia", 1000)
    assert an.ranking_municipios_brecha(tablas_gold["fact_prestacion"], tablas_gold["dim_municipio"])["evidencia_baja"].all()


def test_localidades_con_menos_horas_exige_un_minimo_de_meses(tablas_gold):
    fact, dim = tablas_gold["fact_prestacion"], tablas_gold["dim_localidad"]
    todas = an.localidades_con_menos_horas(fact, dim, cuantas=10, meses_minimos=1)
    assert todas["horas"].is_monotonic_increasing and "EL_ROSARIO" in todas.iloc[0]["clave_localidad"]
    exigentes = an.localidades_con_menos_horas(fact, dim, cuantas=10, meses_minimos=40)
    assert not exigentes["clave_localidad"].str.contains("EL_ROSARIO").any()  # solo reporta 32 meses
    assert (exigentes["meses"] >= 40).all()


def test_evolucion_departamentos_completa_los_meses_y_calcula_el_promedio_movil(tablas_gold):
    evo = an.evolucion_departamentos(tablas_gold["ind_horas_servicio_departamento"], ventana_movil=3)
    cauca = evo[evo["id_departamento"] == "19"].reset_index(drop=True)
    assert len(cauca) == len(MESES) and cauca["periodo"].is_monotonic_increasing
    assert cauca.loc[5, "horas_movil"] == pytest.approx(cauca.loc[3:5, "horas"].mean())


def test_evolucion_region_promedia_todas_las_observaciones_del_mes(tablas_gold):
    fact = tablas_gold["fact_prestacion"]
    region = an.evolucion_region(fact)
    primer_mes = fact[fact["periodo"] == "2020-01-01"]["horas_servicio_promedio_dia"].astype(float).mean()
    assert region["horas"].iloc[0] == pytest.approx(primer_mes)


# ---------------------------------------------------------------------------
# Cambio por localidad y estacionalidad
# ---------------------------------------------------------------------------
def test_cambio_por_localidad_encuentra_la_mejora_de_puerto_merizalde(tablas_gold):
    cambio = an.cambio_por_localidad(tablas_gold["fact_prestacion"], tablas_gold["dim_localidad"])
    primero = cambio.iloc[0]
    assert "MERIZALDE" in primero["clave_localidad"] and primero["cambio"] == pytest.approx(15, abs=1.0)
    assert cambio["cambio"].is_monotonic_decreasing
    assert not cambio["clave_localidad"].str.contains("EL_ROSARIO").any()  # no tiene datos en 2020-2021: no se puede comparar
    assert (cambio["observaciones_antes"] >= an.PARAMETROS["observaciones_minimas_ventana"]).all()
    assert np.allclose(cambio["cambio"], cambio["horas_despues"] - cambio["horas_antes"])


def test_cambio_por_localidad_respeta_ventanas_y_minimo_de_observaciones(tablas_gold):
    fact, dim = tablas_gold["fact_prestacion"], tablas_gold["dim_localidad"]
    estricto = an.cambio_por_localidad(fact, dim, observaciones_minimas=24)  # exige las 24 observaciones de cada ventana
    assert not estricto["clave_localidad"].str.contains("GUAJUI").any()  # tiene meses sin reporte
    otras = an.cambio_por_localidad(fact, dim, ventana_inicial=(2020,), ventana_final=(2021,))
    assert abs(otras["cambio"].median()) < 1.0  # sin mejoras reales entre 2020 y 2021 en la mediana


def test_resumen_cambio_cuenta_mejoran_empeoran_y_se_mantienen():
    cambio = pd.DataFrame({"cambio": [10.0, 1.0, 0.2, -0.2, -1.0, -3.0]})
    resumen = an.resumen_cambio(cambio, remuestreos=200, semilla=1, umbral=0.5)
    assert (resumen["mejoran"], resumen["empeoran"], resumen["se_mantienen"]) == (2, 2, 2)
    assert resumen["mediana"] == pytest.approx(np.median([10, 1, 0.2, -0.2, -1, -3]))
    assert resumen["media"] == pytest.approx(np.mean([10, 1, 0.2, -0.2, -1, -3]))
    assert resumen["media_sin_las_dos_mayores_mejoras"] == pytest.approx(np.mean([0.2, -0.2, -1, -3]))
    assert resumen["mediana_inferior"] <= resumen["mediana"] <= resumen["mediana_superior"]


def test_resumen_cambio_sin_localidades_no_falla():
    assert an.resumen_cambio(pd.DataFrame({"cambio": []}))["localidades"] == 0


def test_media_con_intervalo_es_reproducible_y_contiene_la_media(tablas_gold):
    desviacion = an.desviacion_respecto_a_la_localidad_anio(tablas_gold["fact_prestacion"])
    a = an.media_con_intervalo(desviacion, "mes", remuestreos=300, semilla=5)
    b = an.media_con_intervalo(desviacion, "mes", remuestreos=300, semilla=5)
    pd.testing.assert_frame_equal(a, b)
    assert ((a["inferior"] <= a["media"]) & (a["media"] <= a["superior"])).all()
    c = an.media_con_intervalo(desviacion, "mes", remuestreos=300, semilla=6)
    assert not a["inferior"].equals(c["inferior"])  # otra semilla, otro remuestreo


def test_media_con_intervalo_colapsa_si_todas_las_localidades_son_iguales():
    datos = pd.DataFrame({"clave_localidad": list("AABBCC"), "anio": [2020, 2021] * 3, "desviacion": [1.0] * 6})
    resultado = an.media_con_intervalo(datos, "anio", remuestreos=100, semilla=1)
    assert resultado["inferior"].tolist() == [1.0, 1.0] and resultado["superior"].tolist() == [1.0, 1.0]


def test_la_desviacion_respecto_a_la_localidad_anio_promedia_cero_en_cada_localidad_anio(tablas_gold):
    desviacion = an.desviacion_respecto_a_la_localidad_anio(tablas_gold["fact_prestacion"], meses_minimos=6)
    medias = desviacion.groupby(["clave_localidad", "anio"])["desviacion"].mean()
    assert np.allclose(medias.to_numpy(), 0.0, atol=1e-9)
    conteos = desviacion.groupby(["clave_localidad", "anio"])["horas"].size()
    assert (conteos >= 6).all()


def test_la_estacionalidad_recupera_diciembre_alto_y_enero_bajo(tablas_gold):
    desviacion = an.desviacion_respecto_a_la_localidad_anio(tablas_gold["fact_prestacion"])
    perfil = an.media_con_intervalo(desviacion, "mes", remuestreos=300, semilla=3).set_index("mes")
    assert perfil["media"].idxmax() == 12 and perfil["media"].idxmin() == 1
    assert perfil.loc[12, "inferior"] > 0 and perfil.loc[1, "superior"] < 0  # los intervalos no incluyen 0


# ---------------------------------------------------------------------------
# PQR y operación diaria
# ---------------------------------------------------------------------------
def test_pqr_frente_a_horas_descarta_los_semestres_sin_cobertura_y_cuenta_ceros(tablas_gold):
    original = tablas_gold["ind_pqr_vs_horas_municipio"]
    assert (original["estado_pqr"] == "sin dato vigente").any()  # el mundo tiene semestres fuera de la cobertura de PQR
    comparables = an.pqr_frente_a_horas(original)
    assert (comparables["estado_pqr"] != "sin dato vigente").all()
    assert comparables["casos"].notna().all() and (comparables["casos"] >= 0).all()
    assert len(comparables) == (original["estado_pqr"] != "sin dato vigente").sum()


def test_correlacion_pqr_horas_con_menos_de_tres_pares_devuelve_nulo():
    resultado = an.correlacion_pqr_horas(pd.DataFrame({"casos": [1.0, 2.0], "horas": [5.0, 6.0]}))
    assert np.isnan(resultado["rho"]) and resultado["pares"] == 2


def test_pqr_por_municipio_ordena_por_casos_y_respeta_el_limite(tablas_gold):
    top = an.pqr_por_municipio(tablas_gold["ind_pqr_empresa_municipio"], cuantos=2)
    assert len(top) == 2 and top["n_pqr"].is_monotonic_decreasing
    assert top.iloc[0]["id_municipio"] == "52835"  # Tumaco: 5 casos al mes en el mundo de prueba


def test_contexto_operacion_diaria_resume_flota_y_horas(silver_operacion):
    contexto = an.contexto_operacion_diaria(silver_operacion)
    assert contexto["registros"] == len(silver_operacion) and contexto["generadores"] == silver_operacion["serie_generador"].nunique()
    assert contexto["proporcion_calculado"] == 1.0 and contexto["proporcion_4_5_u_8_horas"] == 1.0  # todo el mundo declara 5 h calculadas
    assert contexto["marcas"].iloc[0]["marca"] == "LISTER"
    assert contexto["distribucion_horas"].set_index("horas")["proporcion"].loc[5] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Hallazgos y tablas de apoyo
# ---------------------------------------------------------------------------
def test_los_hallazgos_traen_las_cifras_clave_y_se_pueden_escribir_como_json(tablas_gold, silver_operacion):
    hallazgos = an.calcular_hallazgos(tablas_gold, silver_operacion)
    assert hallazgos["alcance"]["localidades"] == 10 and hallazgos["alcance"]["periodo_hasta"] == "2025-12"
    assert hallazgos["energia"]["localidad_principal"] == "Puerto Leguizamo" and hallazgos["energia"]["participacion_principal_pct"] > 50
    assert hallazgos["cambio_por_localidad"]["mayores_mejoras"][0]["localidad"] == "Puerto Merizalde"
    assert hallazgos["estacionalidad"]["mes_mas_alto"] == 12 and hallazgos["estacionalidad"]["mes_mas_bajo"] == 1
    assert hallazgos["operacion_diaria"]["pct_4_5_u_8_horas"] == pytest.approx(100.0)
    assert {f["fuente"] for f in hallazgos["fuentes"]} == {"prestacion", "operacion_diaria", "pqr"}
    texto = json.dumps(run_eda._nativo(hallazgos), ensure_ascii=False)
    assert "NaN" not in texto and json.loads(texto)["alcance"]["observaciones"] == hallazgos["alcance"]["observaciones"]


def test_los_hallazgos_sin_operacion_diaria_omiten_esa_seccion(tablas_gold):
    assert "operacion_diaria" not in an.calcular_hallazgos(tablas_gold, None)


def test_las_cifras_de_los_hallazgos_coinciden_con_las_de_las_figuras(tablas_gold, dibujos):
    hallazgos = an.calcular_hallazgos(tablas_gold)
    totales = an.cobertura_mensual(tablas_gold["fact_prestacion"]).sum(axis=1)
    titulo = dibujos["fig02_cobertura_mensual"].texts[0].get_text()
    assert f"entre {totales.min()} y {totales.max()}" in titulo
    assert hallazgos["cobertura"]["minimo"] == totales.min() and hallazgos["cobertura"]["maximo"] == totales.max()


def test_las_tablas_de_apoyo_son_la_version_en_tabla_de_las_figuras(tablas_gold):
    tablas = an.tablas_de_apoyo(tablas_gold)
    assert {"cambio_por_localidad", "estacionalidad", "ranking_municipios_brecha", "operadores", "estado_reciente"} <= set(tablas)
    assert len(tablas["estacionalidad"]) == 12 and "nombre_corto" in tablas["operadores"].columns
    assert tablas["perfil_fact_prestacion"]["columna"].tolist() == list(tablas_gold["fact_prestacion"].columns)
    assert (tablas["cobertura_mensual"]["total"] == tablas["cobertura_mensual"][["19", "52", "76", "86"]].sum(axis=1)).all()


def test_perfil_tabla_reporta_nulos_y_resumen_de_cinco_numeros():
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0, None], "b": ["x", "y", "y", None]})
    perfil = an.perfil_tabla(df).set_index("columna")
    assert perfil.loc["a", "nulos"] == 1 and perfil.loc["a", "pct_nulos"] == 25.0 and perfil.loc["a", "mediana"] == 2.0
    assert perfil.loc["b", "distintos"] == 2 and pd.isna(perfil.loc["b", "mediana"])


# ---------------------------------------------------------------------------
# Figuras
# ---------------------------------------------------------------------------
def test_el_registro_tiene_las_16_figuras_numeradas_y_cada_una_con_su_seccion():
    nombres = list(charts.FIGURAS)
    assert len(nombres) == 16 and nombres == sorted(nombres)
    assert all(nombre.startswith(f"fig{posicion:02d}_") for posicion, nombre in enumerate(nombres, start=1))
    assert all(figura.seccion for figura in charts.FIGURAS.values())
    assert [n for n, f in charts.FIGURAS.items() if f.requiere_operacion] == ["fig16_operacion_diaria"]


@pytest.mark.parametrize("nombre", list(charts.FIGURAS))
def test_cada_figura_se_construye_con_titulo_ejes_y_pie(nombre, dibujos):
    fig = dibujos[nombre]
    assert isinstance(fig, Figure) and len(fig.axes) >= 1
    textos = [t.get_text() for t in fig.texts]
    assert textos and len(textos[0]) > 20  # el título es un hallazgo, no un rótulo
    assert any(t.startswith("Fuente:") for t in textos), "el pie debe citar la fuente"


@pytest.mark.parametrize("nombre", list(charts.FIGURAS))
def test_cada_figura_se_guarda_como_png(nombre, dibujos, tmp_path):
    ruta = st.guardar(dibujos[nombre], tmp_path / "carpeta_nueva" / f"{nombre}.png", dpi=60)
    assert ruta.exists() and ruta.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n" and ruta.stat().st_size > 5_000


def test_los_titulos_de_las_figuras_salen_de_los_datos(dibujos, tablas_gold):
    titulo_estado = dibujos["fig07_estado_departamentos"].texts[0].get_text()
    regional = an.estado_reciente(tablas_gold["fact_prestacion"])
    horas_region = regional.loc[regional["codigo"] == "REGION", "horas"].iloc[0]
    assert st.num(horas_region, 1) in titulo_estado
    assert "Puerto Merizalde" in dibujos["fig10_cambio_localidades"].texts[0].get_text()
    assert "Diciembre" in dibujos["fig11_estacionalidad"].texts[0].get_text()


def test_la_figura_de_operadores_marca_la_evidencia_limitada_y_usa_nombres_cortos(dibujos):
    etiquetas = [t.get_text() for t in dibujos["fig12_operadores"].axes[0].get_yticklabels()]
    assert etiquetas and all(len(e) <= 48 for e in etiquetas)
    assert not any("S.A." in e or "E.S.P." in e for e in etiquetas)


def test_las_figuras_no_pintan_las_etiquetas_con_el_color_de_la_serie(dibujos):
    colores_serie = {st.AZUL, st.NARANJA, st.AQUA, st.AMARILLO}
    for nombre, fig in dibujos.items():
        for eje in fig.axes:
            for texto in eje.get_yticklabels() + eje.get_xticklabels():
                assert texto.get_color() not in colores_serie, f"{nombre}: etiqueta con color de serie"


# ---------------------------------------------------------------------------
# Orquestador del EDA
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def entorno_eda(tablas_gold, silver_operacion, tmp_path_factory):
    raiz = tmp_path_factory.mktemp("eda")
    carpeta_gold = raiz / "gold"
    carpeta_gold.mkdir()
    for nombre, tabla in tablas_gold.items():
        tabla.to_parquet(carpeta_gold / f"{nombre}.parquet", index=False)
    ruta_operacion = raiz / "operacion_diaria.parquet"
    silver_operacion.to_parquet(ruta_operacion, index=False)
    return {"gold": carpeta_gold, "operacion": ruta_operacion, "raiz": raiz}


@pytest.fixture(scope="module")
def corrida_eda(entorno_eda):
    salida = entorno_eda["raiz"] / "salida"
    resumen = run_eda.ejecutar_eda(ruta_gold=entorno_eda["gold"], ruta_salida=salida, ruta_operacion=entorno_eda["operacion"])
    return salida, resumen


def test_ejecutar_eda_escribe_figuras_tablas_hallazgos_e_indice(corrida_eda):
    salida, resumen = corrida_eda
    figuras = sorted(p.name for p in (salida / "figuras").glob("*.png"))
    assert figuras == [f"{nombre}.png" for nombre in charts.FIGURAS]
    assert len(list((salida / "tablas").glob("*.csv"))) == len(resumen["tablas"]) == 12
    hallazgos = json.loads((salida / "hallazgos.json").read_text(encoding="utf-8"))
    assert hallazgos["alcance"]["localidades"] == 10
    indice = (salida / "INDICE.md").read_text(encoding="utf-8")
    assert all(f"[{nombre}](figuras/{nombre}.png)" in indice for nombre in charts.FIGURAS)
    assert "P1 a P6" in indice and "Tablas de apoyo" in indice


def test_las_tablas_de_apoyo_se_escriben_con_bom_y_conservan_las_tildes(corrida_eda):
    salida, _ = corrida_eda
    ruta = salida / "tablas" / "operadores.csv"
    assert ruta.read_bytes().startswith(b"\xef\xbb\xbf")  # utf-8 con BOM: abre bien en Excel
    tabla = pd.read_csv(ruta, encoding="utf-8-sig")
    assert "Electrificadora del Pacífico" in set(tabla["nombre_corto"])


def test_ejecutar_eda_es_idempotente_dos_corridas_dan_los_mismos_archivos(corrida_eda, entorno_eda):
    salida, _ = corrida_eda
    segunda = entorno_eda["raiz"] / "salida_2"
    run_eda.ejecutar_eda(ruta_gold=entorno_eda["gold"], ruta_salida=segunda, ruta_operacion=entorno_eda["operacion"])
    archivos = sorted(p.relative_to(salida) for p in salida.rglob("*") if p.is_file())
    assert archivos == sorted(p.relative_to(segunda) for p in segunda.rglob("*") if p.is_file())
    for relativo in archivos:
        assert (salida / relativo).read_bytes() == (segunda / relativo).read_bytes(), f"{relativo} cambió entre corridas"


def test_ejecutar_eda_sin_silver_de_operacion_omite_solo_esa_figura(entorno_eda, tmp_path):
    resumen = run_eda.ejecutar_eda(ruta_gold=entorno_eda["gold"], ruta_salida=tmp_path, ruta_operacion=tmp_path / "no_existe.parquet")
    assert "fig16_operacion_diaria" not in resumen["figuras"] and len(resumen["figuras"]) == 15
    assert "operacion_diaria" not in json.loads((tmp_path / "hallazgos.json").read_text(encoding="utf-8"))


def test_ejecutar_eda_con_un_filtro_genera_solo_esas_figuras_y_no_reescribe_el_indice(entorno_eda, tmp_path):
    resumen = run_eda.ejecutar_eda(ruta_gold=entorno_eda["gold"], ruta_salida=tmp_path, ruta_operacion=entorno_eda["operacion"], solo=["fig07", "fig10"])
    assert sorted(resumen["figuras"]) == ["fig07_estado_departamentos", "fig10_cambio_localidades"]
    assert not (tmp_path / "INDICE.md").exists()


def test_ejecutar_eda_sin_gold_falla_con_un_error_que_dice_que_hacer(tmp_path):
    with pytest.raises(run_eda.ErrorEDA, match="python main.py --etapa gold"):
        run_eda.ejecutar_eda(ruta_gold=tmp_path / "vacio", ruta_salida=tmp_path / "salida")


def test_una_figura_que_falla_no_impide_las_demas_pero_se_informa_como_error(entorno_eda, tmp_path, monkeypatch):
    def rota(g):
        raise ValueError("datos inesperados")

    monkeypatch.setitem(charts.FIGURAS, "fig05_concentracion_energia", charts.FiguraEDA(rota, False, "Preanálisis"))
    with pytest.raises(run_eda.ErrorEDA, match="fig05_concentracion_energia.*datos inesperados"):
        run_eda.ejecutar_eda(ruta_gold=entorno_eda["gold"], ruta_salida=tmp_path, ruta_operacion=entorno_eda["operacion"])
    assert (tmp_path / "figuras" / "fig06_correlaciones.png").exists()  # las demás se generaron
    assert not (tmp_path / "figuras" / "fig05_concentracion_energia.png").exists()


def test_la_etapa_eda_del_orquestador_resume_lo_que_genero(monkeypatch):
    monkeypatch.setattr(run_eda, "ejecutar_eda", lambda: {"figuras": {"a": {}, "b": {}}, "tablas": ["t1", "t2", "t3"], "hallazgos": "x"})
    assert orquestador.etapa_eda() == "2 figuras y 3 tablas en docs/eda"


def test_si_el_eda_falla_el_orquestador_lo_cuenta_como_error_controlado(monkeypatch):
    reiniciar_errores_controlados()

    def falla(**_):
        raise run_eda.ErrorEDA("figuras con error: {'fig01': 'x'}")

    monkeypatch.setitem(orquestador.FUNCIONES_ETAPA, "eda", falla)
    assert orquestador.main(["--etapa", "eda"]) == 1
    reiniciar_errores_controlados()


# ---------------------------------------------------------------------------
# Reproducibilidad de los PNG
# ---------------------------------------------------------------------------
def test_fijar_layout_redondea_las_posiciones_de_los_ejes_y_congela_el_layout():
    from matplotlib.layout_engine import ConstrainedLayoutEngine

    fig = st.nuevo_lienzo("Un hallazgo", "Qué se mide", "Fuente: prueba")
    fig.subplots(1, 2)
    assert isinstance(fig.get_layout_engine(), ConstrainedLayoutEngine)
    st.fijar_layout(fig)
    assert not isinstance(fig.get_layout_engine(), ConstrainedLayoutEngine)
    for eje in fig.axes:
        assert all(round(v, 4) == v for v in eje.get_position().bounds)


@pytest.mark.parametrize("nombre", ["fig03_mapa_reporte_localidades", "fig09_evolucion_departamentos", "fig16_operacion_diaria"])
def test_la_misma_figura_sale_identica_byte_a_byte_en_repeticiones(nombre, tablas_gold, silver_operacion, tmp_path):
    """Las figuras con más layout automático (barra de color, subgráficos, tres paneles) no deben variar ni un píxel."""
    figura = charts.FIGURAS[nombre]
    contenidos = set()
    for repeticion in range(4):
        with st.tema():
            fig = figura.funcion(tablas_gold, silver_operacion) if figura.requiere_operacion else figura.funcion(tablas_gold)
        contenidos.add(st.guardar(fig, tmp_path / f"{nombre}_{repeticion}.png", dpi=80).read_bytes())
    assert len(contenidos) == 1


# ---------------------------------------------------------------------------
# Modo diapositiva (figuras de la presentación)
# ---------------------------------------------------------------------------
def test_en_modo_diapositiva_la_figura_no_lleva_titulo_ni_pie_pero_los_conserva_en_metadatos():
    assert not st.es_modo_diapositiva()
    with st.modo_diapositiva():
        assert st.es_modo_diapositiva()
        fig = st.nuevo_lienzo("Un hallazgo", "Qué se mide", "Fuente: prueba", ancho=12, alto=6.75)
    assert not st.es_modo_diapositiva()  # el modo vuelve a su valor al salir del contexto
    assert fig.texts == [] and fig.get_figwidth() == st.ANCHO_DIAPOSITIVA_IN
    assert fig.metadatos_zni == {"titulo": "Un hallazgo", "subtitulo": "Qué se mide", "pie": "Fuente: prueba"}
    informe = st.nuevo_lienzo("Un hallazgo", "Qué se mide", "Fuente: prueba", ancho=12, alto=6.75)
    assert informe.get_figwidth() == 12 and len(informe.texts) == 3 and informe.metadatos_zni["titulo"] == "Un hallazgo"


def test_el_modo_diapositiva_se_restablece_aunque_la_figura_falle():
    with pytest.raises(ValueError):
        with st.modo_diapositiva():
            raise ValueError("fallo dentro del contexto")
    assert not st.es_modo_diapositiva()


def test_las_figuras_de_diapositiva_dan_mas_alto_al_grafico_que_las_del_informe(tablas_gold):
    """Sin encabezado ni pie y con el lienzo más angosto, la misma figura ocupa una proporción más cuadrada."""
    with st.tema():
        informe = charts.fig_brechas_municipios(tablas_gold)
        with st.modo_diapositiva():
            diapositiva = charts.fig_brechas_municipios(tablas_gold)
    assert diapositiva.get_figwidth() < informe.get_figwidth()
    assert diapositiva.metadatos_zni["titulo"] == informe.metadatos_zni["titulo"]  # mismos hallazgos
    assert diapositiva.axes[0].get_position().height > informe.axes[0].get_position().height or diapositiva.get_figheight() < informe.get_figheight()


def test_generar_figuras_diapositiva_escribe_solo_las_configuradas_con_su_tamano_y_titulo(entorno_eda, tmp_path):
    generadas = run_eda.generar_figuras_diapositiva(ruta_gold=entorno_eda["gold"], ruta_salida=tmp_path, ruta_operacion=entorno_eda["operacion"])
    assert list(generadas) == an.PARAMETROS["figuras_diapositiva"]
    for nombre, datos in generadas.items():
        ruta = Path(datos["ruta"])
        assert ruta == tmp_path / "figuras" / f"{nombre}.png" and ruta.read_bytes()[:4] == b"\x89PNG"
        assert datos["ancho_px"] == int(round(st.ANCHO_DIAPOSITIVA_IN * an.PARAMETROS["dpi"])) and datos["alto_px"] > 300
        assert len(datos["titulo"]) > 20 and datos["pie"].startswith("Fuente:")


def test_generar_figuras_diapositiva_sin_silver_de_operacion_omite_solo_esa_figura(entorno_eda, tmp_path):
    generadas = run_eda.generar_figuras_diapositiva(ruta_gold=entorno_eda["gold"], ruta_salida=tmp_path, ruta_operacion=tmp_path / "no_existe.parquet")
    assert "fig16_operacion_diaria" not in generadas and len(generadas) == len(an.PARAMETROS["figuras_diapositiva"]) - 1


def test_generar_figuras_diapositiva_sin_gold_falla_con_un_error_que_dice_que_hacer(tmp_path):
    with pytest.raises(run_eda.ErrorEDA, match="python main.py --etapa gold"):
        run_eda.generar_figuras_diapositiva(ruta_gold=tmp_path / "vacio", ruta_salida=tmp_path / "salida")


def test_todas_las_figuras_configuradas_para_diapositiva_existen_en_el_registro():
    assert set(an.PARAMETROS["figuras_diapositiva"]) <= set(charts.FIGURAS)


# ---------------------------------------------------------------------------
# Calibración del intervalo de confianza y serialización de hallazgos
# ---------------------------------------------------------------------------
def test_el_intervalo_del_95_por_ciento_tiene_el_ancho_que_predice_la_teoria():
    """40 localidades con una observación cada una (0 a 39): el error estándar de la media es std/raiz(40) ~ 1,82,
    así que la mitad del intervalo del 95 % mide ~ 1,96 x 1,82 = 3,6 (y 3,0 si el nivel fuera 90 %)."""
    datos = pd.DataFrame({"clave_localidad": [f"L{i:02d}" for i in range(40)], "anio": 1, "desviacion": np.arange(40, dtype=float)})
    mitades = {}
    for nivel in (0.90, 0.95, 0.99):
        fila = an.media_con_intervalo(datos, "anio", remuestreos=4000, semilla=11, nivel=nivel).iloc[0]
        assert fila["media"] == pytest.approx(19.5)
        mitades[nivel] = (fila["superior"] - fila["inferior"]) / 2
    assert 3.4 < mitades[0.95] < 3.8
    assert mitades[0.90] < mitades[0.95] < mitades[0.99]


def test_nativo_convierte_numpy_y_pandas_a_json_y_escribe_los_nulos_como_null():
    convertido = run_eda._nativo(
        {"nulo": float("nan"), "decimal": np.float64(1.23456), "entero": np.int64(3), "fecha": pd.Timestamp("2026-01-05"), "lista": [np.bool_(True), np.int32(2)], "texto": "Magüí"}
    )
    assert convertido == {"nulo": None, "decimal": 1.2346, "entero": 3, "fecha": "2026-01-05", "lista": [True, 2], "texto": "Magüí"}
    assert "NaN" not in json.dumps(convertido) and type(convertido["lista"][0]) is bool


# ---------------------------------------------------------------------------
# Entregable: el notebook
# ---------------------------------------------------------------------------
def test_el_notebook_se_entrega_ejecutado_sin_errores_y_con_todas_las_figuras():
    """Es un JSON: se comprueba sin ejecutarlo (para volver a ejecutarlo: ver la primera celda del cuaderno)."""
    cuaderno = json.loads((RAIZ / "notebooks" / "01_eda_zni.ipynb").read_text(encoding="utf-8"))
    celdas_codigo = [c for c in cuaderno["cells"] if c["cell_type"] == "code"]
    salidas = [salida for celda in celdas_codigo for salida in celda.get("outputs", [])]
    assert celdas_codigo and all(c.get("execution_count") for c in celdas_codigo), "hay celdas sin ejecutar"
    assert not [s for s in salidas if s["output_type"] == "error"], "hay celdas con error"
    imagenes = [s for s in salidas if s["output_type"] in ("display_data", "execute_result") and "image/png" in s.get("data", {})]
    assert len(imagenes) >= len(charts.FIGURAS), f"se esperaban {len(charts.FIGURAS)} figuras y hay {len(imagenes)}"
    lecturas = ["".join(s["data"]["text/markdown"]) for s in salidas if "text/markdown" in s.get("data", {})]  # nbformat guarda el texto por líneas
    assert lecturas and not [x for x in lecturas if re.search(r"[{}]|\bnan\b|s\. d\.", x)], "una lectura quedó con una cifra sin resolver"
