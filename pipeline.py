"""
Replica en Python del workflow de n8n "Leads LinkedIn / Prospeccion Servicios -
Hibrido Serper + Apify" (mismo pipeline, dos formularios con distinto texto).

Orden de operaciones (igual que en n8n):
  1. Generar variantes de consulta site:linkedin.com/in a partir de puesto/ciudad/keywords.
  2. Descubrimiento barato: Serper /search (paginado).
  3. Parsear titulo, dedup por URL, calcular score de relevancia contra el puesto buscado.
  4. Si califica (score >= 0.5 y el titulo se pudo partir en >=2 piezas): enriquecer via Apify.
     Si no: va directo a la hoja de rechazados.
  5. Enriquecimiento por lotes de 50 (limite de 300s del endpoint sync de Apify).
  6. Normalizar perfiles de Apify y guardar en Sheets (appendOrUpdate por url, igual que n8n).
"""
import math
import re
import time
import unicodedata
from datetime import datetime, timezone

import gspread
import requests

from config import (
    APIFY_TOKEN,
    GOOGLE_SHEET_ID,
    SERPER_API_KEY,
    SHEET_TAB_CALIFICADOS,
    SHEET_TAB_RECHAZADOS,
)

SERPER_URL = "https://google.serper.dev/search"
APIFY_ACTOR_URL = "https://api.apify.com/v2/acts/supreme_coder~linkedin-profile-scraper/run-sync-get-dataset-items"
BATCH_SIZE = 50


class SourceError(Exception):
    """Fuente de datos (Serper o Apify) fallo de forma irrecuperable."""


def _request_with_retry(method: str, url: str, max_tries: int = 4, wait_seconds: float = 3, **kwargs):
    """Reintenta ante fallos transitorios (red caida o 5xx/429) - igual que
    retryOnFail en los nodos HTTP de n8n. Un 4xx real (ej. credito agotado o
    input invalido) no se reintenta, y se propaga con el cuerpo real de la
    respuesta para poder diagnosticarlo (sin esto solo se ve "400 Bad Request")."""
    last_exc = None
    for attempt in range(1, max_tries + 1):
        try:
            resp = requests.request(method, url, **kwargs)
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc
            if attempt < max_tries:
                time.sleep(wait_seconds)
            continue
        if (resp.status_code >= 500 or resp.status_code == 429) and attempt < max_tries:
            last_exc = requests.HTTPError(f"{resp.status_code} Error for url: {url}", response=resp)
            time.sleep(wait_seconds)
            continue
        if resp.status_code >= 400:
            detail = resp.text.strip()[:500]
            raise requests.HTTPError(f"{resp.status_code} Error for url: {url} - body: {detail}", response=resp)
        return resp
    raise last_exc


# --------------------------------------------------------------------------
# 1. Parseo de input y generacion de consultas (equivalente a "Generar consultas")
# --------------------------------------------------------------------------
def clamp_paginas(value, default=3) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    if n <= 0:
        n = default
    return max(1, min(10, n))


def generar_consultas(puesto: str, ciudad: str, keywords_empresa: list[str], paginas: int) -> list[dict]:
    variantes = [f'"{puesto}" "{ciudad}"']
    for kw in keywords_empresa:
        variantes.append(f'"{puesto}" "{ciudad}" "{kw}"')

    out = []
    for variante in variantes:
        for page in range(1, paginas + 1):
            out.append({
                "q": f"site:linkedin.com/in {variante}",
                "gl": "mx",
                "hl": "es",
                "num": 10,
                "page": page,
            })
    return out


# --------------------------------------------------------------------------
# 2. Descubrimiento (equivalente a "Serper - Descubrimiento")
# --------------------------------------------------------------------------
def buscar_serper(query: dict) -> list[dict]:
    if not SERPER_API_KEY:
        raise SourceError("Falta SERPER_API_KEY en .env")
    headers = {"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"}
    resp = _request_with_retry("POST", SERPER_URL, headers=headers, json=query, timeout=30)
    return resp.json().get("organic", [])


# --------------------------------------------------------------------------
# 3. Parseo + dedup + scoring (equivalente a "Parsear y calificar")
# --------------------------------------------------------------------------
def _normalizar(s: str) -> str:
    s = (s or "").lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s


def parsear_y_calificar(objetivo_puesto: str, resultados_organic: list[dict]) -> list[dict]:
    tokens = [t for t in _normalizar(objetivo_puesto).split() if len(t) > 3]

    vistos = set()
    out = []
    for r in resultados_organic:
        url = (r.get("link") or "").split("?")[0].rstrip("/")
        if not re.search(r"linkedin\.com/in/", url, re.I):
            continue
        if url in vistos:
            continue
        vistos.add(url)

        limpio = re.sub(r"\s*[|\-–]\s*LinkedIn.*$", "", r.get("title") or "", flags=re.I).strip()
        partes = [p.strip() for p in re.split(r"\s+-\s+", limpio) if p.strip()]

        nombre = partes[0] if len(partes) > 0 else ""
        puesto = partes[1] if len(partes) > 1 else ""
        empresa = " - ".join(partes[2:])

        texto = _normalizar(f"{puesto} {r.get('snippet') or ''}")
        hits = sum(1 for t in tokens if t in texto)
        score = (hits / len(tokens)) if tokens else 0

        out.append({
            "nombre": nombre,
            "puesto": puesto,
            "empresa": empresa,
            "url": url,
            "snippet": r.get("snippet") or "",
            "parseo_ok": len(partes) >= 3,
            "score": round(score, 2),
            "califica": score >= 0.5 and len(partes) >= 2,
            "fuente": "serper",
            "fecha": datetime.now(timezone.utc).date().isoformat(),
        })
    return out


# --------------------------------------------------------------------------
# 4/5. Lotes + enriquecimiento (equivalente a "Lotes para Apify" + "Apify - Enriquecimiento")
# --------------------------------------------------------------------------
def hacer_lotes(leads: list[dict], tam: int = BATCH_SIZE) -> list[list[dict]]:
    return [leads[i:i + tam] for i in range(0, len(leads), tam)]


def enriquecer_apify(lote: list[dict]) -> list[dict]:
    if not APIFY_TOKEN:
        raise SourceError("Falta APIFY_TOKEN en .env")
    headers = {"Authorization": f"Bearer {APIFY_TOKEN}", "Content-Type": "application/json"}
    params = {"timeout": "280", "format": "json"}
    # El actor exige objetos {"url": ...}, no strings planos (input schema real
    # verificado via API: GET /v2/actor-builds/{id} -> inputSchema.properties.urls).
    body = {"urls": [{"url": x["url"]} for x in lote]}
    resp = _request_with_retry(
        "POST", APIFY_ACTOR_URL, headers=headers, params=params, json=body, timeout=300,
    )
    data = resp.json()
    return data if isinstance(data, list) else data.get("items", [data])


# --------------------------------------------------------------------------
# 6. Normalizar perfiles (equivalente a "Normalizar perfiles")
# --------------------------------------------------------------------------
def normalizar_perfiles(perfiles: list[dict], meta_por_url: dict[str, dict]) -> list[dict]:
    out = []
    for p in perfiles:
        if not isinstance(p, dict):
            continue
        url = (p.get("inputUrl") or p.get("linkedinUrl") or p.get("url")
               or p.get("profileUrl") or p.get("publicIdentifier") or "")
        url = str(url).split("?")[0].rstrip("/")
        if not url:
            continue
        base = meta_por_url.get(url, {})

        nombre = " ".join(filter(None, [p.get("firstName"), p.get("lastName")])) or \
            p.get("fullName") or p.get("name") or base.get("nombre") or ""

        out.append({
            "url": url or base.get("url", ""),
            "nombre": nombre,
            "titular": p.get("headline") or "",
            "puesto_actual": p.get("jobTitle") or p.get("currentPosition") or base.get("puesto") or "",
            "empresa_actual": p.get("companyName") or p.get("company") or base.get("empresa") or "",
            "empresa_url": p.get("companyWebsite") or p.get("companyLinkedinUrl") or "",
            "industria": p.get("companyIndustry") or p.get("industry") or "",
            "tam_empresa": p.get("companySize") or p.get("employeeCount") or "",
            "ubicacion": p.get("geoLocationName") or p.get("location") or p.get("addressWithCountry") or base.get("ciudad", ""),
            "email": p.get("email") or "",
            "seguidores": p.get("followerCount") or p.get("followers") or p.get("connections") or "",
            "score": base.get("score", ""),
            "fuente": "serper+apify",
            "fecha": datetime.now(timezone.utc).date().isoformat(),
        })
    return out


# --------------------------------------------------------------------------
# 7. Google Sheets - appendOrUpdate por 'url' (igual que n8n, idempotente)
# --------------------------------------------------------------------------
SHEET_COLUMNS = ["url", "nombre", "titular", "puesto_actual", "empresa_actual", "empresa_url",
                  "industria", "tam_empresa", "ubicacion", "email", "seguidores", "score",
                  "fuente", "fecha"]

REJECT_COLUMNS = ["nombre", "puesto", "empresa", "url", "snippet", "parseo_ok", "score",
                   "califica", "fuente", "fecha"]


def _append_or_update(ws, rows: list[dict], columns: list[str]) -> None:
    if not rows:
        return
    header = ws.row_values(1)
    if not header:
        ws.append_row(columns, value_input_option="USER_ENTERED")
        header = columns

    url_col = header.index("url") + 1 if "url" in header else None
    existentes = ws.col_values(url_col) if url_col else []
    idx_por_url = {u: i + 1 for i, u in enumerate(existentes) if u}

    nuevas, actualizaciones = [], []
    for row in rows:
        valores = [row.get(c, "") for c in header]
        url = row.get("url", "")
        if url and url in idx_por_url:
            actualizaciones.append((idx_por_url[url], valores))
        else:
            nuevas.append(valores)

    for fila_num, valores in actualizaciones:
        ws.update(f"A{fila_num}", [valores], value_input_option="USER_ENTERED")
    if nuevas:
        ws.append_rows(nuevas, value_input_option="USER_ENTERED")


def guardar_calificados(leads: list[dict], creds) -> None:
    if not leads:
        return
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(GOOGLE_SHEET_ID)
    ws = sh.worksheet(SHEET_TAB_CALIFICADOS)
    _append_or_update(ws, leads, SHEET_COLUMNS)


def guardar_rechazados(leads: list[dict], creds) -> None:
    if not leads:
        return
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(GOOGLE_SHEET_ID)
    ws = sh.worksheet(SHEET_TAB_RECHAZADOS)
    _append_or_update(ws, leads, REJECT_COLUMNS)


# --------------------------------------------------------------------------
# Orquestacion principal (equivalente al workflow completo de n8n)
# --------------------------------------------------------------------------
def run_pipeline(form: dict, creds) -> dict:
    puesto = (form.get("Puesto") or "").strip()
    ciudad = (form.get("Ciudad") or "").strip()
    if not puesto or not ciudad:
        raise ValueError("Puesto y Ciudad son obligatorios.")
    keywords_empresa = [s.strip() for s in (form.get("PalabrasClaveEmpresa") or "").split(",") if s.strip()]
    paginas = clamp_paginas(form.get("PaginasPorConsulta"))

    consultas = generar_consultas(puesto, ciudad, keywords_empresa, paginas)

    resultados_organic = []
    consultas_fallidas = 0
    for q in consultas:
        try:
            resultados_organic.extend(buscar_serper(q))
        except Exception as exc:
            consultas_fallidas += 1
            print(f"[pipeline] Consulta Serper fallo (q={q['q']!r} page={q['page']}): {exc!r}")

    parseados = parsear_y_calificar(puesto, resultados_organic)
    calificados = [x for x in parseados if x["califica"]]
    rechazados = [x for x in parseados if not x["califica"]]

    guardar_rechazados(rechazados, creds)

    enriquecidos = []
    lotes_fallidos = 0
    for lote in hacer_lotes(calificados):
        meta_por_url = {x["url"]: x for x in lote}
        try:
            perfiles = enriquecer_apify(lote)
            enriquecidos.extend(normalizar_perfiles(perfiles, meta_por_url))
        except Exception as exc:
            lotes_fallidos += 1
            print(f"[pipeline] Lote Apify fallo ({len(lote)} urls): {exc!r}")
            # No perdemos los leads calificados solo porque el enriquecimiento fallo:
            # se guardan con los datos que ya teniamos de Serper, sin los campos de Apify.
            for x in lote:
                enriquecidos.append({
                    "url": x["url"], "nombre": x["nombre"], "titular": "",
                    "puesto_actual": x["puesto"], "empresa_actual": x["empresa"],
                    "empresa_url": "", "industria": "", "tam_empresa": "",
                    "ubicacion": "", "email": "", "seguidores": "",
                    "score": x["score"], "fuente": "serper (apify fallo)",
                    "fecha": x["fecha"],
                })

    guardar_calificados(enriquecidos, creds)

    return {
        "ok": True,
        "consultas_totales": len(consultas),
        "consultas_fallidas": consultas_fallidas,
        "urls_descubiertas": len(parseados),
        "calificados": len(calificados),
        "rechazados": len(rechazados),
        "enriquecidos": len(enriquecidos),
        "lotes_apify_fallidos": lotes_fallidos,
    }
