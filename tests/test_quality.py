"""Pruebas de src/transform/quality_checks.py: las cinco pruebas de la sección 5 del diseño
(unicidad de llave, validez DANE, cruce entre fuentes, cardinalidad e identificador de empresa
común), la de campos críticos completos y sus umbrales. Sin red, con fixtures pequeñas."""
import sys
from pathlib import Path

import pandas as pd
import pytest

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from src.transform import quality_checks as qc  # noqa: E402


# --------------------------------------------------------------------------- umbrales
def test_los_umbrales_configurados_son_los_del_diseno():
    assert qc.CONFIG["umbrales_calidad"] == {
        "dane_valido_pct_minimo": 95,
        "duplicados_pct_maximo": 1,
        "campos_criticos_completos_pct_minimo": 98,
        "identificador_empresa_comun_pct_minimo": 95,
    }


# --------------------------------------------------------------------------- 1) unicidad de llave
def test_unicidad_aprueba_con_cero_duplicados():
    df = pd.DataFrame({"a": ["x", "y", "z"], "b": [1, 1, 2]})
    res = qc.probar_unicidad_llave(df, ["a", "b"])
    assert res.aprobado and res.metrica == 0.0 and res.detalle["grupos_duplicados"] == 0


def test_unicidad_documenta_grupos_y_filas_afectadas():
    df = pd.DataFrame({"llave": ["a", "a", "b", "c", "c", "c"], "valor": [1, 2, 3, 4, 5, 6]})
    res = qc.probar_unicidad_llave(df, ["llave"])
    assert not res.aprobado
    assert res.detalle["grupos_duplicados"] == 2 and res.detalle["filas_en_duplicados"] == 5
    assert res.metrica == pytest.approx(100 * 5 / 6, abs=0.01)


def test_unicidad_con_llave_compuesta_y_nulos_en_la_llave():
    df = pd.DataFrame({"a": ["x", "x", None, None], "b": [1, 2, 1, 1]})
    res = qc.probar_unicidad_llave(df, ["a", "b"])
    assert res.detalle["grupos_duplicados"] == 1  # las dos filas (None, 1) cuentan como repetidas


def test_unicidad_de_tabla_vacia_no_falla():
    assert qc.probar_unicidad_llave(pd.DataFrame({"a": []}), ["a"]).aprobado


# --------------------------------------------------------------------------- 2) validez DANE
def test_validez_dane_acepta_codigos_con_la_longitud_correcta():
    res = qc.probar_validez_dane(pd.Series(["05001", "76001", "19001", "52835"]), 5)
    assert res.aprobado and res.metrica == 100.0 and res.detalle["catalogo_divipola_usado"] is False


def test_validez_dane_rechaza_longitud_incorrecta_y_no_numericos():
    res = qc.probar_validez_dane(pd.Series(["5001", "76001", "ABCDE", "760010"]), 5)
    assert res.metrica == 25.0 and not res.aprobado


def test_validez_dane_umbral_de_95_por_ciento_es_inclusivo():
    en_el_limite = pd.Series(["76001"] * 19 + ["7600"])  # 19 de 20 = 95%
    debajo = pd.Series(["76001"] * 18 + ["7600"] * 2)    # 18 de 20 = 90%
    assert qc.probar_validez_dane(en_el_limite, 5).aprobado
    assert not qc.probar_validez_dane(debajo, 5).aprobado


def test_validez_dane_con_catalogo_exige_pertenencia():
    serie = pd.Series(["76001", "76002", "99999"])
    res = qc.probar_validez_dane(serie, 5, catalogo_valido={"76001", "76002"})
    assert res.detalle["catalogo_divipola_usado"] is True
    assert res.metrica == pytest.approx(66.67, abs=0.01) and not res.aprobado


def test_validez_dane_ignora_nulos_y_falla_si_no_hay_valores():
    assert qc.probar_validez_dane(pd.Series(["76001", None]), 5).metrica == 100.0
    assert not qc.probar_validez_dane(pd.Series([None, None], dtype="object"), 5).aprobado


# --------------------------------------------------------------------------- 3) cruce entre fuentes
def test_cruce_reporta_el_porcentaje_de_llaves_sin_cruce():
    res = qc.probar_cruce_entre_fuentes({"a", "b", "c", "d"}, {"a", "b", "x"}, "prueba")
    assert res.metrica == 50.0 and res.aprobado  # es un reporte: documenta, no bloquea
    assert res.detalle["n_interseccion"] == 2 and res.nombre_prueba == "cruce_prueba"


def test_cruce_acepta_series_y_conjuntos():
    res = qc.probar_cruce_entre_fuentes(pd.Series(["a", "b", None]), pd.Series(["b"]), "x")
    assert res.metrica == 50.0


def test_cruce_sin_llaves_en_a_no_se_puede_calcular():
    assert not qc.probar_cruce_entre_fuentes(set(), {"a"}, "x").aprobado


# --------------------------------------------------------------------------- 4) cardinalidad
def test_cardinalidad_dentro_de_lo_esperado_aprueba():
    df = pd.DataFrame({"localidad": ["a", "a", "b"], "mes": [1, 2, 1], "operador": ["o1", "o1", "o2"]})
    res = qc.probar_cardinalidad_maxima(df, ["localidad", "mes"], "operador", 1)
    assert res.aprobado and res.metrica == 1.0


def test_cardinalidad_excedida_reporta_el_maximo_observado_y_los_grupos():
    df = pd.DataFrame({"localidad": ["a", "a", "a", "b"], "mes": [1, 1, 1, 1], "operador": ["o1", "o2", "o3", "o1"]})
    res = qc.probar_cardinalidad_maxima(df, ["localidad", "mes"], "operador", 1)
    assert not res.aprobado and res.metrica == 3.0 and res.detalle["grupos_que_exceden"] == 1


# --------------------------------------------------------------------------- 5) identificador de empresa común
def test_identificador_de_empresa_comun_aprueba_desde_95_por_ciento():
    a = pd.Series([str(i) for i in range(20)])
    assert qc.probar_identificador_empresa_comun(a, pd.Series([str(i) for i in range(19)] + ["zzz"])).aprobado  # 19/20 = 95%
    assert not qc.probar_identificador_empresa_comun(a, pd.Series([str(i) for i in range(18)])).aprobado        # 18/20 = 90%


def test_identificador_de_empresa_sin_coincidencias_es_el_caso_real_de_pqr():
    operadores = pd.Series(["1892", "520", "26040"])
    empresas_gas = pd.Series(["6026", "1604"])
    res = qc.probar_identificador_empresa_comun(operadores, empresas_gas)
    assert res.metrica == 0.0 and not res.aprobado
    assert res.detalle["umbral_minimo"] == 95


def test_identificador_de_empresa_compara_como_texto_sin_importar_el_tipo():
    assert qc.probar_identificador_empresa_comun(pd.Series([1892, 520]), pd.Series(["1892", "520"])).metrica == 100.0


# --------------------------------------------------------------------------- campos críticos
def test_campos_criticos_umbral_de_98_por_ciento_es_inclusivo():
    en_el_limite = pd.DataFrame({"x": [None, None] + [1] * 98})  # 98/100
    debajo = pd.DataFrame({"x": [None, None, None] + [1] * 97})   # 97/100
    assert qc.probar_campos_criticos_completos(en_el_limite, ["x"]).aprobado
    assert not qc.probar_campos_criticos_completos(debajo, ["x"]).aprobado


def test_campos_criticos_cuenta_registros_no_celdas():
    # 100 registros, cada uno con 1 de 3 campos críticos vacío en 3 registros distintos:
    # por celda serían 99% completas, pero por registro solo 97% -> no aprueba.
    df = pd.DataFrame({"a": [None, 1, 1] + [1] * 97, "b": [1, None, 1] + [1] * 97, "c": [1, 1, None] + [1] * 97})
    res = qc.probar_campos_criticos_completos(df, ["a", "b", "c"])
    assert res.metrica == 97.0 and not res.aprobado
    assert res.detalle["pct_celdas_completas"] == pytest.approx(99.0, abs=0.01) and res.detalle["registros_completos"] == 97


def test_campos_criticos_con_columna_inexistente_no_aprueba():
    res = qc.probar_campos_criticos_completos(pd.DataFrame({"x": [1]}), ["x", "y"])
    assert not res.aprobado and res.detalle["columnas_faltantes"] == ["y"]


# --------------------------------------------------------------------------- diagnóstico de silver
def test_diagnostico_de_silver_marca_la_llave_agregada_de_pqr_como_informativa():
    silver = {
        "pqr": pd.DataFrame({
            "id_mpio": ["76001", "76001"], "car_carg_ano": [2021, 2021], "semestre": [2, 2], "identificador_empresa": ["1", "1"],
            "car_t1554_dane_depto": ["76", "76"], "car_t1554_dane_mpio": ["001", "001"], "car_carg_periodo": [7, 8], "rad_recibido": ["a", "b"],
        }),
    }
    filas = {(f["prueba"], f["objeto"].split(" ")[0]): f for f in qc.diagnosticar_silver(silver)}
    unicidad = next(f for f in qc.diagnosticar_silver(silver) if f["prueba"] == "unicidad_llave")
    assert unicidad["informativa"] and not unicidad["aprobado"]
    assert any(f["prueba"] == "validez_dane" and f["aprobado"] for f in filas.values())
