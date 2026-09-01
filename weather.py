"""
Clima — OpenWeatherMap.

Requiere una API key gratuita: https://openweathermap.org/api
(el plan gratuito incluye clima actual + pronóstico de 5 días + calidad
del aire, de sobra para esto). Se configura en .env como WEATHER_API_KEY.

Si no hay API key, get_weather() devuelve {"available": False} en vez de
fallar — igual que hicimos con Google Calendar y con el wifi.
"""

import os
import time
import math
import datetime
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ.get("WEATHER_API_KEY")
# Por defecto, coordenadas de Madrid — cámbialas en .env si vives en otro sitio
LAT = os.environ.get("WEATHER_LAT", "40.4168")
LON = os.environ.get("WEATHER_LON", "-3.7038")

_cache = {"data": None, "fetched_at": 0}
CACHE_TTL = 900  # 15 minutos — de sobra de margen frente al límite gratuito (60 llamadas/min, 1000/día)

# Los iconos de OpenWeatherMap (01d, 10n, etc.) mapeados a algo simple y
# consistente con el resto de la app (mismo estilo que usamos en los mocks)
ICON_MAP = {
    "01": "☀️", "02": "⛅", "03": "☁️", "04": "☁️",
    "09": "🌧️", "10": "🌦️", "11": "⛈️", "13": "❄️", "50": "🌫️",
}

# Escala de calidad del aire de OpenWeatherMap: 1 (Buena) a 5 (Muy mala)
AQI_LABELS = {1: "Buena", 2: "Aceptable", 3: "Moderada", 4: "Mala", 5: "Muy mala"}

MOON_PHASES = [
    (0.0, "🌑", "Luna nueva"), (0.25, "🌓", "Cuarto creciente"),
    (0.5, "🌕", "Luna llena"), (0.75, "🌗", "Cuarto menguante"), (1.0, "🌑", "Luna nueva"),
]


def _map_icon(owm_icon_code):
    return ICON_MAP.get(owm_icon_code[:2], "⛅")


def _moon_phase_now():
    """
    Fase lunar calculada por fórmula astronómica estándar — sin ninguna API.
    Se basa en los días transcurridos desde una luna nueva de referencia
    conocida (6 de enero de 2000) y el ciclo sinódico lunar (~29.53 días).
    """
    synodic_month = 29.530588853
    reference_new_moon = datetime.datetime(2000, 1, 6, 18, 14)
    days_since = (datetime.datetime.utcnow() - reference_new_moon).total_seconds() / 86400.0
    phase_fraction = (days_since % synodic_month) / synodic_month  # 0.0–1.0

    # 8 fases con emoji más específico que las 4 "principales" de MOON_PHASES
    phases_8 = [
        (0.0625, "🌑", "Luna nueva"), (0.1875, "🌒", "Creciente"),
        (0.3125, "🌓", "Cuarto creciente"), (0.4375, "🌔", "Gibosa creciente"),
        (0.5625, "🌕", "Luna llena"), (0.6875, "🌖", "Gibosa menguante"),
        (0.8125, "🌗", "Cuarto menguante"), (0.9375, "🌘", "Menguante"),
    ]
    for threshold, emoji, name in phases_8:
        if phase_fraction < threshold:
            return {"emoji": emoji, "name": name}
    return {"emoji": "🌑", "name": "Luna nueva"}


def _fetch_air_quality():
    """Calidad del aire — endpoint gratuito separado de OpenWeatherMap."""
    try:
        resp = requests.get(
            "https://api.openweathermap.org/data/2.5/air_pollution",
            params={"lat": LAT, "lon": LON, "appid": API_KEY},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        aqi = data["list"][0]["main"]["aqi"]
        return {"aqi": aqi, "label": AQI_LABELS.get(aqi, "—")}
    except Exception:
        # La calidad del aire es un "extra" — si falla, el resto del clima
        # sigue funcionando con normalidad, simplemente sin este dato.
        return None


def is_configured():
    return bool(API_KEY)


def get_weather():
    """
    Clima actual + próximos 3 días + sensación térmica + fase lunar +
    calidad del aire. Cacheado 15 min para no gastar cuota.
    Devuelve {"available": False, "error": ...} si falta la API key o si
    OpenWeatherMap no responde (sin romper el resto de la app).
    """
    if not API_KEY:
        return {"available": False, "error": "Falta WEATHER_API_KEY en .env"}

    now = time.time()
    if _cache["data"] is not None and now - _cache["fetched_at"] < CACHE_TTL:
        return _cache["data"]

    try:
        params = {"lat": LAT, "lon": LON, "appid": API_KEY, "units": "metric", "lang": "es"}

        current = requests.get(
            "https://api.openweathermap.org/data/2.5/weather", params=params, timeout=10
        )
        current.raise_for_status()
        current_data = current.json()

        forecast = requests.get(
            "https://api.openweathermap.org/data/2.5/forecast", params=params, timeout=10
        )
        forecast.raise_for_status()
        forecast_data = forecast.json()

        # Una muestra por día (la más cercana a mediodía) de la lista de pronóstico cada 3h
        daily = []
        seen_dates = set()
        for item in forecast_data.get("list", []):
            date_str, hour_str = item["dt_txt"].split(" ")
            if date_str not in seen_dates and hour_str.startswith("12:"):
                seen_dates.add(date_str)
                daily.append({
                    "date": date_str,
                    "temp": round(item["main"]["temp"]),
                    "icon": _map_icon(item["weather"][0]["icon"]),
                })
            if len(daily) >= 3:
                break

        result = {
            "available": True,
            "temp": round(current_data["main"]["temp"]),
            "feels_like": round(current_data["main"]["feels_like"]),
            "temp_min": round(current_data["main"]["temp_min"]),
            "temp_max": round(current_data["main"]["temp_max"]),
            "description": current_data["weather"][0]["description"].capitalize(),
            "icon": _map_icon(current_data["weather"][0]["icon"]),
            "location": current_data.get("name", ""),
            "forecast": daily,
            "moon_phase": _moon_phase_now(),
            "air_quality": _fetch_air_quality(),  # puede ser None si falla, no rompe nada
        }
        _cache.update(data=result, fetched_at=now)
        return result

    except requests.exceptions.RequestException as e:
        return {"available": False, "error": f"No se pudo contactar OpenWeatherMap: {e}"}
    except (KeyError, IndexError) as e:
        return {"available": False, "error": f"Respuesta inesperada de OpenWeatherMap: {e}"}
