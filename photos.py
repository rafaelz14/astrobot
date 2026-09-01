"""
Fotos — carpeta local sincronizada.

No usamos la API de Google Photos directamente (cambió y dejó de ser fiable
para este tipo de proyecto — lo comentamos al principio). En su lugar, esto
lee cualquier carpeta local que TÚ sincronices por tu cuenta con rclone,
el cliente de Dropbox, o simplemente copiando fotos a mano.

Por defecto: ./photos junto a app.py. Cambiable con PHOTOS_DIR en .env.
"""

import os
from dotenv import load_dotenv
from PIL import Image

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()  # le da a Pillow la capacidad de leer HEIC/HEIF
    HEIF_SUPPORT = True
except ImportError:
    HEIF_SUPPORT = False

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# os.environ.get("PHOTOS_DIR", default) SOLO usa el default si la variable
# no existe — pero si existe y está vacía (ej. "PHOTOS_DIR=" en .env, que es
# justo lo que trae la plantilla .env.example), devuelve "" en vez del
# default. Por eso usamos "or", que sí cubre ambos casos.
PHOTOS_DIR = os.environ.get("PHOTOS_DIR") or os.path.join(BASE_DIR, "photos")

CONVERTED_DIR = os.path.join(PHOTOS_DIR, ".converted")  # copias JPEG de los HEIC

ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp"}
if HEIF_SUPPORT:
    ALLOWED_EXT |= {".heic", ".heif"}


def list_photos():
    """
    Lista los archivos de imagen válidos en PHOTOS_DIR, con sus dimensiones
    (para que el frontend decida cover/contain según si son horizontales o
    verticales). Si la carpeta no existe todavía, no es un error —
    simplemente no hay fotos reales que mostrar (el frontend cae a un
    estado de ejemplo).
    """
    if not os.path.isdir(PHOTOS_DIR):
        return {"available": False, "error": f"La carpeta {PHOTOS_DIR} no existe todavía", "photos": []}

    try:
        filenames = sorted(
            f for f in os.listdir(PHOTOS_DIR)
            if os.path.splitext(f)[1].lower() in ALLOWED_EXT
        )
    except OSError as e:
        return {"available": False, "error": str(e), "photos": []}

    photos = []
    for filename in filenames:
        width, height = None, None
        try:
            with Image.open(os.path.join(PHOTOS_DIR, filename)) as img:
                width, height = img.size
        except Exception:
            pass  # si no se puede leer, se sirve igual, solo sin orientación conocida
        photos.append({
            "filename": filename,
            "width": width,
            "height": height,
            "orientation": "landscape" if (width and height and width >= height) else "portrait",
        })

    return {"available": True, "photos": photos, "count": len(photos)}


def get_servable_path(filename):
    """
    Devuelve la ruta real que hay que servir para este filename.
    Si es HEIC/HEIF, convierte (con caché) a JPEG primero — los navegadores
    no saben pintar HEIC de forma nativa, así que sin esto se vería roto.
    Devuelve None si el archivo no existe, el tipo no está permitido, o el
    filename intenta escapar de PHOTOS_DIR (protección extra contra "../",
    además de la que ya aplica send_from_directory).
    """
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXT:
        return None

    original_path = os.path.join(PHOTOS_DIR, filename)
    real_photos_dir = os.path.realpath(PHOTOS_DIR)
    real_original = os.path.realpath(original_path)
    if not real_original.startswith(real_photos_dir + os.sep):
        return None
    if not os.path.isfile(original_path):
        return None

    if ext not in (".heic", ".heif"):
        return original_path

    # HEIC/HEIF: convertir a JPEG con caché (solo se convierte una vez por archivo)
    os.makedirs(CONVERTED_DIR, exist_ok=True)
    converted_path = os.path.join(CONVERTED_DIR, os.path.splitext(filename)[0] + ".jpg")

    needs_conversion = (
        not os.path.isfile(converted_path)
        or os.path.getmtime(original_path) > os.path.getmtime(converted_path)
    )
    if needs_conversion:
        with Image.open(original_path) as img:
            img.convert("RGB").save(converted_path, "JPEG", quality=88)

    return converted_path
