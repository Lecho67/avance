# Análisis exploratorio (EDA)

Generado por `python main.py --etapa eda` (o `python src/eda/run_eda.py`) a partir del modelo gold. Cada figura tiene su
versión en tabla en `tablas/` y las cifras clave están en `hallazgos.json`. El título de cada figura es su hallazgo.

| Figura | Sección | Hallazgo (título de la figura) |
|---|---|---|
| [fig01_frescura_fuentes](figuras/fig01_frescura_fuentes.png) | Preanálisis: calidad y cobertura | Ninguna fuente llega a hoy: la principal va 8 meses atrasada y las otras dos están congeladas desde hace 39 meses o más |
| [fig02_cobertura_mensual](figuras/fig02_cobertura_mensual.png) | Preanálisis: calidad y cobertura | Cada mes reportan entre 14 y 44 de las 97 localidades: la serie es incompleta |
| [fig03_mapa_reporte_localidades](figuras/fig03_mapa_reporte_localidades.png) | Preanálisis: calidad y cobertura | Solo 13 localidades reportan casi todos los meses; 41 reportan 12 meses o menos |
| [fig04_distribucion_horas](figuras/fig04_distribucion_horas.png) | Preanálisis: distribuciones y relaciones | La mitad de las observaciones recibe entre 5,5 y 8,4 horas de energía al día; solo el 3 % tiene servicio casi continuo |
| [fig05_concentracion_energia](figuras/fig05_concentracion_energia.png) | Preanálisis: distribuciones y relaciones | Cinco localidades concentran el 80 % de la energía; Puerto Leguízamo sola, el 65 % |
| [fig06_correlaciones](figuras/fig06_correlaciones.png) | Preanálisis: distribuciones y relaciones | A más energía, más horas de servicio (ρ = 0,57); la potencia máxima casi no las explica (ρ = 0,25) |
| [fig07_estado_departamentos](figuras/fig07_estado_departamentos.png) | P1 · Estado actual | En el último año con datos la región recibió 7,8 de 24 horas de energía al día; Cauca y Nariño, menos de 7 |
| [fig08_brechas_municipios](figuras/fig08_brechas_municipios.png) | P2 · Brechas | Magüí tiene la mayor brecha: recibe 1,9 de 24 horas; los 10 municipios con más brecha son de Nariño o Cauca |
| [fig09_evolucion_departamentos](figuras/fig09_evolucion_departamentos.png) | P3 · Evolución | Sin mejora generalizada: el salto de Valle del Cauca es una sola localidad, Puerto Merizalde (de 7 a 22 horas) |
| [fig10_cambio_localidades](figuras/fig10_cambio_localidades.png) | P3 · Evolución | De 26 localidades, solo 2 mejoraron mucho (Puerto Merizalde y Pital de la Costa); el cambio típico es de +0,3 horas |
| [fig11_estacionalidad](figuras/fig11_estacionalidad.png) | P3 · Evolución | Diciembre es el mes con más horas de servicio (+0,6 h) y enero el de menos (−0,5 h) |
| [fig12_operadores](figuras/fig12_operadores.png) | P4 · Operadores | Los operadores difieren hasta 10 horas, pero los dos extremos se miden con una sola localidad |
| [fig13_pqr](figuras/fig13_pqr.png) | P5 · PQR | Pasto, Ipiales y San Andrés de Tumaco concentran el 71 % de las PQR, que no se relacionan con las horas de servicio (ρ = 0,11) |
| [fig14_peor_desempeno](figuras/fig14_peor_desempeno.png) | P6 · Peor desempeño | San Andrés de Tumaco, Olaya Herrera, Francisco Pizarro: el peor desempeño combinado entre 13 municipios |
| [fig15_localidades_menos_horas](figuras/fig15_localidades_menos_horas.png) | P6 · Peor desempeño | Magüí concentra a las localidades con menos horas: 5 de las 8 peores; 6 reciben menos de 3 horas al día |
| [fig16_operacion_diaria](figuras/fig16_operacion_diaria.png) | Contexto: operación diaria | La bitácora diaria declara casi siempre 4, 5 u 8 horas (96 % de los registros): parece un horario fijo, no una medición |

## Tablas de apoyo

- [`perfil_fact_prestacion.csv`](tablas/perfil_fact_prestacion.csv)
- [`cobertura_mensual.csv`](tablas/cobertura_mensual.csv)
- [`concentracion_energia.csv`](tablas/concentracion_energia.csv)
- [`correlaciones_spearman.csv`](tablas/correlaciones_spearman.csv)
- [`estado_reciente.csv`](tablas/estado_reciente.csv)
- [`ranking_municipios_brecha.csv`](tablas/ranking_municipios_brecha.csv)
- [`evolucion_departamentos.csv`](tablas/evolucion_departamentos.csv)
- [`cambio_por_localidad.csv`](tablas/cambio_por_localidad.csv)
- [`estacionalidad.csv`](tablas/estacionalidad.csv)
- [`operadores.csv`](tablas/operadores.csv)
- [`pqr_por_municipio.csv`](tablas/pqr_por_municipio.csv)
- [`localidades_menos_horas.csv`](tablas/localidades_menos_horas.csv)

## Cómo leer las figuras

- P1 a P6 son las preguntas del MVP del documento de diseño (sección 6.1): P1 estado actual, P2 brechas, P3 evolución,
  P4 operadores, P5 PQR y P6 peor desempeño combinado.
- Un color fijo por departamento en todas las figuras: Cauca (azul), Nariño (naranja), Valle del Cauca (verde), Putumayo (amarillo).
- Las PQR son de distribuidoras de **gas**: se usan como contexto municipal, no como quejas del servicio eléctrico.
- Las fuentes no llegan a hoy (prestación: 8 meses sin datos nuevos; operación diaria y PQR congeladas) y la cobertura de prestación es irregular
  (14 a 44 de 97 localidades por mes): por eso las comparaciones en el tiempo se hacen contra la propia localidad.
