"""Perfila las tres fuentes ZNI de datos.gov.co para cerrar la matriz de granularidad y llaves.

Ubicación en el proyecto: src/etl/perfilar_fuentes.py
Uso (desde la raíz del proyecto):  python src/etl/perfilar_fuentes.py
Requiere: pip install requests pandas

Salidas en docs/perfilado/:
    columnas.csv      campos reales, tipo, filas totales, % de nulos y fecha de última actualización
    muestras.csv      5 filas de cada fuente
    formatos_dane.csv longitud y % numérico de cada campo que parece código DANE
    llaves.csv        prueba de unicidad de cada llave candidata (¿hay duplicados?)
    cruces.csv        % de valores DANE de una fuente que aparecen en otra (localidad y municipio)

Los campos se detectan por nombre (dane, fecha, empresa, operador...). Es una heurística:
revisen a mano las columnas detectadas antes de copiar los resultados a la matriz del documento.
"""
import re
from datetime import datetime, timezone
from itertools import product
from pathlib import Path

import pandas as pd
import requests

BASE = "https://www.datos.gov.co"
FUENTES = {
    "prestacion": "3ebi-d83g",
    "operacion_diaria": "qwe5-ycap",
    "pqr": "5wua-nr2d",
}
SALIDA = Path("docs/perfilado")
PAT_DANE = re.compile(r"dane|divipola|cod(igo)?_?(mun|loc|dep|cent)", re.I)
PAT_TIEMPO = re.compile(r"fecha|periodo|anio|ano$|mes|semestre|trimestre", re.I)
PAT_ACTOR = re.compile(r"empresa|operador|prestador|nit", re.I)


def get(url, params=None):
    r = requests.get(url, params=params, timeout=120)
    r.raise_for_status()
    return r.json()


def consultar(id_, params):
    return get(f"{BASE}/resource/{id_}.json", params)


def metadatos(id_):
    meta = get(f"{BASE}/api/views/{id_}.json")
    cols = [c for c in meta["columns"] if not c["fieldName"].startswith(":")]
    return meta, cols


def conteo_no_nulos(id_, campos):
    sel = ", ".join(f"count({c}) as c{i}" for i, c in enumerate(campos))
    fila = consultar(id_, {"$select": sel})[0]
    return {c: int(fila.get(f"c{i}", 0)) for i, c in enumerate(campos)}


def valores_distintos(id_, campo):
    filas = consultar(id_, {"$select": campo, "$group": campo, "$limit": 200000})
    serie = pd.Series([f.get(campo) for f in filas if f.get(campo) is not None], dtype="string")
    return serie.str.strip().str.replace(r"\.0$", "", regex=True)


def duplicados(id_, llave):
    sel = ", ".join(llave)
    return consultar(id_, {
        "$select": f"{sel}, count(*) as n",
        "$group": sel,
        "$having": "count(*) > 1",
        "$order": "n desc",
        "$limit": 5,
    })


def main():
    SALIDA.mkdir(parents=True, exist_ok=True)
    columnas, muestras, formatos, llaves, distintos = [], [], [], [], {}

    for nombre, id_ in FUENTES.items():
        meta, cols = metadatos(id_)
        campos = [c["fieldName"] for c in cols]
        total = int(consultar(id_, {"$select": "count(*)"})[0]["count"])
        no_nulos = conteo_no_nulos(id_, campos)
        actualizado = datetime.fromtimestamp(meta["rowsUpdatedAt"], tz=timezone.utc).date()

        for c in cols:
            f = c["fieldName"]
            columnas.append({
                "fuente": nombre, "id": id_, "campo": f, "tipo": c["dataTypeName"],
                "descripcion": c.get("description", ""), "filas_totales": total,
                "pct_nulos": round(100 * (1 - no_nulos[f] / total), 2) if total else None,
                "ultima_actualizacion": actualizado,
            })

        for fila in consultar(id_, {"$limit": 5}):
            muestras.append({"fuente": nombre, **fila})

        dane = [f for f in campos if PAT_DANE.search(f)]
        tiempo = [f for f in campos if PAT_TIEMPO.search(f)]
        actor = [f for f in campos if PAT_ACTOR.search(f)]

        for f in dane:
            v = valores_distintos(id_, f)
            distintos[(nombre, f)] = v
            formatos.append({
                "fuente": nombre, "campo": f, "valores_distintos": len(v),
                "longitudes": {int(k): int(n) for k, n in v.str.len().value_counts().items()},
                "pct_solo_digitos": round(100 * v.str.fullmatch(r"\d+").mean(), 2) if len(v) else None,
            })

        for d in dane:
            for etiqueta, llave in (("dane+tiempo", [d] + tiempo), ("dane+tiempo+actor", [d] + tiempo + actor)):
                llave = list(dict.fromkeys(llave))
                dup = duplicados(id_, llave)
                llaves.append({
                    "fuente": nombre, "variante": etiqueta, "campos_llave": ", ".join(llave),
                    "hay_duplicados": bool(dup), "ejemplos_duplicados": dup,
                })

    cruces = []
    nombres = list(FUENTES)
    for i, a in enumerate(nombres):
        for b in nombres[i + 1:]:
            cols_a = [k for k in distintos if k[0] == a]
            cols_b = [k for k in distintos if k[0] == b]
            for ka, kb in product(cols_a, cols_b):
                for etiqueta, corte in (("completo", None), ("5 dígitos (municipio)", 5)):
                    va, vb = distintos[ka], distintos[kb]
                    if corte:
                        va, vb = va.str.zfill(corte).str[:corte], vb.str.zfill(corte).str[:corte]
                    sa, sb = set(va), set(vb)
                    if not sa:
                        continue
                    cruces.append({
                        "fuente_a": a, "campo_a": ka[1], "fuente_b": b, "campo_b": kb[1],
                        "nivel": etiqueta, "pct_de_a_en_b": round(100 * len(sa & sb) / len(sa), 2),
                        "pct_de_b_en_a": round(100 * len(sa & sb) / len(sb), 2) if sb else None,
                    })

    pd.DataFrame(columnas).to_csv(SALIDA / "columnas.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(muestras).to_csv(SALIDA / "muestras.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(formatos).to_csv(SALIDA / "formatos_dane.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(llaves).to_csv(SALIDA / "llaves.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(cruces).sort_values("pct_de_a_en_b", ascending=False).to_csv(
        SALIDA / "cruces.csv", index=False, encoding="utf-8-sig")
    print(f"Listo. Resultados en {SALIDA.resolve()}")


if __name__ == "__main__":
    main()
