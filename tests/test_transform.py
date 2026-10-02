"""Pruebas de las transformaciones, sin red y con fixtures pequeñas:

  - limpieza silver (clean_excel): normalización DANE, deduplicación, filtro por departamentos,
    mes -> semestre, reglas aplicadas;
  - modelo gold (gold_transformations): frescura, es_comparable, validación de medidas, pruebas
    de calidad antes de cada unión, KPI y reproducibilidad;
  - helpers de la carga a PostgreSQL (load_database) que no necesitan servidor;
  - el orquestador main.py y su manejo de errores controlados.

Los datos de prueba son un mini-mundo sintético que pasa por los mismos limpiadores reales.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import main as orquestador  # noqa: E402
from src import obtener_errores_controlados, registrar_error_controlado, reiniciar_errores_controlados  # noqa: E402
from src.load import load_database as carga  # noqa: E402
from src.transform import clean_excel as limpieza  # noqa: E402
from src.transform import gold_transformations as gold  # noqa: E402

CARGA = pd.Timestamp("2026-09-30 12:00:00", tz="UTC")
PORTAL = pd.Timestamp("2026-03-13 14:42:17", tz="UTC")
IDS_FUENTE = {"prestacion": "3ebi-d83g", "operacion_diaria": "qwe5-ycap", "pqr": "5wua-nr2d"}


def _con_trazabilidad(df: pd.DataFrame, fuente: str) -> pd.DataFrame:
    df = df.copy()
    df["_fuente_id"] = IDS_FUENTE[fuente]
    df["_fecha_carga"] = CARGA
    df["_fecha_corte_fuente"] = PORTAL
    df["_lote_id"] = "lote-prueba"
    return df


# ---------------------------------------------------------------------------
# Datos crudos (bronze) sintéticos
# ---------------------------------------------------------------------------
def _fila_prestacion(id_dpto, id_mpio, id_localidad, localidad, anio, mes, energia="5000", horas="9.5", potencia="40"):
    return {
        "id_dpto": id_dpto, "dpto": "DPTO", "id_mpio": id_mpio, "mpio": "MPIO", "id_localidad": id_localidad,
        "localidad": localidad, "anio": str(anio), "mes": str(mes), "energia_activa": energia, "energia_reactiva": "1000",
        "potencia_maxima": potencia, "dia_demanda_maxima": "lunes", "fecha_demanda_maxima": f"{anio}-{mes:02d}-10T10:00:00.000",
        "prom_diario_horas": horas,
    }


MESES_PRESTACION = [(2021, m) for m in range(7, 13)] + [(2025, 12), (2026, 1)]


def bronce_prestacion() -> pd.DataFrame:
    """3 localidades en alcance (2 comparten el código DANE 19318008) + 2 fuera de alcance, en 8 meses.
    En 2025-12 y 2026-01 las horas y la potencia vienen con el cambio de formato de la fuente."""
    filas = []
    for anio, mes in MESES_PRESTACION:
        escalado = anio >= 2025
        horas, potencia = ("776", "473904") if escalado else ("9.5", "40")
        sin_servicio = (anio, mes) == (2026, 1)
        filas += [
            _fila_prestacion("19", "19318", "19318008", "LIMONES (GUAPI - CAUCA)", anio, mes, horas=horas, potencia=potencia),
            _fila_prestacion("19", "19318", "19318008", "SAN ANTONIO DE GUAJUI (GUAPI - CAUCA)", anio, mes, horas=horas, potencia=potencia),
            _fila_prestacion(
                "52", "52835", "52835055", "BOCAS DE CURAY (TUMACO - NARIÑO)", anio, mes,
                energia="0" if sin_servicio else "5000", horas="0" if sin_servicio else horas, potencia="0" if sin_servicio else potencia,
            ),
            _fila_prestacion("91", "91001", "91001000", "LETICIA (LETICIA - AMAZONAS)", anio, mes),  # fuera de alcance
            _fila_prestacion("5", "5873", "5873001", "VEGAEZ (VIGÍA DEL FUERTE - ANTIOQUIA)", anio, mes),  # fuera de alcance, sin ceros
        ]
    filas[5]["id_dpto"] = "00"  # id_dpto inconsistente con id_mpio (caso real de la fuente)
    filas.append(dict(filas[2]))  # fila exactamente duplicada
    return _con_trazabilidad(pd.DataFrame(filas), "prestacion")


def _fila_operacion(codigo, fecha, generador, empresa, operador, energia, localidad="LIMONES"):
    return {
        "serie_generador": generador, "dane_nom_poblad": localidad, "energia_generada": energia, "identificador_empresa": empresa,
        "ano": fecha[:4], "periodo": str(int(fecha[5:7])), "marca": "X", "fecha": f"{fecha}T00:00:00.000", "dane_nom_dpto": "CAUCA",
        "nombre_localidad": localidad, "dane_nom_mpio": "GUAPI", "horometro": "100", "codigo_localidad": codigo,
        "capacidad_generacion": "50", "tipo_medida": "MEDIDO", "nombre": operador, "tiempo_servicio": "8",
    }


def bronce_operacion() -> pd.DataFrame:
    """Localidad enlazable (centro poblado 008) con 2 generadores y, en agosto, 2 operadores; dos
    códigos sin centro poblado (000) que solo se relacionan por municipio; uno fuera de alcance."""
    filas = [
        _fila_operacion("1931800800001", "2021-07-05", "G1", "1892", "EMPRESA GUAPI", "100"),
        _fila_operacion("1931800800001", "2021-07-05", "G2", "1892", "EMPRESA GUAPI", "50"),
        _fila_operacion("1931800800001", "2021-07-06", "G1", "1892", "EMPRESA GUAPI", "100"),
        _fila_operacion("1931800800001", "2021-08-05", "G1", "1892", "EMPRESA GUAPI", "100"),
        _fila_operacion("1931800800001", "2021-08-05", "G3", "9999", "OTRA EMPRESA", "10"),
        _fila_operacion("1931800000002", "2021-07-05", "G1", "1892", "EMPRESA GUAPI", "30", "OTRA VEREDA"),
        _fila_operacion("5283500000001", "2021-07-05", "G1", "520", "CENTRALES NARIÑO", "70", "CHORRERA"),
        _fila_operacion("9100100000001", "2021-07-05", "G1", "77", "AMAZONAS SA", "10", "LETICIA"),
    ]
    return _con_trazabilidad(pd.DataFrame(filas), "operacion_diaria")


def _fila_pqr(depto, mpio, empresa, nombre_empresa, anio, periodo):
    radicado = f"{anio}-{periodo:02d}-15T00:00:00.000"
    respondido = f"{anio}-{periodo:02d}-17T00:00:00.000" if periodo % 2 == 0 else None
    return {
        "identificador_empresa": empresa, "are_esp_nombre": nombre_empresa, "car_carg_ano": str(anio), "car_carg_periodo": str(periodo),
        "car_t1554_dane_depto": depto, "dane_nom_dpto": "DPTO", "car_t1554_dane_mpio": mpio, "dane_nom_mpio": "MPIO",
        "rad_recibido": f"{empresa}{depto}{mpio}{periodo}", "rad_fecha": radicado, "respuesta_fecha": respondido,
        "notifica_fecha": respondido, "fecha_traslado": None,
    }


def bronce_pqr() -> pd.DataFrame:
    """Un caso por mes (jul-dic 2021) en 3 municipios en alcance (mpio '1' llega sin ceros) y 1 fuera de alcance."""
    filas = []
    for periodo in range(7, 13):
        filas += [
            _fila_pqr("19", "318", "6026", "GAS A S.A. ESP", 2021, periodo),
            _fila_pqr("52", "835", "6026", "GAS A S.A. ESP", 2021, periodo),
            _fila_pqr("19", "1", "1604", "GAS B SAS ESP", 2021, periodo),
            _fila_pqr("68", "895", "6026", "GAS A S.A. ESP", 2021, periodo),
        ]
    return _con_trazabilidad(pd.DataFrame(filas), "pqr")


@pytest.fixture(scope="module")
def silver():
    return {
        "prestacion": limpieza.limpiar_prestacion(bronce_prestacion()),
        "operacion_diaria": limpieza.limpiar_operacion_diaria(bronce_operacion()),
        "pqr": limpieza.limpiar_pqr(bronce_pqr()),
    }


@pytest.fixture(scope="module")
def resultado_gold(silver):
    return gold.construir_tablas(silver)


# ---------------------------------------------------------------------------
# Silver: normalización DANE
# ---------------------------------------------------------------------------
def test_normalizar_codigo_dane_rellena_ceros_y_marca_que_filas_cambiaron():
    normalizado, cambio = limpieza.normalizar_codigo_dane(pd.Series(["5873", "05873", "76001", "5"]), 5)
    assert normalizado.tolist() == ["05873", "05873", "76001", "00005"]
    assert cambio.tolist() == [True, False, False, True]


def test_normalizar_codigo_dane_no_toca_nulos_ni_valores_no_numericos():
    normalizado, cambio = limpieza.normalizar_codigo_dane(pd.Series(["ABC12", None, " 76001 "]), 5)
    assert normalizado[0] == "ABC12" and pd.isna(normalizado[1]) and normalizado[2] == "76001"
    assert cambio.tolist() == [False, False, False]  # recortar espacios no cuenta como normalizar el código


@pytest.mark.parametrize("original, esperado", [
    ("LIMONES (GUAPI - CAUCA)", "LIMONES"),
    ("NOANAMITO (LÓPEZ (MICAY) - CAUCA)", "NOANAMITO"),                       # paréntesis anidado del municipio
    ("PUEBLO NUEVO (TABLÓN SALADO) (TUMACO - NARIÑO)", "PUEBLO NUEVO TABLON SALADO"),  # el paréntesis propio se conserva
    ("PAPAYAL 1(BUENAVENTURA - VALLE DEL CAUCA)", "PAPAYAL 1"),
    ("  san   juan  ", "SAN JUAN"),
])
def test_normalizar_nombre_localidad(original, esperado):
    assert limpieza.normalizar_nombre_localidad(pd.Series([original]))[0] == esperado


# ---------------------------------------------------------------------------
# Silver: filtro por departamentos y deduplicación
# ---------------------------------------------------------------------------
def test_filtrar_departamentos_conserva_solo_los_cuatro_del_alcance():
    df = pd.DataFrame({"id_mpio": ["76001", "19001", "52835", "86001", "91001", "05001", "11001"], "x": range(7)})
    resultado = limpieza.filtrar_departamentos(df, "id_mpio")
    assert sorted(resultado["id_mpio"]) == ["19001", "52835", "76001", "86001"]


def test_deduplicar_elimina_solo_filas_exactamente_iguales():
    df = pd.DataFrame({
        "llave": ["a", "a", "a", "b"], "valor": [1, 1, 2, 3],
        "_lote_id": ["l1", "l2", "l1", "l1"],  # la trazabilidad no cuenta para decidir si dos filas son iguales
        "_fuente_id": "f", "_fecha_carga": "t", "_fecha_corte_fuente": "t",
    })
    sin_duplicados, eliminadas = limpieza.remover_duplicados_exactos(df)
    assert eliminadas == 1
    assert sorted(zip(sin_duplicados["llave"], sin_duplicados["valor"])) == [("a", 1), ("a", 2), ("b", 3)]  # misma llave con otro valor se conserva


# ---------------------------------------------------------------------------
# Silver: las tres fuentes
# ---------------------------------------------------------------------------
def test_limpiar_prestacion_normaliza_tipifica_filtra_y_deduplica(silver):
    pr = silver["prestacion"]
    assert len(pr) == 24 and pr.attrs["estadisticas"] == {
        "filas_bronze": 41, "filas_fuera_de_alcance": 16, "duplicados_exactos_eliminados": 1, "filas_silver": 24,
    }
    assert set(pr["id_mpio"].str[:2]) == {"19", "52"}           # Antioquia (05) y Amazonas (91) quedaron fuera
    assert pr["id_localidad"].str.len().eq(8).all() and pr["id_mpio"].str.len().eq(5).all()
    assert (pr["id_dpto"] == pr["id_mpio"].str[:2]).all()        # el '00' se reparó
    assert str(pr["anio"].dtype) == "Int64" and pr["energia_activa"].dtype.kind in "iu"
    assert pd.api.types.is_datetime64_any_dtype(pr["fecha_demanda_maxima"])
    assert not pr.duplicated(["id_localidad", "localidad_nombre_normalizado", "anio", "mes"]).any()  # llave real única
    assert pr["localidad_nombre_normalizado"].isin(["LIMONES", "SAN ANTONIO DE GUAJUI", "BOCAS DE CURAY"]).all()


def test_las_reglas_aplicadas_nunca_quedan_vacias_y_marcan_los_cambios(silver):
    pr = silver["prestacion"]
    assert pr["_reglas_aplicadas"].map(len).min() >= 4
    assert all("deduplicacion_exacta" in reglas for reglas in pr["_reglas_aplicadas"])
    reparada = pr[pr["_reglas_aplicadas"].map(lambda r: "dane_departamento_corregido" in r)]
    assert len(reparada) == 1 and reparada.iloc[0]["id_dpto"] == "19"
    assert silver["operacion_diaria"]["_reglas_aplicadas"].map(len).min() >= 4
    assert silver["pqr"]["_reglas_aplicadas"].map(len).min() >= 5


def test_limpiar_operacion_deriva_el_municipio_y_tipifica(silver):
    op = silver["operacion_diaria"]
    assert len(op) == 7 and "9100100000001" not in set(op["codigo_localidad"])  # el de Amazonas queda fuera
    assert (op["id_mpio"] == op["codigo_localidad"].str[:5]).all()
    assert op["codigo_localidad"].str.len().eq(13).all()
    assert pd.api.types.is_datetime64_any_dtype(op["fecha"]) and pd.api.types.is_numeric_dtype(op["energia_generada"])
    assert pd.api.types.is_string_dtype(op["identificador_empresa"])
    assert not op.duplicated(["codigo_localidad", "fecha", "serie_generador"]).any()


def test_limpiar_pqr_compone_el_municipio_desde_departamento_y_consecutivo(silver):
    pq = silver["pqr"]
    assert len(pq) == 18 and set(pq["id_mpio"]) == {"19318", "52835", "19001"}  # '1' -> '001' -> 19001; el 68895 queda fuera
    assert pq["id_mpio"].str.len().eq(5).all()


@pytest.mark.parametrize("mes, semestre", [(1, 1), (3, 1), (6, 1), (7, 2), (9, 2), (12, 2)])
def test_mes_a_semestre_en_silver_de_pqr(mes, semestre):
    bronce = _con_trazabilidad(pd.DataFrame([_fila_pqr("76", "1", "1", "GAS", 2022, mes)]), "pqr")
    assert int(limpieza.limpiar_pqr(bronce)["semestre"].iloc[0]) == semestre


def test_mes_a_semestre_en_gold_cubre_los_doce_meses():
    assert [int(gold.mes_a_semestre(m)) for m in range(1, 13)] == [1] * 6 + [2] * 6


# ---------------------------------------------------------------------------
# Gold: frescura, cobertura y comparabilidad
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("ultimo, referencia, frecuencia, nominal, esperado", [
    ("2026-01", "2026-03-15", 1, "activa", "vigente"),           # 2 periodos de retraso: todavía vigente
    ("2026-01", "2026-04-01", 1, "activa", "desactualizada"),    # 3 periodos: más de 2
    ("2025-01", "2026-01-31", 6, "activa", "vigente"),           # semestral: 12 meses = 2 periodos
    ("2025-01", "2026-02-01", 6, "activa", "desactualizada"),    # 13 meses = 2.17 periodos
    ("2022-03", "2026-09-30", 6, "congelada", "congelada"),      # sin actualización nominal: siempre congelada
    ("2026-09", "2026-09-30", 1, "congelada", "congelada"),
])
def test_clasificar_frescura(ultimo, referencia, frecuencia, nominal, esperado):
    estado, _ = gold.clasificar_frescura(pd.Period(ultimo, "M"), pd.Timestamp(referencia), frecuencia, nominal)
    assert estado == esperado


def test_la_fecha_de_referencia_usa_la_hora_de_colombia_no_el_dia_utc():
    # 8:27 p. m. del 30-sep en Colombia ya es 01:27 del 1-oct en UTC: el día debe seguir siendo 30-sep.
    noche_en_colombia = pd.Timestamp("2026-10-01 01:27:31", tz="UTC")
    assert gold._a_fecha_naive(noche_en_colombia) == pd.Timestamp("2026-09-30")
    assert gold._a_fecha_naive(pd.Timestamp("2026-09-30 21:45:44", tz="UTC")) == pd.Timestamp("2026-09-30")


def test_semestres_completos_exige_los_seis_meses():
    meses = [pd.Period(f"2021-{m:02d}", "M") for m in range(7, 13)] + [pd.Period("2022-01", "M"), pd.Period("2022-02", "M")]
    assert gold.semestres_completos(meses) == frozenset({(2021, 2)})


def test_estado_de_las_fuentes_usa_la_cobertura_observada(resultado_gold):
    meta = resultado_gold.tablas["meta_fuentes"].set_index("fuente")
    assert meta.loc["prestacion", "estado_frescura"] == "desactualizada"
    assert meta.loc["operacion_diaria", "estado_frescura"] == "congelada"
    assert meta.loc["pqr", "estado_frescura"] == "congelada"
    assert meta.loc["operacion_diaria", "fecha_corte_fuente"] == pd.Timestamp("2021-08-31")
    assert meta.loc["prestacion", "periodos_retraso"] == 8.0  # ene-2026 -> sep-2026
    assert "no actualizado" in meta.loc["prestacion", "advertencia"] and "congelada" in meta.loc["pqr", "advertencia"]


def test_es_comparable_solo_en_los_periodos_que_todas_las_fuentes_cubren(resultado_gold):
    fp = resultado_gold.tablas["fact_prestacion"]
    periodo = fp["periodo"].dt.strftime("%Y-%m")
    assert set(periodo[fp["es_comparable_operador"]]) == {"2021-07", "2021-08"}
    assert set(periodo[fp["es_comparable_pqr"]]) == {f"2021-{m:02d}" for m in range(7, 13)}  # semestre 2021-2 completo
    assert set(periodo[fp["es_comparable"]]) == {"2021-07", "2021-08"}                        # la intersección
    assert len(fp) == 24 and int(fp["es_comparable"].sum()) == 6                              # los no comparables se marcan, no se descartan


# ---------------------------------------------------------------------------
# Gold: validación de medidas
# ---------------------------------------------------------------------------
def test_validar_horas_reescala_solo_lo_que_queda_en_rango():
    horas, reescaladas, invalidas = gold.validar_horas(pd.Series([9.5, 0, 24, 776, 2400, 3000, -1, np.nan]))
    assert horas.iloc[:5].tolist() == [9.5, 0.0, 24.0, 7.76, 24.0]
    assert reescaladas.tolist() == [False, False, False, True, True, False, False, False]
    assert invalidas.tolist() == [False, False, False, False, False, True, True, False]  # 3000/100 = 30 > 24; negativas
    assert np.isnan(horas.iloc[5]) and np.isnan(horas.iloc[6]) and np.isnan(horas.iloc[7])


def test_validar_horas_sin_reescalar_excluye_los_valores_fuera_de_rango():
    cfg = {**gold.PLAUSIBILIDAD, "reescalar_valores_fuera_de_rango": False}
    horas, reescaladas, invalidas = gold.validar_horas(pd.Series([776.0, 9.5]), cfg)
    assert np.isnan(horas.iloc[0]) and bool(invalidas.iloc[0]) and not reescaladas.any()


def test_validar_potencia_nunca_reescala_y_excluye_las_filas_con_cambio_de_formato():
    potencia, invalidas = gold.validar_potencia(
        pd.Series([40.0, 473904.0, 52.0, 20000.0, np.nan]), pd.Series([False, True, True, False, False]),
    )
    assert potencia.iloc[0] == 40.0
    assert np.isnan(potencia.iloc[1]) and np.isnan(potencia.iloc[2])  # 52 también: su fila cambió de formato, no es confiable
    assert np.isnan(potencia.iloc[3])                                   # por encima del máximo plausible
    assert invalidas.tolist() == [False, True, True, True, False]


# ---------------------------------------------------------------------------
# Gold: tablas
# ---------------------------------------------------------------------------
def test_dim_localidad_distingue_localidades_que_comparten_el_codigo_dane(resultado_gold):
    dl = resultado_gold.tablas["dim_localidad"].set_index("clave_localidad")
    assert sorted(dl.index) == ["19318008-LIMONES", "19318008-SAN_ANTONIO_DE_GUAJUI", "52835055-BOCAS_DE_CURAY"]
    assert bool(dl.loc["19318008-LIMONES", "codigo_compartido"]) and dl.loc["19318008-LIMONES", "n_entidades_mismo_codigo"] == 2
    assert not bool(dl.loc["52835055-BOCAS_DE_CURAY", "codigo_compartido"])
    assert dl.loc["19318008-LIMONES", "nombre_departamento"] == "CAUCA"


def test_fact_prestacion_marca_reescalados_y_servicio(resultado_gold):
    fp = resultado_gold.tablas["fact_prestacion"]
    assert int(fp["horas_reescaladas"].sum()) == 5 and int(fp["horas_invalidas"].sum()) == 0
    reescalada = fp[fp["horas_reescaladas"]].iloc[0]
    assert reescalada["horas_servicio_reportadas"] == 776.0 and reescalada["horas_servicio_promedio_dia"] == 7.76
    assert bool(reescalada["potencia_invalida"]) and pd.isna(reescalada["potencia_maxima"])
    assert int(fp["con_servicio"].sum()) == 23  # solo Bocas de Curay en 2026-01 tiene energía 0
    assert fp["horas_servicio_promedio_dia"].between(0, 24).all()
    assert fp["estado_frescura"].eq("desactualizada").all()


def test_union_prestacion_operador_asigna_el_operador_solo_donde_hay_enlace_y_cobertura(resultado_gold):
    fp = resultado_gold.tablas["fact_prestacion"]
    assert fp["estado_operador"].value_counts().to_dict() == {"sin dato vigente": 18, "con dato": 4, "sin enlace por codigo": 2}
    con_dato = fp[fp["estado_operador"] == "con dato"]
    assert set(con_dato["id_operador"]) == {"1892"} and set(con_dato["clave_localidad"].str.split("-").str[1]) == {"LIMONES", "SAN_ANTONIO_DE_GUAJUI"}
    agosto = con_dato[con_dato["periodo"] == pd.Timestamp("2021-08-01")]
    assert agosto["n_operadores_localidad_mes"].eq(2).all()  # dos operadores en agosto: gana el de mayor energía generada
    sin_enlace = fp[fp["estado_operador"] == "sin enlace por codigo"]
    assert set(sin_enlace["clave_localidad"]) == {"52835055-BOCAS_DE_CURAY"}  # el código de Tumaco no trae centro poblado


def test_puente_operador_localidad_tiene_vigencia_observada(resultado_gold):
    puente = resultado_gold.tablas["puente_operador_localidad"]
    assert len(puente) == 6                                   # 4 operador-código, 2 se repiten por las 2 localidades con el mismo código
    guapi = puente[(puente["codigo_localidad_operacion"] == "1931800800001") & (puente["id_operador"] == "1892")]
    assert guapi["vigente_desde"].eq(pd.Timestamp("2021-07-05")).all() and guapi["vigente_hasta"].eq(pd.Timestamp("2021-08-05")).all()
    assert guapi["dias_con_registro"].eq(3).all() and guapi["meses_con_registro"].eq(2).all()
    assert set(puente["nivel_enlace"]) == {"localidad", "municipio"}
    assert puente[puente["nivel_enlace"] == "municipio"]["clave_localidad"].isna().all()
    assert puente["estado_frescura"].eq("congelada").all()


def test_fact_pqr_agrega_antes_de_unir_y_conserva_todos_los_casos(resultado_gold, silver):
    fq = resultado_gold.tablas["fact_pqr"]
    assert int(fq["n_pqr"].sum()) == len(silver["pqr"]) == 18      # no se pierde ni se inventa ningún caso
    assert len(fq) == 3 and fq["n_pqr"].eq(6).all()
    assert set(fq["id_municipio"]) == {"19318", "52835", "19001"}
    assert fq["n_con_respuesta"].eq(3).all() and fq["pct_con_respuesta"].eq(50.0).all()
    assert fq["es_comparable"].all() and fq["estado_frescura"].eq("congelada").all()


def test_la_pqr_nunca_se_asigna_a_una_localidad(resultado_gold):
    for nombre, tabla in resultado_gold.tablas.items():
        if "pqr" in nombre and nombre != "fact_pqr":
            assert not any("localidad" in c and c != "n_localidades" for c in tabla.columns), nombre
    assert "n_pqr" not in resultado_gold.tablas["fact_prestacion"].columns


def test_indicador_pqr_vs_horas_distingue_sin_dato_de_sin_registro(resultado_gold):
    ind = resultado_gold.tablas["ind_pqr_vs_horas_municipio"]
    cubierto = ind[(ind["anio"] == 2021) & (ind["semestre"] == 2)]
    assert set(cubierto["estado_pqr"]) == {"con dato"} and cubierto["n_pqr_total"].eq(6).all() and cubierto["es_comparable"].all()
    fuera = ind[ind["anio"] >= 2025]
    assert set(fuera["estado_pqr"]) == {"sin dato vigente"} and fuera["n_pqr_total"].isna().all() and not fuera["es_comparable"].any()


def test_peor_desempeno_combinado_ordena_con_ranking_1_como_el_peor(resultado_gold):
    peor = resultado_gold.tablas["ind_peor_desempeno_municipio"].sort_values("ranking_peor_desempeno")
    assert peor["ranking_peor_desempeno"].tolist() == list(range(1, len(peor) + 1))
    assert peor["puntaje_combinado"].is_monotonic_decreasing
    assert np.allclose(peor["brecha_horas"], 24 - peor["horas_servicio_promedio"], atol=1e-3)


def test_todos_los_registros_gold_llevan_frescura_y_trazabilidad(resultado_gold):
    for nombre, tabla in resultado_gold.tablas.items():
        if nombre.startswith(gold.PREFIJOS_TABLAS_CON_TRAZABILIDAD):
            for columna in ("fecha_corte_fuente", "estado_frescura", "es_comparable", "fuentes_origen", "fecha_carga", "lote_id", "reglas_aplicadas"):
                assert columna in tabla.columns and tabla[columna].notna().all(), f"{nombre}.{columna}"
            assert tabla["reglas_aplicadas"].astype(str).ne("").all()


def test_las_reglas_que_escribe_el_pipeline_estan_documentadas_en_config(resultado_gold):
    usadas = {
        r for nombre, t in resultado_gold.tablas.items() if nombre.startswith(gold.PREFIJOS_TABLAS_CON_TRAZABILIDAD)
        for texto in t["reglas_aplicadas"].unique() for r in texto.split("; ")
    }
    assert usadas <= set(gold.CONFIG["reglas_negocio"])


def test_gold_es_reproducible_dos_construcciones_dan_las_mismas_huellas(silver, resultado_gold):
    otra = gold.construir_tablas(silver)
    assert {n: gold.hash_tabla(t) for n, t in resultado_gold.tablas.items()} == {n: gold.hash_tabla(t) for n, t in otra.tablas.items()}


def test_hash_tabla_detecta_cualquier_cambio():
    base = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    assert gold.hash_tabla(base) == gold.hash_tabla(base.copy())
    cambiada = base.copy()
    cambiada.loc[1, "b"] = "z"
    assert gold.hash_tabla(base) != gold.hash_tabla(cambiada)
    assert gold.hash_tabla(base) != gold.hash_tabla(base.rename(columns={"a": "c"}))


# ---------------------------------------------------------------------------
# Gold: pruebas de calidad ANTES de cada unión
# ---------------------------------------------------------------------------
def test_resultado_de_las_tres_uniones_con_datos_sinteticos(resultado_gold):
    por_union = {u["union"]: u for u in resultado_gold.resumen_uniones}
    assert por_union["prestacion_operacion_diaria"]["resultado_union"] == "implementada_con_tratamiento"  # 2 operadores en agosto
    assert por_union["prestacion_pqr"]["resultado_union"] == "implementada"                              # 1 empresa por municipio-semestre
    assert por_union["operacion_diaria_pqr"]["resultado_union"] == "solo_municipio"                      # 0% de empresas en común
    assert por_union["operacion_diaria_pqr"]["habilitada_por_empresa"] is False
    pruebas = resultado_gold.tablas["meta_uniones"]
    assert set(pruebas["nombre_union"]) == set(por_union) and {"unicidad_llave", "validez_dane", "identificador_empresa_comun"} <= set(pruebas["prueba"])


def _mini_evidencia(operadores_por_mes):
    filas = [("19318008", pd.Timestamp("2021-08-01"), str(op), 10.0) for op in operadores_por_mes]
    return pd.DataFrame(filas, columns=["id_localidad_enlace", "mes_inicio", "identificador_empresa", "energia_generada"])


def _mini_fact_base(duplicada=False):
    filas = [("19318008-A", "19318008", 2021, 8)] * (2 if duplicada else 1)
    return pd.DataFrame(filas, columns=["clave_localidad", "id_localidad", "anio", "mes"])


def _mini_operacion():
    return pd.DataFrame({"codigo_localidad": ["1931800800001"], "fecha": [pd.Timestamp("2021-08-05")], "serie_generador": ["G1"], "identificador_empresa": ["1"]})


def test_una_union_no_se_construye_si_falla_una_prueba_bloqueante():
    filas, resumen = gold.evaluar_union_prestacion_operador(
        _mini_fact_base(duplicada=True), _mini_operacion(), _mini_evidencia([1]), {"19318008"},
    )
    assert not resumen["habilitada"] and resumen["resultado_union"] == "no_implementada"
    assert any(f["prueba"] == "unicidad_llave" and f["bloqueante"] and not f["aprobado"] for f in filas)


def test_una_union_sin_ids_enlazables_no_se_construye():
    _, resumen = gold.evaluar_union_prestacion_operador(_mini_fact_base(), _mini_operacion(), _mini_evidencia([]), set())
    assert not resumen["habilitada"]


def test_cardinalidad_excedida_no_bloquea_pero_exige_tratamiento():
    _, con_dos = gold.evaluar_union_prestacion_operador(_mini_fact_base(), _mini_operacion(), _mini_evidencia([1, 2]), {"19318008"})
    _, con_uno = gold.evaluar_union_prestacion_operador(_mini_fact_base(), _mini_operacion(), _mini_evidencia([1]), {"19318008"})
    assert con_dos["habilitada"] and con_dos["resultado_union"] == "implementada_con_tratamiento"
    assert con_uno["habilitada"] and con_uno["resultado_union"] == "implementada"


def test_enriquecer_con_operador_no_asigna_nada_si_la_union_no_esta_habilitada():
    fact = pd.DataFrame({"id_localidad": ["19318008"], "periodo": [pd.Timestamp("2021-08-01")], "es_comparable_operador": [True]})
    sin_union = gold.enriquecer_con_operador(fact, pd.DataFrame(), set(), habilitada=False)
    assert sin_union["estado_operador"].iloc[0] == "union no habilitada" and sin_union["id_operador"].isna().all()


@pytest.mark.parametrize("ids_operador, municipios_operador, esperado, por_empresa", [
    (["6026", "1604"], ["19318"], "implementada", True),          # identificadores compartidos (>= 95%)
    (["1892", "520"], ["19318"], "solo_municipio", False),        # 0% en común: regla de respaldo del diseño
    (["1892"], ["123"], "no_implementada", False),                # municipio inválido: ni siquiera por municipio
])
def test_union_operador_pqr_por_empresa_o_solo_municipio(ids_operador, municipios_operador, esperado, por_empresa):
    op = pd.DataFrame({"identificador_empresa": ids_operador, "id_mpio": (municipios_operador * len(ids_operador))[: len(ids_operador)]})
    pq = pd.DataFrame({"identificador_empresa": ["6026", "1604"], "id_mpio": ["19318", "19001"]})
    _, resumen = gold.evaluar_union_operador_pqr(op, pq)
    assert resumen["resultado_union"] == esperado and resumen["habilitada_por_empresa"] is por_empresa


# ---------------------------------------------------------------------------
# Gold: KPI del pipeline
# ---------------------------------------------------------------------------
def _kpis(silver, tablas, reproducibles=None):
    reproducibles = reproducibles if reproducibles is not None else {n: True for n in tablas}
    return gold.calcular_kpis(silver, tablas, reproducibles, {"pqr": {"duplicados_exactos_eliminados": 1}}).set_index("indicador")


def test_los_ocho_kpi_se_calculan_y_cumplen_con_datos_sanos(silver, resultado_gold):
    reiniciar_errores_controlados()
    kpis = _kpis(silver, resultado_gold.tablas)
    assert list(kpis.index) == [
        "pct_fuentes_integradas", "pct_variables_estandarizadas", "pct_registros_duplicados", "pct_registros_con_trazabilidad",
        "pct_campos_criticos_completos", "numero_errores_transformacion", "pct_reglas_negocio_documentadas", "pct_informacion_reproducible",
    ]
    assert kpis["cumple"].all(), kpis[~kpis["cumple"]]
    assert kpis.loc["pct_fuentes_integradas", "valor"] == 100 and kpis.loc["pct_registros_duplicados", "valor"] == 0


def test_los_kpi_si_fallan_cuando_los_datos_estan_mal(silver, resultado_gold):
    reiniciar_errores_controlados()
    mala = {nombre: df.copy() for nombre, df in silver.items()}
    mala["prestacion"].loc[mala["prestacion"].index[0], "id_mpio"] = "123"                         # DANE con longitud inválida
    mala["prestacion"].loc[mala["prestacion"].index[:5], "energia_reactiva"] = pd.NA                # campos críticos incompletos
    tablas = {n: t.copy() for n, t in resultado_gold.tablas.items()}
    tablas["fact_prestacion"] = pd.concat([tablas["fact_prestacion"], tablas["fact_prestacion"].head(3)], ignore_index=True)  # duplicados
    tablas["fact_pqr"]["reglas_aplicadas"] = tablas["fact_pqr"]["reglas_aplicadas"] + "; regla_inventada"                    # regla sin documentar
    tablas["dim_municipio"]["lote_id"] = None                                                        # sin trazabilidad
    registrar_error_controlado("prueba", "error simulado")
    kpis = _kpis(mala, tablas, reproducibles={**{n: True for n in tablas}, "fact_pqr": False})
    for indicador in ("pct_variables_estandarizadas", "pct_registros_duplicados", "pct_registros_con_trazabilidad",
                      "pct_campos_criticos_completos", "numero_errores_transformacion", "pct_reglas_negocio_documentadas",
                      "pct_informacion_reproducible"):
        assert not kpis.loc[indicador, "cumple"], indicador
    assert kpis.loc["numero_errores_transformacion", "valor"] == 1
    assert "regla_inventada" in kpis.loc["pct_reglas_negocio_documentadas", "detalle"]
    reiniciar_errores_controlados()


def test_el_kpi_de_campos_criticos_reporta_la_peor_fuente_y_no_se_diluye(silver, resultado_gold):
    reiniciar_errores_controlados()
    mala = {nombre: df.copy() for nombre, df in silver.items()}
    mala["prestacion"].loc[mala["prestacion"].index[0], "energia_reactiva"] = pd.NA  # 1 de 24 registros incompleto
    fila = _kpis(mala, resultado_gold.tablas).loc["pct_campos_criticos_completos"]
    # El promedio de las tres fuentes (98.6%) cumpliría la meta de 98% y ocultaría el problema; la peor fuente (95.8%) no.
    assert fila["valor"] == pytest.approx(100 * 23 / 24, abs=0.01) and not fila["cumple"]


# ---------------------------------------------------------------------------
# Carga a PostgreSQL: helpers que no necesitan servidor
# ---------------------------------------------------------------------------
def test_preparar_para_sql_convierte_listas_a_texto_y_quita_la_zona_horaria():
    df = pd.DataFrame({
        "reglas": [np.array(["a", "b"]), np.array([]), ["c"]],
        "cuando": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]).tz_localize("UTC"),
        "numero": [1, 2, 3],
    })
    listo = carga.preparar_para_sql(df)
    assert listo["reglas"].iloc[0] == "a; b" and listo["reglas"].iloc[2] == "c"
    assert pd.isna(listo["reglas"].iloc[1])  # una lista vacía queda nula (NULL en la base)
    assert listo["cuando"].dt.tz is None and listo["numero"].tolist() == [1, 2, 3]


def test_tipos_sql_guarda_las_fechas_a_medianoche_como_date():
    df = pd.DataFrame({
        "dia": pd.to_datetime(["2026-01-01", "2026-02-01"]), "instante": pd.to_datetime(["2026-01-01 10:30", "2026-02-01 00:00"]),
        "entero": pd.array([1, None], dtype="Int64"), "real": [1.5, 2.5], "flag": [True, False], "texto": ["a", "b"],
    })
    tipos = {c: type(t).__name__ for c, t in carga.tipos_sql(df).items()}
    assert tipos == {"dia": "Date", "instante": "DateTime", "entero": "BigInteger", "real": "Float", "flag": "Boolean", "texto": "Text"}


def test_nombre_de_indice_respeta_el_limite_de_postgresql():
    corto = carga._nombre_indice("fact_pqr", ["id_municipio"])
    largo = carga._nombre_indice("puente_operador_localidad", ["codigo_localidad_operacion", "id_operador", "clave_localidad"])
    assert corto == "ix_fact_pqr_id_municipio" and len(largo) <= carga.LONGITUD_MAX_IDENTIFICADOR
    assert largo != carga._nombre_indice("puente_operador_localidad", ["codigo_localidad_operacion", "id_operador", "id_municipio"])


def test_las_llaves_de_gold_coinciden_con_las_tablas_que_se_cargan(resultado_gold):
    for nombre, tabla in resultado_gold.tablas.items():
        claves = gold.CLAVES_TABLAS[nombre]
        assert set(claves) <= set(tabla.columns), nombre


# ---------------------------------------------------------------------------
# Orquestador main.py: errores controlados y dependencias entre etapas
# ---------------------------------------------------------------------------
def test_si_falla_extract_las_etapas_dependientes_se_omiten_y_el_error_queda_contado(monkeypatch):
    reiniciar_errores_controlados()
    ejecutadas = []

    def falla(**_):
        raise RuntimeError("sin red")

    def ok(**_):
        ejecutadas.append(1)
        return "bien"

    monkeypatch.setitem(orquestador.FUNCIONES_ETAPA, "extract", falla)
    for etapa in ("silver", "gold", "load"):
        monkeypatch.setitem(orquestador.FUNCIONES_ETAPA, etapa, ok)
    resultados = orquestador.ejecutar_etapas(["extract", "silver", "gold", "load"])
    assert resultados["extract"]["estado"] == "error"
    assert [resultados[e]["estado"] for e in ("silver", "gold", "load")] == ["omitida"] * 3 and not ejecutadas
    errores = obtener_errores_controlados()
    assert len(errores) == 1 and errores[0]["etapa"] == "extract" and "sin red" in errores[0]["detalle"]
    reiniciar_errores_controlados()


def test_un_fallo_en_perfilar_no_frena_el_resto_porque_nadie_depende_de_el(monkeypatch):
    reiniciar_errores_controlados()
    monkeypatch.setitem(orquestador.FUNCIONES_ETAPA, "perfilar", lambda **_: (_ for _ in ()).throw(RuntimeError("API lenta")))
    for etapa in ("extract", "silver", "gold", "load", "eda"):
        monkeypatch.setitem(orquestador.FUNCIONES_ETAPA, etapa, lambda **_: "bien")
    resultados = orquestador.ejecutar_etapas(orquestador.ETAPAS)
    assert resultados["perfilar"]["estado"] == "error"
    assert all(resultados[e]["estado"] == "ok" for e in ("extract", "silver", "gold", "load", "eda"))
    reiniciar_errores_controlados()


def test_el_eda_corre_aunque_falle_la_carga_porque_solo_depende_de_gold(monkeypatch):
    reiniciar_errores_controlados()

    def falla(**_):
        raise RuntimeError("PostgreSQL no disponible")

    for etapa in ("perfilar", "extract", "silver", "gold", "eda"):
        monkeypatch.setitem(orquestador.FUNCIONES_ETAPA, etapa, lambda **_: "bien")
    monkeypatch.setitem(orquestador.FUNCIONES_ETAPA, "load", falla)
    resultados = orquestador.ejecutar_etapas(orquestador.ETAPAS)
    assert resultados["load"]["estado"] == "error" and resultados["eda"]["estado"] == "ok"
    reiniciar_errores_controlados()


def test_si_falla_gold_el_eda_se_omite_porque_no_tendria_datos(monkeypatch):
    reiniciar_errores_controlados()

    def falla(**_):
        raise RuntimeError("gold roto")

    ejecutadas = []
    monkeypatch.setitem(orquestador.FUNCIONES_ETAPA, "gold", falla)
    monkeypatch.setitem(orquestador.FUNCIONES_ETAPA, "eda", lambda **_: ejecutadas.append(1) or "bien")
    resultados = orquestador.ejecutar_etapas(["gold", "eda"])
    assert resultados["gold"]["estado"] == "error" and resultados["eda"]["estado"] == "omitida" and not ejecutadas
    reiniciar_errores_controlados()


def test_main_devuelve_0_sin_errores_y_1_con_errores(monkeypatch):
    monkeypatch.setitem(orquestador.FUNCIONES_ETAPA, "gold", lambda **_: "bien")
    assert orquestador.main(["--etapa", "gold"]) == 0

    def falla(**_):
        raise RuntimeError("fallo controlado")

    monkeypatch.setitem(orquestador.FUNCIONES_ETAPA, "gold", falla)
    assert orquestador.main(["--etapa", "gold"]) == 1
    reiniciar_errores_controlados()


def test_main_por_defecto_corre_todas_las_etapas_en_orden(monkeypatch):
    orden = []
    for etapa in orquestador.ETAPAS:
        monkeypatch.setitem(orquestador.FUNCIONES_ETAPA, etapa, lambda etapa=etapa, **_: orden.append(etapa) or "bien")
    assert orquestador.main([]) == 0
    assert orden == ["perfilar", "extract", "silver", "gold", "load", "eda"]


def test_main_pasa_la_opcion_incluir_silver_a_la_carga(monkeypatch):
    recibido = {}
    monkeypatch.setitem(orquestador.FUNCIONES_ETAPA, "load", lambda incluir_silver=False, **_: recibido.update(v=incluir_silver) or "bien")
    orquestador.main(["--etapa", "load", "--incluir-silver"])
    assert recibido["v"] is True
