# Informe final: Monitoreo del servicio de energía en las ZNI del suroccidente colombiano

**Universidad Autónoma de Occidente — Facultad de Ingeniería y Ciencias Básicas — ETL**
**Equipo:** Simon Colonia Amador, Ingrid Valentina y Willy Daniel
**Entrega final:** 2 de octubre de 2026 · **Corte de los datos:** enero de 2026 (fecha de referencia 2026-09-30)

> Este informe reemplaza el documento de avance (`docs/Avance_2_Proyecto_ETL_2026_V4.pdf`), que se conserva sin cambios. Reproduce
> su estructura (contexto, fuentes, matriz 4.1, frescura, herramientas, OKR, preguntas) y registra lo que cambió al validar el
> diseño con los datos reales. El código y la documentación técnica están en el [README](README.md).

## 1. Resumen ejecutivo

Se construyó un pipeline ETL reproducible con un solo comando (`python main.py`) que integra tres conjuntos de datos abiertos de
datos.gov.co sobre el servicio de energía en las Zonas No Interconectadas (ZNI) de **Valle del Cauca, Cauca, Nariño y Putumayo**,
los limpia en una arquitectura bronze → silver → gold, los carga en PostgreSQL y los entrega a un tablero de Power BI de siete páginas.

| Resultado | Valor |
|---|---|
| Fuentes integradas | 3 de 3 (`prestacion`, `operacion_diaria`, `pqr`) |
| Registros procesados (silver) | 2.327 de prestación, 250.386 de operación diaria y 9.282 de PQR |
| Tablas del modelo gold | 19 (más `kpis_pipeline.csv`), todas con trazabilidad y marca de frescura |
| KPI del pipeline | 8 de 8 cumplen su meta |
| Pruebas automáticas | 220 pasan, sin red; mutación: 14 de 14 fallos del pipeline detectados y 20 de 20 del EDA |
| Reproducibilidad | Dos construcciones independientes producen tablas idénticas (huella por tabla) |
| Análisis | 16 figuras, cuaderno ejecutado y presentación (`docs/eda`, `notebooks`, `docs/presentacion`) |
| Tablero | 7 páginas en Power BI con advertencias de frescura en cada una |

**Hallazgo principal.** El servicio es corto en toda la región: en los últimos doce meses con datos las localidades recibieron en
promedio **7,8 de 24 horas diarias**, y Cauca y Nariño menos de 7. No hay una mejora generalizada entre 2020-2021 y 2024-2025.

**Advertencia principal.** Dos de las tres fuentes están congeladas y la principal lleva ocho periodos sin datos nuevos. Las
conclusiones describen el estado a enero de 2026 y la brecha entre fuentes, no el estado actual.

## 2. Contexto, usuario y problema

*Se mantienen sin cambios respecto al avance.* En las ZNI (Ley 855 de 2003) el servicio lo prestan operadores locales con plantas
diésel, pequeñas centrales o sistemas solares; muchas localidades reciben solo algunas horas al día. La información está dispersa y
se publica en formatos y periodicidades distintos.

El usuario primario es un analista de política energética (MinEnergía / IPSE) que necesita indicadores consolidados, comparables y
actualizados para priorizar inversión del FAZNI, sin acceso directo a datos crudos. Como usuarios secundarios, los operadores
locales y los gobiernos municipales. El árbol del problema está en el documento de avance.

## 3. Fuentes y matriz de granularidad y llaves (4.1 actualizada)

La matriz del avance usaba llaves candidatas. Esta es la versión **validada con los datos reales**: ninguna unión se construyó
antes de pasar las pruebas de la sección 3.2.

### 3.1 Matriz de granularidad y llaves

| Fuente | Granularidad real | Llave validada (0 duplicados) | Cobertura observada (4 departamentos) | Rol en el modelo |
|---|---|---|---|---|
| `prestacion` (3ebi-d83g) | Localidad × mes | `id_localidad` + nombre de localidad normalizado + año + mes | 2020-01 a 2026-01 (73 meses) | Hechos: energía activa y reactiva, potencia máxima y horas de servicio. Base del modelo |
| `operacion_diaria` (qwe5-ycap) | Localidad × día × generador | `codigo_localidad` + fecha + `serie_generador` | 2021-07 a 2022-03 (9 meses) | Relación operador–localidad con vigencia observada |
| `pqr` (5wua-nr2d) | Caso individual; se agrega a municipio × semestre × empresa | Llave agregada: municipio + año + semestre + empresa | 2021-07 a 2022-06 y 2023-01 a 2023-06 | Hechos de PQR, solo a nivel de municipio |

### 3.2 Pruebas previas a las uniones (resultados en `gold.meta_uniones`)

| Prueba | Criterio | Resultado |
|---|---|---|
| Unicidad de la llave | 0 duplicados | Cumple en las tres fuentes (con las llaves de la tabla anterior) |
| Validez del código DANE | ≥ 95 % | 100 % de formato y jerarquía válidos (5 dígitos de municipio; 8 de localidad) |
| Cruce entre fuentes | % sin cruce documentado | 47,95 % de localidades de prestación sin operador enlazable; 55,56 % de municipio-semestre de prestación sin PQR; 25 % de municipios de operación diaria sin PQR |
| Identificador de empresa común | ≥ 95 % de coincidencia | **0 %: no cumple.** La unión operador–PQR se limita al municipio, como preveía la regla de respaldo del diseño |
| Cardinalidad | Observada frente a esperada | Hasta 2 operadores por localidad-mes y hasta 6 empresas por municipio-semestre; ambos casos se tratan antes de unir |

### 3.3 Uniones: lo previsto y lo construido

| Unión | Previsto | Construido |
|---|---|---|
| Prestación ↔ operación diaria | Localidad + mes | **Implementada con tratamiento.** Se une por los primeros 8 dígitos del código de localidad cuando el centro poblado no es `000`: 38 de las 73 localidades y 9 meses. Con 2 operadores en un mes se asigna el de mayor energía generada |
| Prestación ↔ PQR | Municipio + semestre | **Implementada.** La PQR se agrega por municipio-semestre antes de unir y nunca se asigna a una localidad |
| Operación diaria ↔ PQR | Municipio + empresa | **No implementada por empresa** (0 % de identificadores comunes). Solo municipio |

Se mantiene la regla de no unir nunca por nombre en texto libre ni asignar PQR a localidades individuales.

## 4. Política de frescura

La política del avance se aplicó con las fechas de corte **observadas** en los datos, no con las del portal.

| Fuente | Último periodo con datos | Fecha de corte | Retraso a 2026-09-30 | Estado |
|---|---|---|---|---|
| `prestacion` | 2026-01 | 2026-01-31 | 8 periodos | Desactualizada |
| `operacion_diaria` | 2022-03 | 2022-03-31 | 9 periodos | Congelada |
| `pqr` | 2023-06 | 2023-06-30 | 6,5 periodos | Congelada |

Cada registro de gold lleva `fecha_corte_fuente`, `estado_frescura` y `es_comparable`. Los periodos no comparables **se marcan y no se
descartan**. El tablero muestra la advertencia de cada fuente en cada página.

## 5. Arquitectura y herramientas

```
API Socrata → perfilar → extract (bronze) → silver → gold → load (PostgreSQL) → Power BI
                                                     └→ eda (Matplotlib, cuaderno)
```

| Etapa | Herramienta | Uso real |
|---|---|---|
| Extracción | Socrata API (SoQL), `requests` | Paginación con `$order=:id`, reintentos con espera creciente, token opcional y respaldo local por CSV/XLSX |
| Transformación | Python y pandas | Tipos, códigos DANE, filtro por departamento, deduplicación exacta, 4 o más reglas registradas por registro, validación de plausibilidad |
| Almacenamiento | PostgreSQL, SQLAlchemy | Esquemas `gold` y `silver`, carga idempotente, llaves e índices, verificación de conteos |
| Orquestación | `main.py` | Etapas encadenadas con errores controlados, registro en `logs/pipeline.log` y código de salida 0/1 |
| Visualización | Power BI | Siete páginas; ver sección 9 |
| Calidad | pytest | 220 pruebas sin red, con pruebas de mutación |

## 6. OKR y KPI: cumplimiento

| KR | Meta | Fecha | Resultado |
|---|---|---|---|
| KR1. Fuentes integradas en PostgreSQL con carga automatizada | 3 de 3 | 5-oct-2026 | **Cumple.** 3 de 3, carga con `python main.py` |
| KR2. DANE válido y cruce; duplicados; campos críticos | ≥ 95 %; ≤ 1 %; ≥ 98 % | 7-oct-2026 | **Cumple.** DANE 100 %; duplicados 0 %; campos críticos 100 % (por registro, peor fuente). Los cruces tienen porcentajes sin cruce documentados (sección 3.2) |
| KR3. Trazabilidad y reproducibilidad | 100 %; 0 errores sin controlar | 8-oct-2026 | **Cumple.** 100 % con fuente, fecha de carga, lote y regla; 0 errores; reproducibilidad 100 % |
| KR4. Tablero con indicadores del MVP y advertencia de frescura | 1 tablero | 9-oct-2026 | **Cumple en contenido.** Tablero de 7 páginas con advertencias; archivo `.pbix` y PDF se entregan aparte (no se versionan) |

### KPI del pipeline (`data/gold/kpis_pipeline.csv`)

| KPI | Meta | Valor |
|---|---|---|
| `pct_fuentes_integradas` | ≥ 100 % | 100 % |
| `pct_variables_estandarizadas` | ≥ 100 % | 100 % (30 variables) |
| `pct_registros_duplicados` | ≤ 1 % | 0 % |
| `pct_registros_con_trazabilidad` | ≥ 100 % | 100 % |
| `pct_campos_criticos_completos` | ≥ 98 % | 100 % |
| `numero_errores_transformacion` | 0 | 0 |
| `pct_reglas_negocio_documentadas` | ≥ 100 % | 100 % |
| `pct_informacion_reproducible` | ≥ 100 % | 100 % |

**KPI del diseño que no figuran en `kpis_pipeline`:**

- *% de indicadores con fuente identificada:* se cumple, pues las 11 tablas `ind_*` llevan `fuentes_origen` sin nulos, pero no se publica como KPI.
- *% de localidades con servicio:* está en el tablero (97,1 % en 2026-01: 34 de 35 localidades reportadas).
- *% de disponibilidad del pipeline:* **no se mide**; exige operar el pipeline durante un periodo y no hay ejecuciones programadas.

## 7. Respuestas a las preguntas del MVP

Cifras de `docs/eda/hallazgos.json` y del tablero. Detalle y salvedades en el cuaderno `notebooks/01_eda_zni.ipynb`.

1. **Estado actual.** En 2026-01 reportaron 35 localidades y 34 tenían servicio. En los últimos doce meses con datos el promedio es de
   7,8 h/día: Cauca 6,3; Nariño 6,6; Valle del Cauca 8,9; Putumayo 14,8 (solo dos localidades).
2. **Brechas.** La mayor está en la costa pacífica de Nariño y Cauca. Magüí recibe 1,9 h; le siguen López de Micay (5,8 h) y El Charco.
   Cinco de las ocho localidades con menos horas son de Magüí.
3. **Evolución.** No hay mejora generalizada. De 26 localidades comparables, 11 mejoran, 10 empeoran y 5 se mantienen; el cambio
   mediano es de +0,3 h y su intervalo de confianza del 95 % (−0,6 a +1,0) incluye el cero. Solo Puerto Merizalde (de 7 a 22 h) y Pital de
   la Costa mejoraron mucho. Diciembre es el mejor mes (+0,6 h) y enero el peor (−0,5 h).
4. **Operadores.** Hay 14 operadores y el operador solo se puede asignar al 52 % de las localidades, entre 2021-07 y 2022-03. El promedio
   ponderado es de 6,9 h. Los dos extremos (13,5 h y 3,1 h) se miden con una sola localidad cada uno, por lo que no son comparables.
5. **PQR.** Son 9.282 casos, 89,5 % con respuesta; Pasto, Ipiales y Tumaco reúnen el 71 %. Son casos de **distribuidoras de gas**, no de energía
   eléctrica. La relación con las horas de servicio es débil (ρ de Spearman 0,11 con 36 pares municipio-semestre) y descriptiva, no causal.
6. **Peor desempeño combinado.** Tumaco encabeza (767 PQR, 17,1 h de brecha), seguido de Olaya Herrera y Francisco Pizarro. Las localidades
   con menos horas son El Rosario (0,4 h), La Isla (1,2 h) y Alto Estero (1,7 h), las tres de Magüí.

## 8. Desviaciones respecto al diseño

Cada una nació de un hallazgo al perfilar las fuentes; la evidencia está en `config/config.yaml` (`notas` y `decisiones_de_diseno`).

| # | El diseño suponía | Lo encontrado | Decisión |
|---|---|---|---|
| 1 | `pqr` mide quejas del servicio de energía | Todas las empresas son distribuidoras de gas; el identificador de empresa coincide 0 % con `operacion_diaria` | Se mantiene como contexto municipal; la unión se limita a municipio |
| 2 | `prestacion` ↔ `operacion_diaria` por código de localidad | El código de operación diaria tiene 13 dígitos (municipio 5 + centro poblado 3 + consecutivo 5) | Se une por los primeros 8 dígitos si el centro poblado no es `000`: 38 de 73 localidades |
| 3 | Una llave de localidad por código DANE | 15 de 73 códigos agrupan localidades con nombres distintos | La entidad es (código, nombre normalizado); con esa llave no hay duplicados |
| 4 | Cortes del portal: `qwe5-ycap` jun-2023 y `5wua-nr2d` mar-2024 | Los datos terminan en 2022-03 y 2023-06; `pqr` no tiene el semestre 2022-2 | La comparabilidad usa la cobertura observada |
| 5 | `3ebi-d83g` con corte único ene-2026 | Hay dos fechas: último periodo con datos (ene-2026) y actualización del portal (2026-03-13) | Se usa el último periodo con datos |
| 6 | Formato estable de `prestacion` | En 2025-12 y 2026-01 las horas vienen ×100 y la potencia en escala inconsistente | Las horas se reescalan y se marcan (validado con la energía); la potencia de esas filas se excluye |
| 7 | Validez DANE frente al catálogo DIVIPOLA | No se incorporó el catálogo | Se valida formato y jerarquía; la pertenencia a un catálogo oficial queda pendiente |
| 8 | Llave de `qwe5-ycap` con operador | La llave única es localidad + fecha + serie del generador | El operador se obtiene por agregación localidad-mes |
| 9 | Horas de `qwe5-ycap` como medida del servicio | El 96 % de los registros declara 4, 5 u 8 horas y el 96 % del tiempo figura como calculado | Las horas del análisis salen de `prestacion` |

## 9. Tablero de Power BI

Siete páginas sobre las tablas de `gold` (modo Importar): 1. Estado actual · 2. Brechas · 3. Evolución · 4. Operadores · 5. PQR ·
6. Peor desempeño · 7. Calidad y frescura. Las instrucciones para reconstruirlo, las medidas DAX y las lecturas recomendadas están en la
sección 9 del [README](README.md#9-tablero-de-power-bi).

Se tomaron estas decisiones de diseño del tablero:

- El `% con servicio` es una medida (suma de localidades con servicio entre suma de reportadas), no un promedio de porcentajes.
- Las tablas `ind_*` no tienen relaciones; un calendario único conecta las páginas mensuales.
- Cada página muestra el aviso de frescura de las fuentes que usa.
- La página de PQR limita el eje a 60 casos y lo declara: Tumaco (≈ 767) quedaría fuera de escala.
- La página de calidad muestra las pruebas no aprobadas (3 de 18) con su explicación, no las oculta.

## 10. Limitaciones

- **Los datos no están al día.** Prestación termina en enero de 2026 y las otras dos fuentes están congeladas; no se puede afirmar el estado actual.
- **Reporte incompleto.** Entre 14 y 44 de las 97 localidades reportan cada mes. Puerto Leguízamo (≈ 65 % de la energía) no reportó en 24 de 73 meses,
  lo que produce caídas bruscas en la energía total que no son un cambio del servicio.
- **Operadores.** Solo 38 de 73 localidades y 9 meses tienen operador asignable.
- **PQR.** Son de gas, no se normalizan por población y no prueban una causa.
- **Potencia máxima.** No está disponible para 2025-12 y 2026-01.
- **Evolución.** Solo es medible en 26 de las 97 localidades; con tan pocas el cambio no se distingue de cero.
- **Sin catálogo DIVIPOLA.** La validez DANE verifica formato y jerarquía.

## 11. Trabajo futuro (fase 2)

Las preguntas de la sección 6.2 del avance siguen requiriendo fuentes adicionales: población por localidad (DANE), proyectos FAZNI/IPSE
históricos, atlas de recursos renovables, costos y metas oficiales de cobertura. Antes de ellas convendría:

1. Incorporar el catálogo DIVIPOLA y validar la pertenencia de los códigos.
2. Programar la ejecución del pipeline y medir la disponibilidad (el KPI pendiente).
3. Solicitar a las entidades el reporte de `operacion_diaria` y `pqr` posterior a 2022 y 2023, o buscar fuentes que lo reemplacen.
4. Buscar una fuente de operador vigente para poder responder la pregunta 4 con datos recientes.

## 12. Reproducir el trabajo

```powershell
git clone https://github.com/Lecho67/avance.git; cd avance
python -m venv .venv; .venv\Scripts\Activate.ps1; pip install -r requirements.txt
Copy-Item .env.example .env       # completar PG_PASSWORD (y PG_PORT si se usa Docker)
python main.py                    # perfilado, extracción, silver, gold, carga y EDA
pytest                            # 220 pruebas
```

Detalles de instalación, configuración de PostgreSQL con Docker, ejecución por etapas y solución de problemas: [README](README.md).

## Anexo A. Tablas del modelo gold

| Tabla | Filas | Grano |
|---|---|---|
| `dim_municipio` | 133 | Municipio |
| `dim_localidad` | 97 | Localidad (código + nombre) |
| `fact_prestacion` | 2.327 | Localidad × mes |
| `fact_pqr` | 519 | Municipio × semestre × empresa |
| `puente_operador_localidad` | 992 | Código de operación × operador, con vigencia |
| `ind_localidades_con_servicio` | 282 | Departamento × mes |
| `ind_horas_servicio_departamento` | 282 | Departamento × mes |
| `ind_horas_servicio_municipio` | 785 | Municipio × mes |
| `ind_brechas_horas_servicio` | 112 | Departamento o municipio × año |
| `ind_evolucion_mensual` | 355 | Región o departamento × mes |
| `ind_operador_localidad` | 29 | Localidad × operador |
| `ind_comparacion_operadores` | 14 | Operador |
| `ind_pqr_vs_horas_municipio` | 153 | Municipio × semestre |
| `ind_pqr_empresa_municipio` | 519 | Municipio × semestre × empresa |
| `ind_peor_desempeno_municipio` | 13 | Municipio |
| `ind_localidades_menos_horas` | 77 | Localidad |
| `meta_fuentes` | 3 | Fuente |
| `meta_uniones` | 18 | Unión × prueba |
| `kpis_pipeline` | 8 | Indicador |
