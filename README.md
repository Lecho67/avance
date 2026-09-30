# Monitoreo del servicio de energía en ZNI (suroccidente colombiano)

Pipeline ETL que integra, limpia y estandariza el estado de la prestación del servicio de
energía eléctrica en las Zonas No Interconectadas (ZNI) de Valle del Cauca, Cauca, Nariño
y Putumayo, a partir de tres fuentes del portal de datos.gov.co. Ver el diseño completo en
`docs/Avance_2_Proyecto_ETL_2026_V4.pdf`.

## Estado del proyecto

En construcción por fases (Fase 0 completada: estructura, entorno y configuración base).

## 1. Instalación (PowerShell)

```powershell
cd C:\Users\simon\Documents\avance

# Crear el entorno virtual (ya existe en este repo; se deja el comando de referencia)
python -m venv .venv

# Activar el entorno virtual
.venv\Scripts\Activate.ps1

# Instalar dependencias
pip install -r requirements.txt
```

## 2. Configuración de `.env`

Copiar `.env.example` a `.env` y completar los valores:

```powershell
Copy-Item .env.example .env
```

Variables:

- `DATABASE_URL` (opcional): cadena de conexión completa a PostgreSQL. Si se deja vacía,
  se arma automáticamente a partir de las variables `PG_*`.
- `PG_HOST`, `PG_PORT`, `PG_DATABASE`, `PG_USER`, `PG_PASSWORD`: credenciales de PostgreSQL.
- `SOCRATA_APP_TOKEN` (opcional): token de la API de datos.gov.co para evitar límites de tasa.

## 3. Cómo correr cada etapa

_Pendiente: se completa en la Fase 6, cuando `main.py` quede terminado._

```powershell
python main.py --etapa perfilar
python main.py --etapa extract
python main.py --etapa silver
python main.py --etapa gold
python main.py --etapa load
python main.py --etapa all      # por defecto
```

## 4. Fuentes de datos

| Fuente             | Id Socrata  | Dueño                  | Granularidad                     |
|---------------------|-------------|-------------------------|-----------------------------------|
| `prestacion`         | 3ebi-d83g   | MinEnergía / IPSE        | localidad x mes                  |
| `operacion_diaria`   | qwe5-ycap   | Superservicios           | localidad x día x operador       |
| `pqr`                | 5wua-nr2d   | Superservicios           | empresa x municipio x semestre   |

Alcance geográfico: Valle del Cauca (76), Cauca (19), Nariño (52), Putumayo (86), filtrando
por los 2 primeros dígitos del código DANE de municipio.

## 5. Modelo de datos (capa gold)

_Pendiente: se completa en la Fase 4 (modelo gold: `dim_localidad`, `fact_prestacion`,
`puente_operador_localidad`, `fact_pqr`, indicadores y `kpis_pipeline.csv`)._

## 6. Calidad y KPIs del pipeline

_Pendiente: se completa en la Fase 5/6 (`src/transform/quality_checks.py` y
`data/gold/kpis_pipeline.csv`)._

## 7. Pruebas

```powershell
pytest
```
