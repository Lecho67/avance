"""Pruebas de src/extract/extract_excel.py sin red: paginación, reintentos con backoff, token
opcional, respaldo local (.csv/.xlsx) y columnas de trazabilidad de bronze."""
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest
import requests

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from src import obtener_errores_controlados, reiniciar_errores_controlados  # noqa: E402
from src.extract import extract_excel as ex  # noqa: E402


class RespuestaFalsa:
    """Imita requests.Response con lo mínimo que usa extract_excel.solicitar."""

    def __init__(self, datos, estado=200):
        self._datos = datos
        self.status_code = estado

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._datos


# --------------------------------------------------------------------------- paginación
def test_extraer_paginado_recorre_todas_las_paginas(monkeypatch):
    filas = [{"id": str(i)} for i in range(5)]
    llamadas = []

    def solicitar_falso(url, parametros=None):
        llamadas.append(dict(parametros))
        desde = parametros["$offset"]
        return filas[desde: desde + parametros["$limit"]]

    monkeypatch.setattr(ex, "solicitar", solicitar_falso)
    monkeypatch.setattr(ex, "LIMITE_PAGINA", 2)
    df = ex.extraer_paginado("abcd-1234")
    assert len(df) == 5
    assert [c["$offset"] for c in llamadas] == [0, 2, 4]
    assert all(c["$order"] == ":id" for c in llamadas)  # orden estable para no perder/repetir filas


def test_extraer_paginado_con_total_multiplo_de_la_pagina_termina_en_pagina_vacia(monkeypatch):
    filas = [{"id": str(i)} for i in range(4)]
    offsets = []

    def solicitar_falso(url, parametros=None):
        offsets.append(parametros["$offset"])
        return filas[parametros["$offset"]: parametros["$offset"] + parametros["$limit"]]

    monkeypatch.setattr(ex, "solicitar", solicitar_falso)
    monkeypatch.setattr(ex, "LIMITE_PAGINA", 2)
    assert len(ex.extraer_paginado("abcd-1234")) == 4
    assert offsets == [0, 2, 4]  # la tercera página viene vacía y corta el ciclo


def test_extraer_paginado_fuente_vacia(monkeypatch):
    monkeypatch.setattr(ex, "solicitar", lambda url, parametros=None: [])
    assert ex.extraer_paginado("abcd-1234").empty


# --------------------------------------------------------------------------- reintentos y token
def test_solicitar_reintenta_con_backoff_exponencial_y_termina_bien(monkeypatch):
    intentos, esperas = {"n": 0}, []

    def get_falso(url, params=None, headers=None, timeout=None):
        intentos["n"] += 1
        if intentos["n"] < 3:
            raise requests.ConnectionError("red caída")
        return RespuestaFalsa([{"ok": 1}])

    monkeypatch.setattr(ex.requests, "get", get_falso)
    monkeypatch.setattr(ex.time, "sleep", esperas.append)
    assert ex.solicitar("http://ejemplo") == [{"ok": 1}]
    assert intentos["n"] == 3
    assert esperas == [ex.BACKOFF_BASE * 1, ex.BACKOFF_BASE * 2]


def test_solicitar_reintenta_tambien_ante_errores_http(monkeypatch):
    respuestas = iter([RespuestaFalsa(None, 500), RespuestaFalsa({"listo": True})])
    monkeypatch.setattr(ex.requests, "get", lambda *a, **k: next(respuestas))
    monkeypatch.setattr(ex.time, "sleep", lambda s: None)
    assert ex.solicitar("http://ejemplo") == {"listo": True}


def test_solicitar_agota_los_reintentos_y_falla(monkeypatch):
    intentos, esperas = {"n": 0}, []

    def siempre_falla(*a, **k):
        intentos["n"] += 1
        raise requests.Timeout("lento")

    monkeypatch.setattr(ex.requests, "get", siempre_falla)
    monkeypatch.setattr(ex.time, "sleep", esperas.append)
    with pytest.raises(RuntimeError, match="intentos"):
        ex.solicitar("http://ejemplo")
    assert intentos["n"] == ex.REINTENTOS_MAXIMOS
    assert len(esperas) == ex.REINTENTOS_MAXIMOS - 1  # no espera después del último intento


@pytest.mark.parametrize("token, esperado", [("mi-token", "mi-token"), (None, None)])
def test_solicitar_envia_el_token_solo_si_existe(monkeypatch, token, esperado):
    encabezados = {}

    def get_falso(url, params=None, headers=None, timeout=None):
        encabezados.update(headers)
        return RespuestaFalsa([])

    monkeypatch.setattr(ex, "obtener_token_socrata", lambda: token)
    monkeypatch.setattr(ex.requests, "get", get_falso)
    ex.solicitar("http://ejemplo")
    assert encabezados.get("X-App-Token") == esperado


# --------------------------------------------------------------------------- respaldo local
def test_respaldo_local_csv_conserva_los_ceros_a_la_izquierda(tmp_path, monkeypatch):
    monkeypatch.setattr(ex, "RUTA_BRONZE", tmp_path)
    pd.DataFrame({"id_mpio": ["05001"], "valor": ["7"]}).to_csv(tmp_path / "prestacion.csv", index=False)
    df = ex.leer_respaldo_manual("prestacion")
    assert df.loc[0, "id_mpio"] == "05001"


def test_respaldo_local_xlsx(tmp_path, monkeypatch):
    monkeypatch.setattr(ex, "RUTA_BRONZE", tmp_path)
    pd.DataFrame({"id_mpio": ["05001"], "valor": ["7"]}).to_excel(tmp_path / "pqr.xlsx", index=False)
    df = ex.leer_respaldo_manual("pqr")
    assert df.loc[0, "id_mpio"] == "05001" and list(df.columns) == ["id_mpio", "valor"]


def test_respaldo_local_inexistente_devuelve_none(tmp_path, monkeypatch):
    monkeypatch.setattr(ex, "RUTA_BRONZE", tmp_path)
    assert ex.leer_respaldo_manual("operacion_diaria") is None


def test_extraer_fuente_usa_el_respaldo_si_la_api_falla(tmp_path, monkeypatch):
    monkeypatch.setattr(ex, "RUTA_BRONZE", tmp_path)

    def api_caida(id_fuente):
        raise RuntimeError("sin conexión")

    monkeypatch.setattr(ex, "obtener_fecha_corte", api_caida)
    pd.DataFrame({"id_mpio": ["05001", "76001"], "valor": ["1", "2"]}).to_csv(tmp_path / "prestacion.csv", index=False)
    filas = ex.extraer_fuente("prestacion", "3ebi-d83g", "lote-prueba")
    bronze = pd.read_parquet(tmp_path / "prestacion.parquet")
    assert filas == 2 and len(bronze) == 2
    assert set(bronze["_fuente_id"]) == {"3ebi-d83g"} and set(bronze["_lote_id"]) == {"lote-prueba"}
    assert bronze["_fecha_corte_fuente"].isna().all()  # no se inventa la fecha de corte de un archivo a mano


def test_extraer_fuente_sin_api_ni_respaldo_falla(tmp_path, monkeypatch):
    monkeypatch.setattr(ex, "RUTA_BRONZE", tmp_path)

    def api_caida(id_fuente):
        raise RuntimeError("sin conexión")

    monkeypatch.setattr(ex, "obtener_fecha_corte", api_caida)
    with pytest.raises(RuntimeError, match="respaldo manual"):
        ex.extraer_fuente("pqr", "5wua-nr2d", "lote-prueba")


# --------------------------------------------------------------------------- bronze y trazabilidad
def test_bronze_guarda_todo_como_texto_con_columnas_de_trazabilidad(tmp_path, monkeypatch):
    monkeypatch.setattr(ex, "RUTA_BRONZE", tmp_path)
    corte = datetime(2026, 3, 13, 14, 42, 17, tzinfo=timezone.utc)
    monkeypatch.setattr(ex, "obtener_fecha_corte", lambda id_fuente: corte)
    monkeypatch.setattr(ex, "extraer_paginado", lambda id_fuente: pd.DataFrame({"anio": [2020, 2021], "energia": [1.5, 2.0]}))
    ex.extraer_fuente("prestacion", "3ebi-d83g", "lote-1")
    bronze = pd.read_parquet(tmp_path / "prestacion.parquet")
    assert bronze["anio"].tolist() == ["2020", "2021"]  # texto: silver es quien tipifica
    for columna in ("_fuente_id", "_fecha_carga", "_fecha_corte_fuente", "_lote_id"):
        assert columna in bronze.columns and bronze[columna].notna().all()
    assert bronze["_fecha_corte_fuente"].iloc[0] == pd.Timestamp(corte)


def test_extraer_fuente_es_idempotente_sobrescribe_y_no_acumula(tmp_path, monkeypatch):
    monkeypatch.setattr(ex, "RUTA_BRONZE", tmp_path)
    monkeypatch.setattr(ex, "obtener_fecha_corte", lambda id_fuente: datetime(2026, 1, 1, tzinfo=timezone.utc))
    monkeypatch.setattr(ex, "extraer_paginado", lambda id_fuente: pd.DataFrame({"x": ["a", "b", "c"]}))
    ex.extraer_fuente("pqr", "5wua-nr2d", "lote-1")
    ex.extraer_fuente("pqr", "5wua-nr2d", "lote-2")
    bronze = pd.read_parquet(tmp_path / "pqr.parquet")
    assert len(bronze) == 3 and set(bronze["_lote_id"]) == {"lote-2"}


def test_generar_lote_id_es_unico_y_tiene_marca_de_tiempo():
    a, b = ex.generar_lote_id(), ex.generar_lote_id()
    assert a != b and len(a.split("_")[0]) == 15


# --------------------------------------------------------------------------- errores controlados
def test_extraer_todas_registra_el_error_y_sigue_con_las_demas_fuentes(monkeypatch):
    reiniciar_errores_controlados()

    def extraer_falso(nombre, id_fuente, lote_id):
        if nombre == "pqr":
            raise RuntimeError("API caída")
        return 10

    monkeypatch.setattr(ex, "extraer_fuente", extraer_falso)
    resultados, fallidas = ex.extraer_todas()
    assert resultados == {"prestacion": 10, "operacion_diaria": 10}
    assert fallidas == ["pqr"]
    errores = obtener_errores_controlados()
    assert len(errores) == 1 and errores[0]["etapa"] == "extract" and "pqr" in errores[0]["detalle"]
    reiniciar_errores_controlados()
