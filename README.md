# Monitoreo del servicio de energía en ZNI (suroccidente colombiano)

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

## 1. Instalación (PowerShell)

Requiere Python 3.11 o superior (probado con 3.14).

```powershell
cd C:\Users\simon\Documents\avance

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

## 9. Pruebas

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

## 10. Limitaciones conocidas

- Los casos de PQR son de distribuidoras de gas; el indicador de peor desempeño combinado los usa solo como contexto municipal y no normaliza por población (no hay fuente de población en el alcance del MVP).
- El operador solo se puede asignar a 38 de las 73 localidades y en 9 meses (2021-07 a 2022-03): la pregunta "qué operador presta el servicio en cada localidad" solo es respondible para ese subconjunto.
- Los reportes de `prestacion` no son completos mes a mes: el número de localidades que reportan (código DANE + nombre, la entidad del modelo) va de 14 a 44 según el mes, y Puerto Leguízamo (~65 % de la energía acumulada) no reportó en 24 de los 73 meses. Por eso la serie de energía total tiene caídas bruscas que no son un error del pipeline; interprétese junto con `n_localidades_reportadas`.
- La potencia máxima de 2025-12 y 2026-01 no está disponible (se excluye por el cambio de formato de la fuente).
- No se usa catálogo DIVIPOLA: la validez DANE verifica el formato y la jerarquía, no la pertenencia a un catálogo oficial.
- Dos fuentes están congeladas y la principal está desactualizada (8 periodos de retraso a 2026-09-30): el tablero debe mostrar las advertencias de `meta_fuentes`.
- La evolución solo se puede medir en las localidades con datos en ambos periodos (26 de 97): con tan pocas, el cambio mediano (+0,3 horas, intervalo del 95 %: −0,6 a +1,0) no se distingue de cero.
- Las horas de `operacion_diaria` no sirven para medir el servicio: el 96 % de los registros declara 4, 5 u 8 horas y el 96 % del tiempo de servicio figura como calculado. Por eso las horas del análisis salen de `prestacion`.
- El tablero de Power BI (resultado clave 4 del diseño) no forma parte de este repositorio.

## 11. Equipo

Simon Colonia Amador, Ingrid Valentina y Willy Daniel — Universidad Autónoma de Occidente, Facultad de Ingeniería y Ciencias Básicas.
