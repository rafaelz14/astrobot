"""
Integración con Google Calendar — Fase 2/3.

Requiere que TÚ completes esto una vez, fuera de este código:
1. Crear 5 calendarios en tu cuenta de Google: uno por cada persona
   (Rafael / Laura / Joaquín / Sienna) y uno "Familia" para lo que no es
   de una persona en concreto.
2. En console.cloud.google.com: activar la Calendar API y crear credenciales
   OAuth "Aplicación de escritorio" -> descargar como credentials.json en esta carpeta.
3. Ejecutar `python3 google_calendar.py --auth` UNA VEZ desde un ordenador con
   navegador (no desde el Pi headless) para generar token.json.
4. Copiar credentials.json y token.json al Pi, junto al .env con los IDs de calendario.

Si credentials.json o token.json no existen, todas las funciones de aquí
devuelven "not_configured" en vez de fallar — así el resto de la app sigue
funcionando mientras completas la configuración.
"""

import os
import json
import datetime
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_PATH = os.path.join(BASE_DIR, "credentials.json")
TOKEN_PATH = os.path.join(BASE_DIR, "token.json")

SCOPES = ["https://www.googleapis.com/auth/calendar"]

# Zona horaria usada para los eventos que crea la app. Google Calendar
# EXIGE que cada evento lleve zona horaria (o un offset UTC) — sin esto,
# la API lo rechaza. Configurable en .env como TIMEZONE, ej. "Europe/Madrid".
TIMEZONE = os.environ.get("TIMEZONE", "Europe/Madrid")

# owner -> ID de calendario de Google, configurados en .env
# Si una variable no está definida, ese owner queda deshabilitado (no crashea).
OWNER_CALENDAR_IDS = {
    "Rafael": os.environ.get("CAL_ID_RAFAEL"),
    "Laura": os.environ.get("CAL_ID_LAURA"),
    "Joaquín": os.environ.get("CAL_ID_JOAQUIN"),
    "Sienna": os.environ.get("CAL_ID_SIENNA"),
    "Familia": os.environ.get("CAL_ID_FAMILIA"),
}

# mapa inverso, para cuando llega un evento de Google y hay que saber de quién es
CALENDAR_ID_TO_OWNER = {v: k for k, v in OWNER_CALENDAR_IDS.items() if v}


def is_configured():
    """True solo si tenemos credentials.json Y token.json ya generado."""
    return os.path.exists(CREDENTIALS_PATH) and os.path.exists(TOKEN_PATH)


def get_service():
    """
    Devuelve un cliente de la Calendar API, o None si falta configuración.
    Renueva el token automáticamente si caducó (no requiere volver a autorizar
    a mano salvo que revoques el acceso).
    """
    if not is_configured():
        return None

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def list_events(time_min_iso, time_max_iso):
    """
    Trae los eventos de todos los calendarios configurados (los que tengan
    CAL_ID_* definido) entre time_min_iso y time_max_iso (ISO 8601, con Z).
    Devuelve {"configured": True, "events": [...]} o
             {"configured": False} si falta el setup de Google.
    """
    service = get_service()
    if service is None:
        return {"configured": False, "events": []}

    all_events = []
    for owner, cal_id in OWNER_CALENDAR_IDS.items():
        if not cal_id:
            continue
        try:
            result = service.events().list(
                calendarId=cal_id,
                timeMin=time_min_iso,
                timeMax=time_max_iso,
                singleEvents=True,
                orderBy="startTime",
            ).execute()
        except Exception as e:
            # Un calendario mal configurado no debe tirar abajo los demás
            all_events.append({"error": str(e), "owner": owner})
            continue

        for ev in result.get("items", []):
            start = ev["start"].get("dateTime", ev["start"].get("date"))
            end = ev["end"].get("dateTime", ev["end"].get("date"))
            all_events.append({
                "id": ev["id"],
                "title": ev.get("summary", "(sin título)"),
                "start": start,
                "end": end,
                "owner": owner,
                "calendar_id": cal_id,
            })

    return {"configured": True, "events": all_events}


def create_event(owner, title, start_iso, end_iso):
    """
    Crea un evento real en el calendario de Google correspondiente al owner.
    Devuelve {"configured": False} si Google no está listo todavía,
    {"configured": True, "event": {...}} si se creó con éxito, o
    {"configured": True, "error": "..."} si Google rechazó la petición
    (por ejemplo, un calendar_id inválido) — nunca deja que la excepción
    llegue sin capturar a Flask, porque eso devolvería HTML en vez de JSON
    y el frontend no sabría interpretarlo.
    """
    service = get_service()
    if service is None:
        return {"configured": False}

    # Si el owner no se reconoce o no tiene calendario asignado, cae en
    # "Familia" (el catch-all); si ni eso está configurado, como último
    # recurso usa el calendario principal de la cuenta autorizada.
    cal_id = OWNER_CALENDAR_IDS.get(owner) or OWNER_CALENDAR_IDS.get("Familia") or "primary"
    body = {
        "summary": title,
        "start": {"dateTime": start_iso, "timeZone": TIMEZONE},
        "end": {"dateTime": end_iso, "timeZone": TIMEZONE},
    }
    try:
        created = service.events().insert(calendarId=cal_id, body=body).execute()
        return {"configured": True, "event": created}
    except Exception as e:
        return {"configured": True, "error": f"Google rechazó el evento: {e}"}


# ==================== Utilidad de autorización (paso manual, una vez) ====================

def run_local_authorization():
    """
    Abre el navegador para autorizar el acceso a los 3 calendarios y guarda
    token.json. EJECUTAR ESTO DESDE UN ORDENADOR CON NAVEGADOR, no desde el
    Pi en modo kiosco headless. Luego copia token.json (y credentials.json)
    al Pi.
    """
    if not os.path.exists(CREDENTIALS_PATH):
        print(f"Falta {CREDENTIALS_PATH} — descárgalo desde Google Cloud Console primero.")
        return

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
    creds = flow.run_local_server(port=0)
    with open(TOKEN_PATH, "w") as f:
        f.write(creds.to_json())
    print(f"Autorización completa. Token guardado en {TOKEN_PATH}")


if __name__ == "__main__":
    import sys
    if "--auth" in sys.argv:
        run_local_authorization()
    else:
        print("Uso: python3 google_calendar.py --auth")
