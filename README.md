# Monitoreo del servicio de energía en ZNI (suroccidente colombiano)

[![Pruebas](https://github.com/Lecho67/avance/actions/workflows/pruebas.yml/badge.svg)](https://github.com/Lecho67/avance/actions/workflows/pruebas.yml)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![Licencia](https://img.shields.io/badge/licencia-MIT-green)

Proyecto de ingeniería de datos de extremo a extremo: **3 APIs abiertas → arquitectura medallón (bronze/silver/gold) → PostgreSQL →
tablero de Power BI**, con calidad de datos medida, trazabilidad por registro y 220 pruebas automáticas. Responde cuánta energía reciben
las localidades más aisladas del país y cuánto confiar en los datos que lo dicen.
Documentación completa: [**Informe final**](INFORME_FINAL.md) · [Cuaderno de análisis](notebooks/01_eda_zni.ipynb) · [Tablero (sección 9)](#9-tablero-de-power-bi).

![Municipios con mayor brecha de horas de servicio](docs/eda/figuras/fig08_brechas_municipios.png)

| | |
|---|---|
| **Qué resuelve** | Consolida tres fuentes de datos.gov.co con granularidades y llaves distintas en un modelo analítico único, con las advertencias de frescura incluidas. |
| **Resultado** | Las localidades reciben en promedio **7,8 de 24 horas diarias** (Cauca y Nariño, menos de 7) y no hay una mejora generalizada desde 2020. |
| **Decisiones técnicas** | Las llaves se validan con los datos antes de unir; las uniones que no pasan sus pruebas se degradan en lugar de forzarse; los periodos sin datos frescos se marcan, no se descartan; todo es idempotente. |
| **Stack** | Python, pandas, SQLAlchemy, PostgreSQL, Docker, Matplotlib, pytest, Power BI. |

Pipeline ETL que integra, limpia y estandariza el estado de la prestación del servicio de energía
eléctrica en las Zonas No Interconectadas (ZNI) de **Valle del Cauca (76), Cauca (19), Nariño (52) y
Putumayo (86)** a partir de tres conjuntos de datos de [datos.gov.co](https://www.datos.gov.co), y lo
deja en un modelo analítico en PostgreSQL listo para Power BI. El diseño completo está en
`docs/Avance_2_Proyecto_ETL_2026_V4.pdf`.

```
 API Socrata (3 fuentes)                                              Power BI
        │                                                                ▲
        ▼            ▼               ▼                ▼                  │
   [ perfilar ] → [ extract ]  →  [ silver ]   →   [ gold ]   →   [ load: PostgreSQL ]
   logs/perfilado   data/bronze    data/silver      data/gold        esquemas gold / silver
                    crudo+traza    tipos, DANE,     modelo + KPI
                                   filtro, calidad  + pruebas por unión
                                                       │
                                                       └→ [ eda ]  docs/eda: figuras (Matplotlib), tablas, hallazgos
```

Después de gold corre el **análisis exploratorio** (etapa `eda`, sección 8): lee `data/gold` y escribe en `docs/eda` las 16 figuras,
sus tablas de apoyo y las cifras clave que usan el cuaderno `notebooks/01_eda_zni.ipynb` y la presentación.

| Capa | Qué contiene |
|---|---|
| **bronze** | Datos tal como llegan de la API (todo como texto, inmutable) + `_fuente_id`, `_fecha_carga`, `_fecha_corte_fuente`, `_lote_id`. |
| **silver** | Tipos correctos, códigos DANE normalizados, duplicados exactos eliminados, filtro a los 4 departamentos y `_reglas_aplicadas` en cada registro. |
| **gold** | Dimensiones, hechos, puente con vigencia, indicadores y KPI. Nombres de tablas y columnas en español `snake_case`. |

Todo es **idempotente**: correr el pipeline dos veces con los mismos datos de origen produce las mismas tablas
(verificado comparando la huella de cada tabla entre corridas).

## Inicio rápido

```powershell
git clone https://github.com/Lecho67/avance.git; cd avance
python -m venv .venv; .venv\Scripts\Activate.ps1; pip install -r requirements.txt
Copy-Item .env.example .env          # completar PG_PASSWORD (y PG_PORT si usas Docker, ver sección 2)
python main.py                       # todo el pipeline; sin PostgreSQL igual genera data/gold
pytest                               # pruebas, sin red
```

Luego, para ver los resultados: las tablas quedan en `data/gold` (y en el esquema `gold` de PostgreSQL), las figuras del EDA en
`docs/eda` y el tablero se arma con la sección 9.

## 1. Instalación (PowerShell)

Requiere Python 3.11 o superior (probado con 3.14).

```powershell
cd avance

# Crear y activar el entorno virtual
python -m venv .venv
.venv\Scripts\Activate.ps1

# Instalar dependencias
pip install -r requirements.txt
```

## 2. Configuración de `.env`

El archivo `.env` **nunca se versiona**. Se parte de la plantilla:

```powershell
Copy-Item .env.example .env
```

| Variable | Para qué sirve |
|---|---|
| `DATABASE_URL` | Cadena de conexión completa, p. ej. `postgresql+psycopg2://usuario:clave@localhost:5434/zni_energia`. Si se deja vacía se arma con las variables `PG_*`. |
| `PG_HOST`, `PG_PORT`, `PG_DATABASE`, `PG_USER`, `PG_PASSWORD` | Datos de PostgreSQL (se usan solo si `DATABASE_URL` está vacía). |
| `SOCRATA_APP_TOKEN` | Opcional. Token de datos.gov.co para evitar límites de tasa. |

Si la base de datos no existe, la etapa `load` intenta crearla. **Ojo con el puerto**: los valores por defecto
(`localhost:5432`) pueden apuntar al PostgreSQL de otro proyecto; usa una base dedicada. Una forma rápida con Docker:

```powershell
docker run -d --name zni-postgres -e POSTGRES_PASSWORD=cambia_esta_clave -e POSTGRES_DB=zni_energia -p 5434:5432 postgres:17-alpine
```

y en `.env`: `PG_PORT=5434` y `PG_PASSWORD=cambia_esta_clave`.

## 3. Cómo correr el pipeline

**Un solo comando reproduce todo desde cero** (perfilado → extracción → silver → gold → carga a PostgreSQL → análisis exploratorio):

```powershell
python main.py
```

O por etapas:

```powershell
python main.py --etapa perfilar   # perfila las 3 fuentes            -> logs/perfilado/*.csv
python main.py --etapa extract    # descarga desde la API            -> data/bronze/*.parquet
python main.py --etapa silver     # limpieza + pruebas de calidad    -> data/silver/*.parquet
python main.py --etapa gold       # modelo analítico y KPI           -> data/gold/*.parquet y *.csv
python main.py --etapa load       # carga gold a PostgreSQL
python main.py --etapa load --incluir-silver   # carga también silver
python main.py --etapa eda        # análisis exploratorio (Matplotlib) -> docs/eda (lee data/gold; no necesita PostgreSQL)
```

- Cada etapa captura sus errores **sin tumbar el pipeline**: se cuentan como *errores controlados*, se escriben en
  `logs/pipeline.log` y las etapas que dependen de una etapa fallida (p. ej. `silver` si falló `extract`) se omiten.
- Código de salida: `0` sin errores, `1` si hubo al menos un error controlado (p. ej. PostgreSQL no disponible: en ese
  caso gold igual queda generado en `data/gold`).
- Los módulos también se pueden correr sueltos: `python src/extract/extract_excel.py`, `python src/transform/clean_excel.py`,
  `python src/transform/gold_transformations.py`, `python src/load/load_database.py`.
- **Respaldo manual**: si la API no responde, `extract` busca `data/bronze/<fuente>.csv` o `.xlsx` descargados a mano
  (`prestacion`, `operacion_diaria`, `pqr`).
- Tiempos aproximados: extracción ≈ 2 min (operacion_diaria son 455 mil filas), silver ≈ 2 s, gold ≈ 5 s, carga de gold ≈ 3 s, análisis exploratorio ≈ 5 s.
- La etapa `eda` depende de `gold` y no de `load`: si PostgreSQL no está disponible, el análisis igual se genera.

## 4. Las fuentes y lo que se encontró al perfilarlas

| Clave | Id Socrata | Dueño | Granularidad real | Llave validada (0 duplicados) | Cobertura observada (4 departamentos) | Frescura |
|---|---|---|---|---|---|---|
| `prestacion` | 3ebi-d83g | MinEnergía / IPSE | localidad × mes | `id_localidad` + nombre normalizado + `anio` + `mes` | 2020-01 a 2026-01 (73 meses) | desactualizada |
| `operacion_diaria` | qwe5-ycap | Superservicios | localidad × día × generador | `codigo_localidad` + `fecha` + `serie_generador` | 2021-07 a 2022-03 (9 meses) | congelada |
| `pqr` | 5wua-nr2d | Superservicios | caso individual (se agrega a municipio-semestre-empresa) | llave agregada: `id_mpio` + año + semestre + `identificador_empresa` (las filas crudas son casos, no se espera unicidad) | 2021-07 a 2022-06 y 2023-01 a 2023-06 | congelada |

Campos de geografía: `prestacion` usa `id_dpto`/`id_mpio`/`id_localidad` (los campos sin `id_` son nombres); `operacion_diaria` usa
`codigo_localidad` (los `dane_nom_*` son nombres); `pqr` usa `car_t1554_dane_depto` + `car_t1554_dane_mpio` (los `dane_nom_*` son nombres).

El perfilado contra la API real ajustó varios supuestos del documento de diseño. Todos están documentados con su
evidencia en `config/config.yaml` (secciones `notas` y `decisiones_de_diseno`):

1. **`pqr` es de empresas de GAS, no de energía eléctrica.** Todas las empresas de `are_esp_nombre` son distribuidoras de gas
   y `identificador_empresa` coincide en **0 %** con `operacion_diaria`. Se mantiene la fuente pero, siguiendo la regla de respaldo
   del diseño, la relación operador–PQR se limita al **municipio**. Los conteos de PQR son contexto municipal de servicios
   públicos, **no** quejas del servicio de energía.
2. **`prestacion` ↔ `operacion_diaria` no se unen por el código de localidad completo**: `codigo_localidad` tiene 13 dígitos
   (municipio 5 + centro poblado 3 + consecutivo 5). Cuando el centro poblado es distinto de `000`, los primeros 8 dígitos son el
   `id_localidad` de prestacion (validado contra los nombres: 38 de 38 coinciden); con `000` solo se relacionan por municipio.
   Son enlazables 38 de las 73 localidades.
3. **Un código DANE de localidad puede agrupar varias localidades con nombre distinto** (15 de 73 códigos). No son duplicados:
   sus valores difieren. La entidad localidad es `(id_localidad, nombre normalizado)`; con esa llave no hay duplicados.
4. **La cobertura real es menor que las fechas del portal.** El portal dice que `operacion_diaria` se actualizó en jun-2023 y `pqr`
   en mar-2024, pero sus datos terminan en 2022-03 y 2023-06. La comparabilidad usa la cobertura observada.
   Además, `pqr` no tiene datos del semestre 2022-2.
5. **Cambio de formato en `prestacion` (2025-12 y 2026-01)**: `prom_diario_horas` viene multiplicado por 100 (776 = 7.76 h) y
   `potencia_maxima` en una escala inconsistente. Las horas se reescalan y se marcan (validado con la energía: 99 % de las filas queda
   entre 0.5× y 2× de la potencia media histórica de su localidad); la potencia de esas filas **se excluye** porque no se puede corregir
   de forma fiable. Configurable en `plausibilidad`.
6. `3ebi-d83g` tiene dos fechas distintas: último periodo con datos **ene-2026** y última actualización del portal **2026-03-13**.

## 5. Modelo gold

Todas las tablas de datos (`dim_*`, `fact_*`, `puente_*`, `ind_*`) llevan las columnas de **frescura** (`fecha_corte_fuente`,
`estado_frescura`, `es_comparable`) y de **trazabilidad** (`fuentes_origen`, `fecha_carga`, `lote_id`, `reglas_aplicadas`).
Los periodos no comparables **se marcan, no se descartan**.

`fecha_carga` está en UTC. La *fecha de referencia* con la que se mide el retraso de cada fuente es el día de la carga a bronze en
hora de Colombia (`frescura.zona_horaria_referencia` en `config.yaml`), así que el retraso crece con el paso del tiempo aunque los
datos de origen no cambien; con los mismos datos de origen y la misma fecha de referencia, gold siempre queda idéntico.

| Tabla | Grano | Descripción |
|---|---|---|
| `dim_municipio` | municipio | 133 municipios que aparecen en alguna fuente, con departamento. |
| `dim_localidad` | localidad (código + nombre) | 97 localidades de prestacion; `codigo_compartido` indica si comparte código DANE. |
| `fact_prestacion` | localidad × mes | Energía, potencia y horas de servicio (validadas, con los valores reportados al lado), `con_servicio`, operador del mes y `estado_operador`. |
| `fact_pqr` | municipio × semestre × empresa | Casos de PQR, con respuesta, % con respuesta y días promedio de respuesta. |
| `puente_operador_localidad` | código de operación × operador | Relación operador–localidad con **vigencia observada** (`vigente_desde`, `vigente_hasta`) y `nivel_enlace` (`localidad` o `municipio`). |
| `ind_localidades_con_servicio` | departamento × mes | Localidades reportadas / con servicio (energía activa > 0). |
| `ind_horas_servicio_departamento`, `ind_horas_servicio_municipio` | dep./municipio × mes | Horas de servicio promedio, energía y potencia. |
| `ind_brechas_horas_servicio` | departamento o municipio × año | `brecha_horas = 24 − horas promedio` y ranking (1 = mayor brecha). |
| `ind_evolucion_mensual` | región o departamento × mes | Serie mensual con variación mensual e interanual. |
| `ind_operador_localidad`, `ind_comparacion_operadores` | localidad × operador / operador | Horas de servicio por operador (solo localidades enlazables y meses con cobertura). |
| `ind_pqr_vs_horas_municipio` | municipio × semestre | Unión prestacion ↔ PQR: horas del municipio frente a casos de PQR. |
| `ind_pqr_empresa_municipio` | municipio × semestre × empresa | PQR por empresa-municipio con las horas de servicio de su municipio. |
| `ind_peor_desempeno_municipio`, `ind_localidades_menos_horas` | municipio / localidad | Peor desempeño combinado (percentil de brecha + percentil de PQR; ranking 1 = peor) y localidades con menos horas. |
| `meta_fuentes` | fuente | Cobertura, retraso y **advertencia de frescura** por fuente para mostrar en el tablero. |
| `meta_uniones` | unión × prueba | Resultado de cada prueba de calidad ejecutada antes de cada unión. |
| `kpis_pipeline` | indicador | Los 8 KPI (también en `data/gold/kpis_pipeline.csv`). |

**Estados que conviene conocer en Power BI**

- `estado_operador` (en `fact_prestacion`): `con dato`; `sin dato vigente` (el mes está fuera de la cobertura de operacion_diaria);
  `sin enlace por codigo` (hay cobertura pero la localidad no se puede enlazar por código); `sin registro en el mes`.
- `estado_pqr` (en `ind_pqr_vs_horas_municipio`): `con dato`; `sin registro en periodo cubierto` (el semestre está cubierto y el municipio
  no tiene casos: el conteo es 0); `sin dato vigente` (semestre fuera de cobertura: el conteo es nulo, no cero).
- `estado_frescura`: `vigente` (hasta 2 periodos de retraso), `desactualizada` (más de 2) o `congelada` (fuente sin actualización nominal).

**Relaciones sugeridas en Power BI**: `dim_localidad[clave_localidad]` → `fact_prestacion`, `puente_operador_localidad`,
`ind_operador_localidad`; `dim_municipio[id_municipio]` → `dim_localidad`, `fact_pqr`, `ind_*_municipio`.
Se conecta con *Obtener datos → Base de datos PostgreSQL* (esquema `gold`) o leyendo los `.csv` de `data/gold`.

## 6. Uniones y pruebas de calidad

Antes de construir cada unión se ejecutan las pruebas de la sección 5 del diseño (`src/transform/quality_checks.py`); las
bloqueantes (unicidad de llave y validez DANE) impiden construirla. El resultado queda en `gold.meta_uniones`.

| Unión | Nivel | Resultado con los datos actuales |
|---|---|---|
| prestacion ↔ operacion_diaria | localidad (prefijo DIVIPOLA) + mes | **Implementada con tratamiento**: hay localidades-mes con 2 operadores, se asigna el de mayor energía generada. Solo para localidades enlazables y meses con cobertura. |
| prestacion ↔ pqr | municipio + semestre | **Implementada con tratamiento**: hasta 6 empresas por municipio-semestre; la PQR se agrega (suma de empresas) antes de unir y nunca se asigna a una localidad. |
| operacion_diaria ↔ pqr | municipio + empresa | **Por empresa NO implementada** (0 % de identificadores en común, exigido ≥ 95 %); la relación se limita al municipio. |

## 7. KPI del pipeline (`data/gold/kpis_pipeline.csv`)

| KPI | Cómo se mide | Meta | Valor actual |
|---|---|---|---|
| `pct_fuentes_integradas` | Fuentes con registros en el modelo gold / fuentes configuradas | ≥ 100 % | 100 % |
| `pct_variables_estandarizadas` | Variables clave de silver con el tipo/formato esperado (30 evaluadas) | ≥ 100 % | 100 % |
| `pct_registros_duplicados` | Filas duplicadas en las llaves declaradas de gold | ≤ 1 % | 0 % |
| `pct_registros_con_trazabilidad` | Registros gold con fuente, fecha de carga, lote y regla aplicada | ≥ 100 % | 100 % |
| `pct_campos_criticos_completos` | Registros con todos sus campos críticos; se reporta la **peor** fuente | ≥ 98 % | 100 % |
| `numero_errores_transformacion` | Errores controlados en la corrida | 0 | 0 |
| `pct_reglas_negocio_documentadas` | Reglas escritas en `reglas_aplicadas` que están en el registro de `config.yaml` | ≥ 100 % | 100 % |
| `pct_informacion_reproducible` | Tablas idénticas en dos construcciones independientes | ≥ 100 % | 100 % |

Las metas salen de `config/config.yaml` (`kpis_metas` y `umbrales_calidad`).

## 8. Análisis exploratorio (EDA) y presentación

El EDA responde las seis preguntas del MVP del documento de diseño (sección 6.1) y documenta la calidad y la cobertura de los datos.
Todo sale del modelo gold, las mismas tablas que se cargan a PostgreSQL.

```powershell
python main.py --etapa eda                  # 16 figuras, tablas de apoyo y hallazgos       -> docs/eda
python src/eda/run_eda.py --diapositivas    # figuras de la presentación (sin título ni pie) -> docs/presentacion/figuras
```

| Entregable | Dónde | Qué es |
|---|---|---|
| 16 figuras (Matplotlib) | `docs/eda/figuras/` | Una por hallazgo: preanálisis (frescura, cobertura, mapa de reporte, distribuciones, concentración, correlaciones), las seis preguntas (P1 a P6) y contexto de operación diaria. Ver [`docs/eda/INDICE.md`](docs/eda/INDICE.md). |
| Tablas de apoyo (CSV) | `docs/eda/tablas/` | La versión en tabla de cada figura (accesibilidad y verificación). |
| Cifras clave | `docs/eda/hallazgos.json` | Todo número del cuaderno y de la presentación se calcula con el mismo código y sale de aquí. |
| Cuaderno | `notebooks/01_eda_zni.ipynb` | Narrativa y figuras, entregado ya ejecutado. Abrirlo con el kernel del entorno virtual (`.venv`). |
| Presentación | `docs/presentacion/` | Las 13 figuras en modo diapositiva y el guion (`guion.md`). La presentación de 20 diapositivas (16 más 4 de anexo) se publicó como una página de Slides y se exporta a PowerPoint o PDF desde su menú. |

Decisiones de diseño (código en `src/eda/`):

- **El título de cada figura es su hallazgo** y las cifras se calculan de los datos (`analysis.py`); nada se escribe a mano.
- **Un color fijo por departamento** (paleta de referencia validada para daltonismo), un solo eje en cada gráfico y etiquetas en tinta neutra.
- **Comparar cada localidad consigo misma.** Entre 14 y 44 de 97 localidades reportan cada mes, así que un promedio de "todas las observaciones" mezcla cambios reales con cambios de *quién reporta*. La evolución se mide como cambio de cada localidad entre 2020-2021 y 2024-2025, con intervalos de confianza del 95 % por remuestreo de localidades.
- **Reproducible:** dos corridas con los mismos datos de gold dan los mismos archivos, byte a byte (el layout de Matplotlib se resuelve una vez y se congela antes de guardar).
- Los umbrales (meses mínimos, ventanas de años, remuestreos, semilla) están en la sección `eda` de `config/config.yaml`.

**Hallazgos principales** (corte de datos ene-2026; el detalle y las salvedades están en el cuaderno):

1. **El servicio es corto en toda la región:** en el último año con datos las localidades recibieron en promedio 7,8 de 24 horas diarias; Cauca y Nariño, menos de 7.
2. **La brecha se concentra en la costa pacífica de Nariño y Cauca:** Magüí recibe 1,9 horas y 5 de las 8 localidades con menos horas son suyas.
3. **No hay mejora generalizada:** de 26 localidades comparables solo Puerto Merizalde (de 7 a 22 horas) y Pital de la Costa mejoraron mucho; el cambio mediano es de +0,3 horas y no se distingue de cero. El salto de Valle del Cauca en los promedios por departamento es una sola localidad.
4. **Diciembre es el mejor mes (+0,6 horas) y enero el peor (−0,5);** los intervalos de ambos no incluyen el cero.
5. **Los datos limitan las conclusiones:** `prestacion` lleva 8 meses sin datos nuevos, las otras dos fuentes están congeladas, las PQR son de gas y los dos extremos de la comparación entre operadores se miden con una sola localidad.

## 9. Tablero de Power BI

El tablero (resultado clave 4 del diseño) lee las tablas de `gold` en PostgreSQL. El archivo `.pbix` **no se versiona** (es un binario
que contiene una copia de los datos): se entrega aparte, junto con su exportación a PDF. Esta sección permite reconstruirlo desde cero.

**Requisitos:** Power BI Desktop (Windows), la base `zni_energia` cargada (`python main.py`) y el contenedor encendido
(`docker start zni-postgres`).

### 9.1 Conectar los datos

1. *Inicio → Obtener datos → Base de datos PostgreSQL*. Servidor `localhost:5434`, base `zni_energia`, modo **Importar**.
2. Credenciales de tipo *Base de datos*: usuario y contraseña del `.env`. Si pide cifrado, conectar sin cifrar (el contenedor local no usa SSL).
3. Marcar las 19 tablas del esquema `gold` y pulsar **Load** (no hace falta *Transform Data*). Power BI las nombra `gold <tabla>`, por eso las
   fórmulas DAX de abajo las citan entre comillas simples.
4. Plan B si falla el conector (instalar Npgsql): *Obtener datos → Texto/CSV* sobre los `.csv` de `data/gold`.
5. Desmarcar *Archivo → Opciones → Archivo actual → Carga de datos → Detectar automáticamente nuevas relaciones*; si no, Power BI cruza casi
   todas las tablas por tener columnas con el mismo nombre (`id_municipio`, `id_localidad`).

### 9.2 Modelo

Cuatro relaciones de estrella (*muchos a uno*, filtro en una dirección, activas):

| Tabla "uno" | Tabla "varios" | Columna |
|---|---|---|
| `dim_municipio` | `dim_localidad` | `id_municipio` |
| `dim_municipio` | `fact_pqr` | `id_municipio` |
| `dim_localidad` | `fact_prestacion` | `clave_localidad` |
| `dim_localidad` | `puente_operador_localidad` | `clave_localidad` |

Las tablas `ind_*`, `meta_*` y `kpis_pipeline` **no tienen relaciones**: ya vienen agregadas con sus propios nombres. Por eso un segmentador
sobre una de ellas filtra solo esa tabla. Para que **un único selector de mes** filtre las páginas mensuales hay una tabla `Calendario`
(*Modelado → Nueva tabla*) relacionada con la columna `periodo` de `ind_evolucion_mensual`, `ind_horas_servicio_departamento`,
`ind_horas_servicio_municipio`, `ind_localidades_con_servicio` y `fact_prestacion` (otras cinco relaciones, nueve en total):

```DAX
Calendario = SELECTCOLUMNS(GENERATESERIES(0, 83), "Mes", EDATE(DATE(2020,1,1), [Value]))
```

La columna `Mes` se formatea `yyyy-MM`; en los segmentadores se usa `Mes` y no *Date Hierarchy*.

### 9.3 Medidas DAX

```DAX
% con servicio =
VAR conServicio = CALCULATE(SUM('gold ind_evolucion_mensual'[n_localidades_con_servicio]), 'gold ind_evolucion_mensual'[nivel_geografico] = "region")
VAR reportadas  = CALCULATE(SUM('gold ind_evolucion_mensual'[n_localidades_reportadas]),  'gold ind_evolucion_mensual'[nivel_geografico] = "region")
RETURN DIVIDE(conServicio, reportadas)

Aviso prestación = LOOKUPVALUE('gold meta_fuentes'[advertencia], 'gold meta_fuentes'[fuente], "prestacion")
Aviso PQR        = LOOKUPVALUE('gold meta_fuentes'[advertencia], 'gold meta_fuentes'[fuente], "pqr")

KPIs cumplidos = CALCULATE(COUNTROWS('gold kpis_pipeline'), 'gold kpis_pipeline'[cumple] = TRUE()) & " de " & COUNTROWS('gold kpis_pipeline')
```

Más una columna calculada en `kpis_pipeline`: `Estado = IF('gold kpis_pipeline'[cumple], "✔ Cumple", "✘ No cumple")`.
El `% con servicio` se calcula como medida (suma de localidades con servicio entre suma de reportadas) y **no** como promedio de
`pct_localidades_con_servicio`, que daría el mismo peso a meses con pocas localidades.

### 9.4 Páginas

**Tema visual:** [`powerbi/tema_zni.json`](powerbi/tema_zni.json) (*Vista → Temas → Buscar temas*). Usa los mismos colores por departamento
que las figuras del EDA (Cauca azul, Nariño naranja, Putumayo ámbar, Valle del Cauca aqua), fondo gris claro y visuales en tarjetas blancas.

| Página | Qué muestra | Tablas |
|---|---|---|
| 1. Estado actual | Selector de mes (por defecto 2026-01); tarjetas de horas promedio, localidades con servicio, energía y `% con servicio` (región); barras de horas por departamento | `ind_evolucion_mensual`, `ind_horas_servicio_departamento` |
| 2. Brechas | Selector de año; brecha de horas (`24 − horas`) por departamento y 10 municipios con mayor brecha | `ind_brechas_horas_servicio` |
| 3. Evolución | Líneas de horas promedio por departamento y región; energía activa de la región; nota sobre las caídas de Puerto Leguízamo | `ind_evolucion_mensual` |
| 4. Operadores | Horas promedio por operador, comparación y detalle operador × localidad | `ind_comparacion_operadores`, `ind_operador_localidad` |
| 5. PQR | Dispersión horas vs. PQR por municipio (eje Y limitado a 60; Tumaco, con ~767 casos, queda fuera) y tabla de semestres | `ind_pqr_vs_horas_municipio` |
| 6. Peor desempeño | Ranking de peor desempeño combinado y localidades con menos horas | `ind_peor_desempeno_municipio`, `ind_localidades_menos_horas` |
| 7. Calidad y frescura | Frescura de las fuentes, los 8 KPI (`8 de 8` cumplen) y las pruebas por unión | `meta_fuentes`, `kpis_pipeline`, `meta_uniones` |

Todas las páginas llevan las tarjetas de **aviso de frescura** (`Aviso prestación` y, donde se usa PQR, `Aviso PQR`) porque dos de las
tres fuentes están congeladas y la principal está desactualizada.

**Vista previa** (exportada desde Power BI; las imágenes están en [`imagenes/tablero/`](imagenes/tablero)):

![Página 1: estado actual del servicio](imagenes/tablero/pagina_1_estado_actual.png)

| | |
|---|---|
| ![Página 2: brechas](imagenes/tablero/pagina_2_brechas.png) | ![Página 3: evolución](imagenes/tablero/pagina_3_evolucion.png) |
| ![Página 4: operadores](imagenes/tablero/pagina_4_operadores.png) | ![Página 5: PQR](imagenes/tablero/pagina_5_pqr.png) |
| ![Página 6: peor desempeño](imagenes/tablero/pagina_6_peor_desempeno.png) | ![Página 7: calidad y frescura](imagenes/tablero/pagina_7_calidad_frescura.png) |

### 9.5 Cómo leerlo

- **Las caídas de energía en la página 3 no son caídas del servicio:** Puerto Leguízamo (~65 % de la energía) no reportó en 24 de 73 meses.
- **PQR son de gas** y se unen a las horas de servicio solo por municipio y semestre: es una asociación descriptiva, no causal. Solo
  13 municipios tienen dato comparable (`es_comparable = True`).
- **En la página 7 hay pruebas con `aprobado = False` y es lo esperado.** `identificador_empresa_comun` (0 % de coincidencia entre
  operacion_diaria y pqr) hace que esa unión quede solo por municipio, y las dos de `cardinalidad_maxima` (hasta 2 operadores por
  localidad-mes y 6 empresas por municipio-semestre) se resuelven con el tratamiento descrito en la sección 6.
- **Buenaventura sale con 10,80 h en la página 6 y 10,13 h en la 5:** una pondera por observaciones y la otra es el promedio simple de semestres.
- Los municipios con pocos `n_meses` (p. ej. El Rosario, un solo mes) tienen promedios poco confiables.

### 9.6 Actualizar y problemas frecuentes

- Para refrescar: correr `python main.py` (recarga PostgreSQL) y en Power BI *Inicio → Actualizar*.
- *No conecta:* comprobar que el contenedor esté encendido (`docker ps`) y que el puerto sea el de `PG_PORT`.
- *Un visual sale vacío:* revisar el panel *Filters*. Los filtros automáticos `Sum of … is (All)` sobre campos agregados pueden dejarlo sin
  filas; se borran y se filtra por `es_comparable` o `estado_pqr`.
- *Valores sumados sin sentido (“Sum of …”, totales raros):* en tablas de una fila por entidad, usar **Don't summarize** y apagar los totales.
- *Un segmentador no filtra otra tabla:* es normal, las tablas `ind_*` no están relacionadas (ver 9.2).

## 10. Pruebas

```powershell
pytest            # o: python -m pytest
```

220 pruebas, sin red (fixtures pequeñas y mocks): `tests/test_extract.py` (paginación, reintentos con backoff, token, respaldo local),
`tests/test_transform.py` (normalización DANE, deduplicación, mes → semestre, frescura y `es_comparable`, filtro por departamentos,
reglas de validación, compuertas de calidad por unión, KPI, orquestador) y `tests/test_quality.py` (las cinco pruebas y sus umbrales).
`tests/test_eda.py` (114 pruebas) corre el EDA sobre un mini-mundo sintético que pasa por los mismos limpiadores y por la construcción real de gold:
cálculos, formato es-CO, las 16 figuras, la reproducibilidad de los PNG, la calibración de los intervalos de confianza, hallazgos, orquestador y que el cuaderno se entregue ejecutado.
Se verificó con pruebas de mutación: 14 comportamientos del pipeline rotos a propósito (los 14 detectados) y 20 del EDA (los 20 detectados, tras agregar
dos pruebas para las dos primeras mutaciones que habían sobrevivido).

## 11. Limitaciones conocidas

- Los casos de PQR son de distribuidoras de gas; el indicador de peor desempeño combinado los usa solo como contexto municipal y no normaliza por población (no hay fuente de población en el alcance del MVP).
- El operador solo se puede asignar a 38 de las 73 localidades y en 9 meses (2021-07 a 2022-03): la pregunta "qué operador presta el servicio en cada localidad" solo es respondible para ese subconjunto.
- Los reportes de `prestacion` no son completos mes a mes: el número de localidades que reportan (código DANE + nombre, la entidad del modelo) va de 14 a 44 según el mes, y Puerto Leguízamo (~65 % de la energía acumulada) no reportó en 24 de los 73 meses. Por eso la serie de energía total tiene caídas bruscas que no son un error del pipeline; interprétese junto con `n_localidades_reportadas`.
- La potencia máxima de 2025-12 y 2026-01 no está disponible (se excluye por el cambio de formato de la fuente).
- No se usa catálogo DIVIPOLA: la validez DANE verifica el formato y la jerarquía, no la pertenencia a un catálogo oficial.
- Dos fuentes están congeladas y la principal está desactualizada (8 periodos de retraso a 2026-09-30): el tablero debe mostrar las advertencias de `meta_fuentes`.
- La evolución solo se puede medir en las localidades con datos en ambos periodos (26 de 97): con tan pocas, el cambio mediano (+0,3 horas, intervalo del 95 %: −0,6 a +1,0) no se distingue de cero.
- Las horas de `operacion_diaria` no sirven para medir el servicio: el 96 % de los registros declara 4, 5 u 8 horas y el 96 % del tiempo de servicio figura como calculado. Por eso las horas del análisis salen de `prestacion`.
- El archivo `.pbix` del tablero no se versiona (binario con datos incrustados); la sección 9 explica cómo reconstruirlo. Las capturas de `imagenes/tablero/` salen de su exportación a PDF.

## 12. Autor

Simon Colonia Amador — Universidad Autónoma de Occidente, Facultad de Ingeniería y Ciencias Básicas.

Los datos provienen de [datos.gov.co](https://www.datos.gov.co) (MinEnergía / IPSE y Superservicios) y se usan bajo sus licencias de datos abiertos.
El código se distribuye bajo licencia MIT (ver [LICENSE](LICENSE)).
