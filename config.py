import os

from dotenv import load_dotenv

load_dotenv()

SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")
APIFY_TOKEN = os.getenv("APIFY_TOKEN", "")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")
SHEET_TAB_CALIFICADOS = os.getenv("SHEET_TAB_CALIFICADOS", "Prospectos")
SHEET_TAB_RECHAZADOS = os.getenv("SHEET_TAB_RECHAZADOS", "rechazados")
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")
FLASK_PORT = int(os.getenv("FLASK_PORT", "5001"))
GOOGLE_CLIENT_SECRETS_FILE = os.getenv("GOOGLE_CLIENT_SECRETS_FILE", "client_secret.json")

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]

TOKEN_FILE = "token.json"
