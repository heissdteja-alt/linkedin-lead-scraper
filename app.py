"""
Flask app: formulario de Generador de Leads LinkedIn / Prospeccion de Servicios,
con login de Google (Sheets). Mismo patron de OAuth que lead-scraper-python.

Rutas:
  GET  /              -> formulario (o redirige a /login si no hay sesion)
  GET  /login          -> pantalla "Iniciar sesion con Google"
  GET  /authorize       -> arranca el flujo OAuth
  GET  /oauth2callback -> Google redirige aqui, se guarda el token
  GET  /logout         -> borra la sesion local
  POST /run             -> ejecuta el pipeline con los datos del formulario
"""
import json
import os

os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

from flask import Flask, redirect, render_template, request, session, url_for
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from config import FLASK_PORT, FLASK_SECRET_KEY, GOOGLE_CLIENT_SECRETS_FILE, GOOGLE_SCOPES, TOKEN_FILE
from pipeline import run_pipeline

app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY

REDIRECT_URI = f"http://localhost:{FLASK_PORT}/oauth2callback"

MODOS = {
    "prospeccion": {
        "titulo": "Prospeccion de Clientes para Servicios",
        "descripcion": "Busca duenos/gerentes que podrian necesitar tus servicios (analisis de datos, ecommerce, dashboards, leads)",
        "placeholder_puesto": "Dueno, Director General, Gerente de Ecommerce",
        "placeholder_kw": "analisis de datos, dashboards, ecommerce, venta de leads (separadas por coma)",
    },
    "linkedin": {
        "titulo": "Generador de Leads LinkedIn",
        "descripcion": "Descubrimiento barato via Serper + enriquecimiento selectivo via Apify",
        "placeholder_puesto": "Gerente de Compras",
        "placeholder_kw": "manufactura, retail (separadas por coma)",
    },
}


def _save_token(creds: Credentials) -> None:
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(creds.to_json())


def _load_creds() -> Credentials | None:
    if not os.path.exists(TOKEN_FILE):
        return None
    with open(TOKEN_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    creds = Credentials.from_authorized_user_info(data, GOOGLE_SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(GoogleAuthRequest())
        _save_token(creds)
    return creds


def _make_flow() -> Flow:
    return Flow.from_client_secrets_file(
        GOOGLE_CLIENT_SECRETS_FILE,
        scopes=GOOGLE_SCOPES,
        redirect_uri=REDIRECT_URI,
    )


@app.route("/")
def index():
    creds = _load_creds()
    if not creds or not creds.valid:
        return redirect(url_for("login"))
    modo = request.args.get("modo", "prospeccion")
    if modo not in MODOS:
        modo = "prospeccion"
    return render_template("index.html", user_email=session.get("user_email", ""), modo=modo, modos=MODOS)


@app.route("/login")
def login():
    return render_template("login.html")


@app.route("/authorize")
def authorize():
    if not os.path.exists(GOOGLE_CLIENT_SECRETS_FILE):
        return (
            f"Falta el archivo {GOOGLE_CLIENT_SECRETS_FILE}. "
            "Copialo del proyecto lead-scraper-python (mismo proyecto de Google Cloud) "
            "y agrega http://localhost:{}/oauth2callback como Authorized redirect URI.".format(FLASK_PORT),
            500,
        )
    flow = _make_flow()
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    session["oauth_state"] = state
    return redirect(auth_url)


@app.route("/oauth2callback")
def oauth2callback():
    state = session.get("oauth_state")
    flow = _make_flow()
    flow.fetch_token(authorization_response=request.url, state=state)
    creds = flow.credentials
    _save_token(creds)

    try:
        from googleapiclient.discovery import build

        about = build("sheets", "v4", credentials=creds)
        session["user_email"] = ""  # no pedimos scope de perfil, solo Sheets
    except Exception:
        session["user_email"] = ""

    return redirect(url_for("index"))


@app.route("/logout")
def logout():
    session.clear()
    if os.path.exists(TOKEN_FILE):
        os.remove(TOKEN_FILE)
    return redirect(url_for("login"))


@app.route("/run", methods=["POST"])
def run():
    creds = _load_creds()
    if not creds or not creds.valid:
        return redirect(url_for("login"))

    form = {
        "Puesto": request.form.get("Puesto", ""),
        "Ciudad": request.form.get("Ciudad", ""),
        "PalabrasClaveEmpresa": request.form.get("PalabrasClaveEmpresa", ""),
        "PaginasPorConsulta": request.form.get("PaginasPorConsulta", ""),
    }

    try:
        result = run_pipeline(form, creds)
        return render_template("result.html", ok=True, result=result)
    except Exception as exc:  # noqa: BLE001
        return render_template("result.html", ok=False, error=str(exc))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=FLASK_PORT, debug=True, use_reloader=False)
