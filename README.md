# Leads LinkedIn - Hibrido Serper + Apify

Prospeccion B2B: descubrimiento barato de perfiles de LinkedIn via el indice de
Google (Serper), calificacion por relevancia, y enriquecimiento selectivo solo de
los que califican via Apify. Salida a Google Sheets (calificados / rechazados).
Replica en Python de dos workflows de n8n que resultaron ser el mismo pipeline con
dos formularios distintos — ver [Modos](#modos) abajo.

## Indice

- [Arquitectura](#arquitectura)
- [Modos](#modos)
- [1. Instalar dependencias](#1-instalar-dependencias)
- [2. Configurar credenciales](#2-configurar-credenciales)
- [3. Configurar el login de Google](#3-configurar-el-login-de-google-sheets)
- [4. Arrancar la app](#4-arrancar-la-app)
- [Estructura del proyecto](#estructura-del-proyecto)
- [Decisiones de diseno y calibracion](#decisiones-de-diseno-y-calibracion)

## Arquitectura

```
Formulario (Puesto, Ciudad, Palabras clave empresa, Paginas por consulta)
  -> generar variantes de consulta: site:linkedin.com/in "puesto" "ciudad" [+ keyword]
  -> Serper /search (una llamada por variante x pagina, num=10)
  -> parsear titulo -> nombre / puesto / empresa, dedup por URL, score de relevancia
  -> califica? (score >= 0.5 y el titulo se pudo partir en >= 2 piezas)
       si   -> lotes de 50 -> Apify (supreme_coder~linkedin-profile-scraper) -> normalizar
                                                                              -> Sheet "Prospectos"
       no   -> Sheet "rechazados" directo
```

Guardado en Sheets es **idempotente**: cada fila se actualiza o inserta segun la
columna `url` (igual que `appendOrUpdate` en n8n), asi que correr el mismo
segmento dos veces no duplica filas.

## Modos

Un mismo pipeline, dos textos de formulario (el selector "Modo" solo cambia el
titulo/placeholders, la logica es identica):

- **Prospeccion Servicios** — pensado para buscar duenos/gerentes que podrian
  necesitar tus propios servicios.
- **Leads LinkedIn** — mismo flujo, enmarcado como generador de leads generico
  (ej. "Gerente de Compras" para prospeccion de ventas B2B).

## 1. Instalar dependencias

```bash
cd proyecto_leads_linkedin
pip install -r requirements.txt
```

## 2. Configurar credenciales

```bash
cp .env.example .env
```

Edita `.env` y llena:

- `SERPER_API_KEY` - tu API key de [serper.dev](https://serper.dev/api-key).
- `APIFY_TOKEN` - tu token de Apify (Settings -> API & Integrations -> "Default API token").
- `GOOGLE_SHEET_ID` - el ID del spreadsheet (esta en la URL del Sheet). Debe tener
  las pestanas `Prospectos` y `rechazados` creadas de antemano (nombres configurables
  via `SHEET_TAB_CALIFICADOS` / `SHEET_TAB_RECHAZADOS`).

## 3. Configurar el login de Google (Sheets)

Mismo patron que [`lead-scraper-python`](../../lead-scraper-python) — un OAuth
Client tipo Web application (puede ser el mismo si le agregas un redirect URI
adicional, o uno nuevo):

1. [Google Cloud Console -> Credentials](https://console.cloud.google.com/apis/credentials)
   -> **Create Credentials -> OAuth client ID** -> Web application.
2. En **Authorized redirect URIs** agrega:
   ```
   http://localhost:5001/oauth2callback
   ```
3. Descarga el JSON, renombralo a `client_secret.json` y ponlo en esta carpeta.

## 4. Arrancar la app

```bash
python app.py
```

Abre [http://localhost:5001](http://localhost:5001) - primer login con Google
guarda la sesion en `token.json` (se refresca solo despues).

## Estructura del proyecto

```
proyecto_leads_linkedin/
  app.py          Flask: login con Google + formulario (2 modos) + endpoint /run
  pipeline.py      Generacion de consultas, Serper, scoring, lotes + Apify, normalizado, Sheets
  config.py        Carga variables de .env
  templates/       login.html, index.html, result.html
  workflows/       Workflow original de n8n (borrador con credenciales placeholder)
  scripts/costos.py   Modelo de costo/tiempo hibrido vs. Apify-solo
  CLAUDE.md        Notas de diseno originales del proyecto (arquitectura, decisiones, pendientes)
  .env             Tus credenciales (NO se sube a git)
  client_secret.json / token.json   Sesion de Google (NO se sube a git)
```

## Decisiones de diseno y calibracion

**Por que no se scrapea LinkedIn directo.** LinkedIn demando a Proxycurl en enero
2025 y la empresa cerro en julio de ese ano. La linea que se traza aqui es
login vs. publico: nada que exija autenticarse como usuario de LinkedIn. Solo se
usan actors de Apify que no piden cookie de sesion (los que si la piden actuan
como tu cuenta y LinkedIn la cierra al pasar cierto volumen).

**Formato real del input de Apify (calibrado).** El actor
`supreme_coder~linkedin-profile-scraper` exige `urls` como un arreglo de objetos
`{"url": "..."}`, no strings planos — verificado contra el input schema real via
`GET /v2/actor-builds/{id}` de la API de Apify. Un borrador anterior de este
workflow asumia el campo `profileUrls`; quedo descartado.

**Campos que el actor SI y NO devuelve por defecto.** Con la configuracion actual
(sin `scrapeCompany` ni el addon `findContacts`): `titular`, `puesto_actual`,
`empresa_actual`, `empresa_url`, `ubicacion` y `seguidores` llegan bien.
`industria`, `tam_empresa` y `email` llegan vacios — requieren activar opciones
extra del actor (mas costo/tiempo), no estan prendidas por defecto.

**Lotes de 50 hacia Apify.** El endpoint `run-sync-get-dataset-items` corta a los
300s; 50 deja margen razonable. Si un lote completo falla, esos leads se guardan
igual (con los datos de Serper, sin enriquecer) en vez de perderse.

**`num=10` en Serper, no 100.** 1 credito cubre hasta 10 resultados; 11-100 cuesta
2 creditos, y Google retiro el parametro `num=100` a fines de 2025 — pedirlo puede
cobrar doble sin entregar mas resultados.

Ver [`CLAUDE.md`](CLAUDE.md) para el resto de las decisiones de diseno originales
y el modelo de costos (`scripts/costos.py`).
