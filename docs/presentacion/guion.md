# Guion de la presentación

**Título:** Energía en las ZNI del suroccidente colombiano
**Duración sugerida:** 12 a 15 minutos con las diapositivas 1 a 16; las 4 últimas son anexo para responder preguntas.

**Idea central.** En promedio, una localidad de las ZNI del suroccidente recibe menos de 8 de las 24 horas del día, la brecha se concentra en la costa
pacífica de Nariño y Cauca y no hay una mejora generalizada; además, los datos están atrasados e incompletos, y eso limita cualquier decisión.

**Estructura narrativa**

- **Por qué importa y qué construimos.** Desde la diapositiva 1.
- **Qué dicen los datos sobre estado, brechas, evolución, operadores y PQR.** Desde la diapositiva 4.
- **Qué tan confiables y completos son los datos.** Desde la diapositiva 12.
- **Conclusiones, recomendaciones y próximos pasos.** Desde la diapositiva 13.
- **Material de apoyo para preguntas.** Desde la diapositiva 17.

La presentación vive como una página de Slides publicada desde la cuenta de claude.ai (privada: solo la abre quien tenga acceso) y se exporta a PowerPoint o PDF desde su menú.
Este guion y las figuras (`figuras/`, regenerables con `python src/eda/run_eda.py --diapositivas`) permiten ensayarla o reconstruirla. Las cifras salen de
`docs/eda/hallazgos.json`.

## Mapa de diapositivas

| # | Sección | Mensaje (título de la diapositiva) |
|---|---|---|
| 1 | Portada | ¿Cuántas horas de energía al día reciben las ZNI del suroccidente colombiano? |
| 2 | El problema | Muchas localidades sin red nacional reciben solo algunas horas de energía al día |
| 3 | Qué construimos | Un pipeline reproducible convierte tres fuentes abiertas en un modelo listo para analizar |
| 4 | P1 · Estado actual | La región recibe 7,8 de las 24 horas posibles de energía al día |
| 5 | P2 · Brechas | Magüí tiene la mayor brecha: recibe 1,9 de 24 horas |
| 6 | P6 · Localidades con menos horas | 5 de las 8 localidades con menos horas están en Magüí |
| 7 | P3 · Evolución | El salto de Valle del Cauca es una sola localidad: Puerto Merizalde |
| 8 | P3 · Evolución | Solo 2 de 26 localidades mejoraron mucho; el cambio típico es +0,3 horas |
| 9 | P4 · Operadores | Los operadores difieren hasta 10 horas, pero los extremos se miden con una sola localidad |
| 10 | P5 · PQR | Pasto, Ipiales y San Andrés de Tumaco concentran el 71 % de las PQR |
| 11 | P6 · Peor desempeño combinado | San Andrés de Tumaco, Olaya Herrera y Francisco Pizarro: el peor desempeño combinado |
| 12 | Qué tan confiables son los datos | La fuente principal lleva 8 meses sin actualizarse y otras dos están congeladas |
| 13 | Conclusiones | El servicio es corto, se concentra en la costa pacífica y no está mejorando de forma general |
| 14 | Qué haríamos con esto | Cuatro recomendaciones para el analista de política energética |
| 15 | Lo que sigue | Del modelo gold al tablero, y de allí a las fases siguientes |
| 16 | Cierre | Medir bien es el primer paso para cerrar la brecha de 16,2 horas |
| 17 | Anexo · Distribución | La mitad de las observaciones recibe entre 5,5 y 8,4 horas; solo el 3 % tiene servicio casi continuo |
| 18 | Anexo · Estacionalidad | Diciembre es el mes con más horas (+0,6 h) y enero el de menos (−0,5 h) |
| 19 | Anexo · Cobertura | Cada mes reportan entre 14 y 44 de las 97 localidades: la serie es incompleta |
| 20 | Anexo · Operación diaria | La bitácora declara casi siempre 4, 5 u 8 horas (96 % de los registros): parece un horario fijo |

## Notas del orador

### 1. ¿Cuántas horas de energía al día reciben las ZNI del suroccidente colombiano?

Abrir con el número: en promedio, una localidad de las zonas no interconectadas del suroccidente recibe 7,8 de las 24 horas del día. La pregunta de hoy es dónde falta más servicio y si está mejorando. Presentarse brevemente: somos tres estudiantes de la UAO y construimos un pipeline ETL con datos abiertos.

### 2. Muchas localidades sin red nacional reciben solo algunas horas de energía al día

Contexto en una frase: las ZNI no están en la red nacional y dependen de operadores locales. El problema para el analista de política energética (el usuario del proyecto) es que los datos están dispersos. Por eso construimos un pipeline que los integra y un análisis que responde seis preguntas.

### 3. Un pipeline reproducible convierte tres fuentes abiertas en un modelo listo para analizar

Esta diapositiva es corta: el pipeline ya se presentó en las fases anteriores. Lo importante es que todo el análisis que sigue sale de ese modelo gold, el mismo que está cargado en PostgreSQL (19 tablas, 6.718 filas), y que cada corrida es reproducible con un solo comando.

### 4. La región recibe 7,8 de las 24 horas posibles de energía al día

Este es el estado actual. En el último año con datos, las localidades de la región recibieron en promedio 7,8 horas de energía al día. Cauca y Nariño están por debajo de 7 horas. Putumayo parece mejor, pero es un promedio de solo 2 localidades muy distintas, así que no representa al departamento.

### 5. Magüí tiene la mayor brecha: recibe 1,9 de 24 horas

La brecha es 24 horas menos las horas de servicio. Magüí es el extremo, con 1,9 horas al día en promedio; le siguen López de Micay, El Charco y Olaya Herrera. Los diez municipios con más brecha son de Nariño o Cauca, en la costa pacífica. Las menores brechas son las de Puerto Leguízamo y Buenaventura.

### 6. 5 de las 8 localidades con menos horas están en Magüí

Bajando a las localidades: 5 de las 8 con menos horas están en Magüí. La peor es El Rosario, con 0,4 horas al día. En total, 6 localidades reciben menos de 3 horas diarias. Ojo con la evidencia: varias de estas localidades tienen pocos meses reportados.

### 7. El salto de Valle del Cauca es una sola localidad: Puerto Merizalde

Si miramos solo los promedios por departamento, parece que Valle del Cauca mejoró entre 2022 y 2023. Pero ese salto lo explica una sola localidad, Puerto Merizalde, que pasó de 7 a 22 horas. Los promedios de un departamento también se mueven cuando cambian las localidades que reportan.

### 8. Solo 2 de 26 localidades mejoraron mucho; el cambio típico es +0,3 horas

Para quitar el efecto de qué localidades reportan, comparamos cada localidad consigo misma entre 2020-2021 y 2024-2025. De 26, solo Puerto Merizalde y Pital de la Costa mejoraron mucho. El cambio mediano es +0,3 horas y su intervalo incluye el cero: no hay mejora generalizada. El promedio (+1,1 h) lo jalonan esas dos localidades; sin ellas es +0,1 h.

### 9. Los operadores difieren hasta 10 horas, pero los extremos se miden con una sola localidad

Hay 14 operadores observados. El que más horas tiene es Electrificadora del Pacífico (13,5 h) y el que menos, Energía Rural Francisco Pizarro (3,1 h); pero cada uno se mide con una sola localidad y entre uno y cuatro meses. No alcanza para decir que un operador es mejor que otro. Además, el registro de operador está congelado desde marzo de 2022.

### 10. Pasto, Ipiales y San Andrés de Tumaco concentran el 71 % de las PQR

Hay 9.282 casos de PQR, el 89 % con respuesta. Tres municipios concentran el 71 %. Advertencia importante: las empresas de esta fuente son distribuidoras de gas; el identificador de empresa coincide en 0 % con la bitácora de operación eléctrica. Por eso las PQR sirven como contexto municipal, no como medida de la calidad del servicio de energía.

### 11. San Andrés de Tumaco, Olaya Herrera y Francisco Pizarro: el peor desempeño combinado

El puntaje combina el percentil de brecha de horas y el de PQR. San Andrés de Tumaco queda primero sobre todo por sus 767 casos de PQR de gas; Olaya Herrera y Francisco Pizarro lo hacen por su brecha de horas. Por eso conviene leer este ranking junto con el de localidades con menos horas, que mira solo el servicio eléctrico.

### 12. La fuente principal lleva 8 meses sin actualizarse y otras dos están congeladas

Antes de decidir con estos datos hay que saber qué tan buenos son. La fuente principal llega hasta 2026-01, con 8 meses de retraso; la bitácora de operación y las PQR están congeladas desde 2022-03 y 2023-06. Además, cada mes reportan entre 14 y 44 de las 97 localidades. El pipeline marca cada registro con su estado de frescura para que el tablero lo advierta.

### 13. El servicio es corto, se concentra en la costa pacífica y no está mejorando de forma general

Cuatro conclusiones. Uno: el servicio es corto en toda la región. Dos: la brecha se concentra en la costa pacífica de Nariño y Cauca, con Magüí como caso extremo. Tres: no hay una mejora generalizada; solo dos localidades mejoraron mucho. Cuatro: los datos están atrasados e incompletos, y eso limita cualquier decisión.

### 14. Cuatro recomendaciones para el analista de política energética

Estas son propuestas nuestras, derivadas de los hallazgos; no son resultados de los datos. La primera es dónde priorizar. La segunda, aprender de los dos casos que sí mejoraron. La tercera, mejorar el dato: sin series completas no se puede medir mejora. La cuarta, sumar población y el catálogo DIVIPOLA, que son las dos piezas que le faltan al modelo para priorizar por personas.

### 15. Del modelo gold al tablero, y de allí a las fases siguientes

Lo que sigue: publicar el tablero en Power BI sobre el esquema gold, que es el cuarto resultado clave del proyecto; incorporar las fuentes adicionales de la fase 2; y mantener el pipeline: cuando haya datos nuevos se vuelve a correr un solo comando.

### 16. Medir bien es el primer paso para cerrar la brecha de 16,2 horas

Cerrar con la idea central: la brecha promedio es de 16,2 horas al día, y medirla bien (con datos completos y actualizados) es el primer paso para cerrarla. Abrir preguntas.

### 17. La mitad de las observaciones recibe entre 5,5 y 8,4 horas; solo el 3 % tiene servicio casi continuo

Material de apoyo: la distribución de las horas. La mediana es de 7,0 horas y la mitad de las observaciones está entre 5,5 y 8,4.

### 18. Diciembre es el mes con más horas (+0,6 h) y enero el de menos (−0,5 h)

Material de apoyo: hay un patrón estacional pequeño pero claro. Los datos no dicen por qué; una hipótesis sin probar es la mayor demanda de fin de año.

### 19. Cada mes reportan entre 14 y 44 de las 97 localidades: la serie es incompleta

Material de apoyo: la cobertura mensual. Es la razón por la que la evolución se mide comparando cada localidad consigo misma y no promedios de toda la región.

### 20. La bitácora declara casi siempre 4, 5 u 8 horas (96 % de los registros): parece un horario fijo

Material de apoyo: la bitácora de operación diaria es la fuente más detallada, pero sus horas parecen un horario fijo; por eso el análisis usa las horas de la fuente de prestación.

