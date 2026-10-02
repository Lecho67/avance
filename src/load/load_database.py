"""Carga de gold (y, opcionalmente, silver) a PostgreSQL con SQLAlchemy.

- Esquemas: gold (modelo analítico para Power BI) y silver (opcional, con --incluir-silver).
- Estrategia idempotente "truncate + load": si la tabla existe con las mismas columnas se
  vacía y se vuelve a llenar; si no existe o cambió su esquema se recrea. Todo dentro de una
  transacción por tabla, así que una carga fallida no deja una tabla a medias.
- Índices por llaves: llave primaria cuando la llave declarada es única y no tiene nulos;
  índice normal en caso contrario, más índices en las columnas típicas de relación.
- Al final verifica que el número de filas en la base coincida con el de origen.

Conexión: variable DATABASE_URL del .env o, si está vacía, las variables PG_* (ver .env.example).
Si la base no existe, intenta crearla.

Uso (desde la raíz del proyecto, con el entorno virtual activado):
    python src/load/load_database.py                    # carga gold
    python src/load/load_database.py --incluir-silver   # carga gold y silver
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, inspect, text
from sqlalchemy import types as sqltypes
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.exc import OperationalError, SQLAlchemyError

_RAIZ_PROYECTO = Path(__file__).resolve().parent.parent.parent
if str(_RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_PROYECTO))

from src import (  # noqa: E402
    cargar_configuracion,
    obtener_logger,
    obtener_url_base_datos,
    registrar_error_controlado,
)
from src.transform.gold_transformations import CLAVES_TABLAS  # noqa: E402

CONFIG = cargar_configuracion()
LOGGER = obtener_logger("load_database", "load.log")

RUTA_SILVER = Path(CONFIG["rutas"]["silver"])
RUTA_GOLD = Path(CONFIG["rutas"]["gold"])
ESQUEMA_GOLD = "gold"
ESQUEMA_SILVER = "silver"
LONGITUD_MAX_IDENTIFICADOR = 63  # límite de PostgreSQL
COLUMNAS_DE_RELACION = ("clave_localidad", "id_municipio", "id_departamento", "id_operador", "id_empresa", "periodo")
TAMANO_LOTE = 2000

# Llaves de las tablas silver (las definidas en config.yaml por fuente).
CLAVES_SILVER: dict[str, list[str]] = {nombre: datos["campos_llave"] for nombre, datos in CONFIG["fuentes"].items()}


class ErrorCargaBaseDatos(RuntimeError):
    """Falla controlada al cargar a PostgreSQL (conexión, permisos o verificación)."""


# ---------------------------------------------------------------------------
# Conexión
# ---------------------------------------------------------------------------
def _crear_base_si_no_existe(url: URL) -> None:
    """Crea la base de datos de la URL conectándose a la base de mantenimiento 'postgres'."""
    base = url.database
    mantenimiento = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with mantenimiento.connect() as conexion:
            existe = conexion.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": base}).scalar()
            if not existe:
                conexion.execute(text(f'CREATE DATABASE "{base}"'))
                LOGGER.info("Base de datos '%s' creada.", base)
    finally:
        mantenimiento.dispose()


def crear_motor(url: str | None = None) -> Engine:
    """Crea el motor SQLAlchemy y comprueba la conexión (creando la base si hace falta)."""
    url = make_url(url or obtener_url_base_datos())
    motor = create_engine(url, pool_pre_ping=True)
    try:
        with motor.connect() as conexion:
            conexion.execute(text("SELECT 1"))
    except OperationalError as error:
        if "does not exist" in str(error) or "no existe" in str(error):
            try:
                _crear_base_si_no_existe(url)
                motor = create_engine(url, pool_pre_ping=True)
                with motor.connect() as conexion:
                    conexion.execute(text("SELECT 1"))
                return motor
            except SQLAlchemyError as error_creacion:
                raise ErrorCargaBaseDatos(
                    f"La base '{url.database}' no existe y no se pudo crear: {error_creacion}"
                ) from error_creacion
        raise ErrorCargaBaseDatos(
            "No se pudo conectar a PostgreSQL. Revisa DATABASE_URL o las variables PG_* del archivo .env "
            f"(host={url.host}, puerto={url.port}, base={url.database}, usuario={url.username}) y que el servidor esté en marcha. "
            f"Detalle: {str(error).splitlines()[0]}"
        ) from error
    return motor


# ---------------------------------------------------------------------------
# Preparación de los datos
# ---------------------------------------------------------------------------
def _lista_a_texto(valor):
    """Convierte una lista/arreglo (p. ej. _reglas_aplicadas de silver) en 'a; b; c'."""
    if isinstance(valor, (list, tuple, set)) or hasattr(valor, "tolist"):
        elementos = list(valor)
        return "; ".join(map(str, elementos)) if elementos else None
    return valor


def preparar_para_sql(df: pd.DataFrame) -> pd.DataFrame:
    """Deja el DataFrame listo para PostgreSQL: listas (p. ej. _reglas_aplicadas) a texto
    y fechas con zona horaria a UTC sin zona."""
    df = df.copy()
    for columna in df.columns:
        serie = df[columna]
        if serie.dtype == object:
            df[columna] = serie.map(_lista_a_texto)
        elif isinstance(serie.dtype, pd.DatetimeTZDtype):
            df[columna] = serie.dt.tz_convert("UTC").dt.tz_localize(None)
    return df


def tipos_sql(df: pd.DataFrame) -> dict[str, sqltypes.TypeEngine]:
    """Tipo SQL de cada columna. Las fechas a medianoche se guardan como DATE."""
    tipos: dict[str, sqltypes.TypeEngine] = {}
    for columna in df.columns:
        serie = df[columna]
        if pd.api.types.is_bool_dtype(serie):
            tipos[columna] = sqltypes.Boolean()
        elif pd.api.types.is_integer_dtype(serie):
            tipos[columna] = sqltypes.BigInteger()
        elif pd.api.types.is_float_dtype(serie):
            tipos[columna] = sqltypes.Float(53)
        elif pd.api.types.is_datetime64_any_dtype(serie):
            valores = serie.dropna()
            a_medianoche = bool(len(valores) == 0 or (valores.dt.normalize() == valores).all())
            tipos[columna] = sqltypes.Date() if a_medianoche else sqltypes.DateTime()
        else:
            tipos[columna] = sqltypes.Text()
    return tipos


# ---------------------------------------------------------------------------
# Tablas e índices
# ---------------------------------------------------------------------------
def _nombre_indice(tabla: str, columnas: list[str], prefijo: str = "ix") -> str:
    nombre = f"{prefijo}_{tabla}_{'_'.join(columnas)}"
    if len(nombre) > LONGITUD_MAX_IDENTIFICADOR:
        huella = hashlib.md5(nombre.encode("utf-8")).hexdigest()[:8]
        nombre = f"{nombre[:LONGITUD_MAX_IDENTIFICADOR - 9]}_{huella}"
    return nombre


def _cotizar(motor: Engine, identificador: str) -> str:
    return motor.dialect.identifier_preparer.quote(identificador)


def _tabla_compatible(motor: Engine, esquema: str, tabla: str, columnas: list[str]) -> bool:
    """True si la tabla ya existe con exactamente las mismas columnas y en el mismo orden."""
    inspector = inspect(motor)
    if not inspector.has_table(tabla, schema=esquema):
        return False
    return [c["name"] for c in inspector.get_columns(tabla, schema=esquema)] == columnas


def cargar_tabla(motor: Engine, df: pd.DataFrame, tabla: str, esquema: str, claves: list[str]) -> int:
    """Carga un DataFrame con truncate + load (recreando la tabla si cambió su esquema) y crea
    sus índices. Devuelve las filas cargadas."""
    datos = preparar_para_sql(df)
    columnas = list(datos.columns)
    tipos = tipos_sql(datos)
    destino = f"{_cotizar(motor, esquema)}.{_cotizar(motor, tabla)}"
    claves = [c for c in claves if c in columnas]

    with motor.begin() as conexion:
        if _tabla_compatible(motor, esquema, tabla, columnas):
            conexion.execute(text(f"TRUNCATE TABLE {destino}"))
            modo = "truncate+load"
        else:
            conexion.execute(text(f"DROP TABLE IF EXISTS {destino}"))
            datos.head(0).to_sql(tabla, conexion, schema=esquema, if_exists="fail", index=False, dtype=tipos)
            modo = "recreada+load"
        datos.to_sql(
            tabla, conexion, schema=esquema, if_exists="append", index=False, dtype=tipos,
            method="multi", chunksize=max(1, TAMANO_LOTE),
        )
        _crear_indices(motor, conexion, datos, tabla, esquema, claves)
    LOGGER.info("  %s.%s: %s filas (%s)", esquema, tabla, len(datos), modo)
    return len(datos)


def _crear_indices(motor: Engine, conexion, datos: pd.DataFrame, tabla: str, esquema: str, claves: list[str]) -> None:
    """Llave primaria si la llave es única y sin nulos; si no, índice normal. Más índices en
    las columnas de relación presentes."""
    destino = f"{_cotizar(motor, esquema)}.{_cotizar(motor, tabla)}"
    if claves:
        es_unica = bool(datos[claves].notna().all().all()) and not datos.duplicated(claves).any()
        lista = ", ".join(_cotizar(motor, c) for c in claves)
        tiene_pk = bool(conexion.execute(
            text("SELECT 1 FROM pg_constraint WHERE conrelid = CAST(:t AS regclass) AND contype = 'p'"),
            {"t": destino},
        ).scalar())
        if es_unica and not tiene_pk:
            conexion.execute(text(f"ALTER TABLE {destino} ADD PRIMARY KEY ({lista})"))
        elif not es_unica:
            conexion.execute(text(f"CREATE INDEX IF NOT EXISTS {_cotizar(motor, _nombre_indice(tabla, claves))} ON {destino} ({lista})"))
    for columna in COLUMNAS_DE_RELACION:
        if columna in datos.columns and columna not in claves[:1]:
            conexion.execute(text(
                f"CREATE INDEX IF NOT EXISTS {_cotizar(motor, _nombre_indice(tabla, [columna]))} ON {destino} ({_cotizar(motor, columna)})"
            ))


def contar_filas(motor: Engine, esquema: str, tabla: str) -> int:
    """Filas de una tabla en la base (para verificar la carga)."""
    with motor.connect() as conexion:
        return int(conexion.execute(text(f"SELECT count(*) FROM {_cotizar(motor, esquema)}.{_cotizar(motor, tabla)}")).scalar())


# ---------------------------------------------------------------------------
# Orquestación
# ---------------------------------------------------------------------------
def leer_tablas_gold() -> dict[str, pd.DataFrame]:
    """Lee todas las tablas de data/gold/*.parquet."""
    archivos = sorted(RUTA_GOLD.glob("*.parquet"))
    if not archivos:
        raise FileNotFoundError(f"No hay tablas en {RUTA_GOLD}; corre la etapa gold primero.")
    return {archivo.stem: pd.read_parquet(archivo) for archivo in archivos}


def leer_tablas_silver() -> dict[str, pd.DataFrame]:
    """Lee las tablas de data/silver/*.parquet."""
    archivos = sorted(RUTA_SILVER.glob("*.parquet"))
    if not archivos:
        raise FileNotFoundError(f"No hay tablas en {RUTA_SILVER}; corre la etapa silver primero.")
    return {archivo.stem: pd.read_parquet(archivo) for archivo in archivos}


def ejecutar_carga(incluir_silver: bool = False, url: str | None = None) -> dict[str, int]:
    """Carga gold (y silver si se pide) y verifica los conteos. Devuelve {esquema.tabla: filas}."""
    motor = crear_motor(url)
    try:
        with motor.begin() as conexion:
            for esquema in (ESQUEMA_GOLD, ESQUEMA_SILVER) if incluir_silver else (ESQUEMA_GOLD,):
                conexion.execute(text(f"CREATE SCHEMA IF NOT EXISTS {_cotizar(motor, esquema)}"))

        trabajos: list[tuple[str, str, pd.DataFrame, list[str]]] = []
        for nombre, df in leer_tablas_gold().items():
            trabajos.append((ESQUEMA_GOLD, nombre, df, CLAVES_TABLAS.get(nombre, [])))
        if incluir_silver:
            for nombre, df in leer_tablas_silver().items():
                trabajos.append((ESQUEMA_SILVER, nombre, df, CLAVES_SILVER.get(nombre, [])))

        cargadas: dict[str, int] = {}
        LOGGER.info("Cargando %s tablas a PostgreSQL (%s)...", len(trabajos), motor.url.render_as_string(hide_password=True))
        for esquema, nombre, df, claves in trabajos:
            cargadas[f"{esquema}.{nombre}"] = cargar_tabla(motor, df, nombre, esquema, claves)

        for esquema, nombre, df, _ in trabajos:
            en_base = contar_filas(motor, esquema, nombre)
            if en_base != len(df):
                raise ErrorCargaBaseDatos(f"{esquema}.{nombre}: {en_base} filas en la base vs {len(df)} de origen")
        LOGGER.info("Carga verificada: %s tablas, %s filas.", len(cargadas), sum(cargadas.values()))
        return cargadas
    except SQLAlchemyError as error:
        raise ErrorCargaBaseDatos(f"Falló la carga a PostgreSQL: {error}") from error
    finally:
        motor.dispose()


def main() -> None:
    """Punto de entrada de línea de comandos."""
    parser = argparse.ArgumentParser(description="Carga gold (y opcionalmente silver) a PostgreSQL.")
    parser.add_argument("--incluir-silver", action="store_true", help="Cargar también las tablas silver.")
    args = parser.parse_args()
    try:
        cargadas = ejecutar_carga(incluir_silver=args.incluir_silver)
    except (ErrorCargaBaseDatos, FileNotFoundError) as error:
        registrar_error_controlado("load", str(error))
        LOGGER.error("%s", error)
        sys.exit(1)
    for tabla, filas in cargadas.items():
        print(f"{tabla:45s} {filas:>8d}")


if __name__ == "__main__":
    main()
