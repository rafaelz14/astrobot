"""
Backend del Calendario Familiar — Fase 1
Flask + SQLite para Tasks (Grocery/To-Do), Recipes y Meals (menú semanal).

El Calendario (Google), el Clima y las Fotos todavía usan datos de ejemplo
en el frontend — se conectan en fases posteriores.
"""

from flask import Flask, jsonify, request, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import os
import time

import google_calendar
import system_control
import weather
import photos as photos_module

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__, static_folder="static", static_url_path="")
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{os.path.join(BASE_DIR, 'skylight.db')}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

DAYS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
SLOTS = ["Desayuno", "Comida", "Cena"]


@app.errorhandler(Exception)
def handle_any_error(e):
    """
    Red de seguridad global: si cualquier ruta lanza una excepción no
    capturada, devolvemos JSON en vez de la página HTML de error por
    defecto de Flask. Sin esto, el frontend recibe un 500 con cuerpo HTML,
    intenta parsearlo como JSON, falla, y muestra un mensaje de error
    genérico y confuso ("no se pudo conectar con el servidor") en vez del
    error real.
    """
    code = getattr(e, "code", 500)
    return jsonify({"error": str(e)}), code


# ==================== MODELOS ====================

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    list_type = db.Column(db.String(20), nullable=False)  # 'grocery' | 'todo'
    text = db.Column(db.String(200), nullable=False)
    done = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)  # se pone al marcar done=True
    archived = db.Column(db.Boolean, default=False)  # a los 3 días de completada

    def to_dict(self):
        return {
            "id": self.id, "text": self.text, "done": self.done, "list": self.list_type,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class Recipe(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    category = db.Column(db.String(20), nullable=False)  # Desayuno / Comida / Cena
    ingredients = db.Column(db.Text)
    instructions = db.Column(db.Text)
    has_carb = db.Column(db.Boolean, default=False)  # heredado de tu script original

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "ingredients": self.ingredients or "",
            "instructions": self.instructions or "",
            "has_carb": bool(self.has_carb),
        }


class MealSlot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    day = db.Column(db.String(10), nullable=False)     # 'Lun'..'Dom'
    slot = db.Column(db.String(20), nullable=False)     # Desayuno/Comida/Cena
    dish_name = db.Column(db.String(150))
    recipe_id = db.Column(db.Integer, db.ForeignKey("recipe.id"), nullable=True)

    __table_args__ = (db.UniqueConstraint("day", "slot", name="uq_day_slot"),)

    def to_dict(self):
        return {
            "id": self.id,
            "day": self.day,
            "slot": self.slot,
            "dish_name": self.dish_name,
            "recipe_id": self.recipe_id,
        }


class WorldClockZone(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    label = db.Column(db.String(60), nullable=False)      # ej. "Madrid"
    iana_zone = db.Column(db.String(60), nullable=False)   # ej. "Europe/Madrid"
    position = db.Column(db.Integer, nullable=False, default=0)

    def to_dict(self):
        return {"id": self.id, "label": self.label, "iana_zone": self.iana_zone, "position": self.position}


# ==================== TASKS (Grocery / To-Do) ====================

COMPLETED_ARCHIVE_DAYS = 3


def _archive_old_completed_tasks():
    """
    Barrido perezoso: se ejecuta cada vez que se listan tareas. Cualquier
    tarea completada hace más de 3 días pasa a "archivada" — deja de
    aparecer en la lista principal y en Home, pero sigue consultable en
    /api/tasks/completed.
    """
    cutoff = datetime.utcnow() - timedelta(days=COMPLETED_ARCHIVE_DAYS)
    old_completed = Task.query.filter(
        Task.done == True, Task.archived == False,
        Task.completed_at != None, Task.completed_at < cutoff,
    ).all()
    for t in old_completed:
        t.archived = True
    if old_completed:
        db.session.commit()


@app.route("/api/tasks", methods=["GET"])
def get_tasks():
    _archive_old_completed_tasks()
    list_type = request.args.get("list")
    q = Task.query.filter_by(archived=False)
    if list_type:
        q = q.filter_by(list_type=list_type)
    return jsonify([t.to_dict() for t in q.order_by(Task.created_at).all()])


@app.route("/api/tasks/completed", methods=["GET"])
def get_completed_tasks():
    """Las que ya se archivaron (completadas hace más de 3 días)."""
    list_type = request.args.get("list")
    q = Task.query.filter_by(archived=True)
    if list_type:
        q = q.filter_by(list_type=list_type)
    return jsonify([t.to_dict() for t in q.order_by(Task.completed_at.desc()).all()])


@app.route("/api/tasks", methods=["POST"])
def create_task():
    data = request.get_json(force=True) or {}
    text = (data.get("text") or "").strip()
    list_type = data.get("list")
    if not text or list_type not in ("grocery", "todo"):
        return jsonify({"error": "text y list ('grocery' o 'todo') son requeridos"}), 400
    t = Task(text=text, list_type=list_type, done=False)
    db.session.add(t)
    db.session.commit()
    return jsonify(t.to_dict()), 201


@app.route("/api/tasks/<int:task_id>", methods=["PATCH"])
def update_task(task_id):
    t = Task.query.get_or_404(task_id)
    data = request.get_json(force=True) or {}
    if "done" in data:
        new_done = bool(data["done"])
        if new_done and not t.done:
            t.completed_at = datetime.utcnow()  # se acaba de completar ahora
        elif not new_done:
            t.completed_at = None  # se destachó: ya no cuenta para el archivado
            t.archived = False
        t.done = new_done
    if "text" in data:
        t.text = data["text"].strip()
    db.session.commit()
    return jsonify(t.to_dict())


@app.route("/api/tasks/<int:task_id>", methods=["DELETE"])
def delete_task(task_id):
    t = Task.query.get_or_404(task_id)
    db.session.delete(t)
    db.session.commit()
    return "", 204


# ==================== RECIPES ====================

@app.route("/api/recipes", methods=["GET"])
def get_recipes():
    category = request.args.get("category")
    q = Recipe.query
    if category:
        q = q.filter_by(category=category)
    return jsonify([r.to_dict() for r in q.order_by(Recipe.name).all()])


@app.route("/api/recipes", methods=["POST"])
def create_recipe():
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()
    category = data.get("category")
    if not name or category not in SLOTS:
        return jsonify({"error": "name y category (Desayuno/Comida/Cena) son requeridos"}), 400
    r = Recipe(
        name=name,
        category=category,
        ingredients=data.get("ingredients", ""),
        instructions=data.get("instructions", ""),
    )
    db.session.add(r)
    db.session.commit()
    return jsonify(r.to_dict()), 201


@app.route("/api/recipes/<int:recipe_id>", methods=["PUT"])
def update_recipe(recipe_id):
    r = Recipe.query.get_or_404(recipe_id)
    data = request.get_json(force=True) or {}
    for field in ("name", "category", "ingredients", "instructions"):
        if field in data:
            setattr(r, field, data[field])
    db.session.commit()
    return jsonify(r.to_dict())


@app.route("/api/recipes/<int:recipe_id>", methods=["DELETE"])
def delete_recipe(recipe_id):
    r = Recipe.query.get_or_404(recipe_id)
    db.session.delete(r)
    db.session.commit()
    return "", 204


# ==================== GENERADOR DE MENÚ ====================
# Puerto de la lógica de menu-generator.py: elige una receta al azar por
# categoría/día SIN repetir ninguna dentro de la misma categoría en la semana.
# random.sample() garantiza esto directamente (muestreo sin reemplazo),
# así que sustituye el bucle de "detectar repetidos y regenerar" del script
# original por algo equivalente pero más directo.

import random

@app.route("/api/meals/generate", methods=["POST"])
def generate_menu():
    data = request.get_json(force=True) or {}
    days = data.get("days", DAYS)  # por defecto, genera los 7 días
    add_to_grocery = data.get("add_to_grocery", True)

    invalid_days = [d for d in days if d not in DAYS]
    if invalid_days:
        return jsonify({"error": f"Días inválidos: {invalid_days}"}), 400

    chosen_by_slot = {}
    for slot in SLOTS:
        pool = Recipe.query.filter_by(category=slot).all()
        if len(pool) < len(days):
            return jsonify({
                "error": f"Solo hay {len(pool)} recetas de {slot}, "
                         f"pero se necesitan {len(days)} distintas para no repetir en la semana."
            }), 400
        chosen_by_slot[slot] = dict(zip(days, random.sample(pool, len(days))))

    for slot in SLOTS:
        for day in days:
            recipe = chosen_by_slot[slot][day]
            entry = MealSlot.query.filter_by(day=day, slot=slot).first()
            if not entry:
                entry = MealSlot(day=day, slot=slot)
                db.session.add(entry)
            entry.dish_name = recipe.name
            entry.recipe_id = recipe.id
    db.session.commit()

    added_to_grocery = []
    if add_to_grocery:
        existing = {t.text.strip().lower() for t in Task.query.filter_by(list_type="grocery").all()}
        seen_this_run = set()
        for slot in SLOTS:
            for day in days:
                recipe = chosen_by_slot[slot][day]
                for ing in (recipe.ingredients or "").split(","):
                    ing = ing.strip()
                    key = ing.lower()
                    if ing and key not in existing and key not in seen_this_run:
                        seen_this_run.add(key)
                        db.session.add(Task(list_type="grocery", text=ing, done=False))
                        added_to_grocery.append(ing)
        db.session.commit()

    result = {slot: {day: chosen_by_slot[slot][day].to_dict() for day in days} for slot in SLOTS}
    return jsonify({"meals": result, "added_to_grocery": added_to_grocery})


# ==================== MEALS (menú semanal) ====================

@app.route("/api/meals", methods=["GET"])
def get_meals():
    entries = MealSlot.query.all()
    grid = {slot: {day: None for day in DAYS} for slot in SLOTS}
    for e in entries:
        grid[e.slot][e.day] = e.to_dict()
    return jsonify(grid)


@app.route("/api/meals/<day>/<slot>", methods=["PUT"])
def set_meal(day, slot):
    if day not in DAYS or slot not in SLOTS:
        return jsonify({"error": "day o slot inválido"}), 400
    data = request.get_json(force=True) or {}
    entry = MealSlot.query.filter_by(day=day, slot=slot).first()
    if not entry:
        entry = MealSlot(day=day, slot=slot)
        db.session.add(entry)
    entry.dish_name = data.get("dish_name")
    entry.recipe_id = data.get("recipe_id")
    db.session.commit()
    return jsonify(entry.to_dict())


# ==================== GOOGLE CALENDAR (Fase 2/3) ====================
# Caché en memoria muy simple: evita golpear la API de Google en cada
# apertura del Calendar o cada refresco de la Home. TTL corto porque
# necesitamos ver los cambios hechos desde el móvil con rapidez razonable.
_events_cache = {"data": None, "fetched_at": 0, "range_key": None}
EVENTS_CACHE_TTL = 120  # segundos

@app.route("/api/events", methods=["GET"])
def get_events():
    """
    ?start=YYYY-MM-DD&end=YYYY-MM-DD (opcional; por defecto, el mes actual)
    """
    today = datetime.utcnow()
    start_str = request.args.get("start")
    end_str = request.args.get("end")
    if start_str and end_str:
        time_min = f"{start_str}T00:00:00Z"
        time_max = f"{end_str}T23:59:59Z"
    else:
        first_of_month = today.replace(day=1)
        next_month = (first_of_month + timedelta(days=32)).replace(day=1)
        time_min = first_of_month.strftime("%Y-%m-%dT00:00:00Z")
        time_max = next_month.strftime("%Y-%m-%dT00:00:00Z")

    range_key = f"{time_min}_{time_max}"
    now = time.time()
    if (_events_cache["data"] is not None
            and _events_cache["range_key"] == range_key
            and now - _events_cache["fetched_at"] < EVENTS_CACHE_TTL):
        return jsonify(_events_cache["data"])

    result = google_calendar.list_events(time_min, time_max)
    _events_cache.update(data=result, fetched_at=now, range_key=range_key)
    return jsonify(result)


@app.route("/api/events", methods=["POST"])
def create_event():
    data = request.get_json(force=True) or {}
    owner = data.get("owner", "General")
    title = (data.get("title") or "").strip()
    start_iso = data.get("start")  # ISO 8601 completo, ej. 2026-08-20T18:00:00
    end_iso = data.get("end")

    if not title or not start_iso or not end_iso:
        return jsonify({"error": "title, start y end son requeridos"}), 400

    # No permitir eventos en fechas pasadas — se valida por fecha (no por hora
    # exacta), así que crear algo "hoy" siempre está permitido aunque ya sea
    # tarde.
    try:
        event_date = datetime.fromisoformat(start_iso).date()
    except ValueError:
        return jsonify({"error": "Formato de fecha/hora inválido en 'start'"}), 400
    if event_date < datetime.now().date():
        return jsonify({"error": "No se pueden crear eventos en fechas pasadas"}), 400

    result = google_calendar.create_event(owner, title, start_iso, end_iso)
    if not result.get("configured"):
        return jsonify({
            "error": "Google Calendar todavía no está configurado (falta credentials.json/token.json)",
            "configured": False,
        }), 409

    if result.get("error"):
        # Google SÍ está configurado, pero rechazó este evento en concreto
        # (calendar_id inválido, zona horaria mal formada, etc.)
        return jsonify({"error": result["error"], "configured": True}), 400

    # invalidar caché para que el próximo GET traiga el evento nuevo
    _events_cache["data"] = None
    return jsonify(result), 201


@app.route("/api/events/status", methods=["GET"])
def events_status():
    """Para que el frontend sepa si debe mostrar el aviso de 'conecta Google Calendar'."""
    return jsonify({
        "configured": google_calendar.is_configured(),
        "owners_ready": [o for o, cid in google_calendar.OWNER_CALENDAR_IDS.items() if cid],
    })


# ==================== WORLD CLOCK (zonas horarias) ====================

@app.route("/api/timezones", methods=["GET"])
def get_timezones():
    zones = WorldClockZone.query.order_by(WorldClockZone.position).all()
    return jsonify([z.to_dict() for z in zones])


@app.route("/api/timezones", methods=["POST"])
def create_timezone():
    data = request.get_json(force=True) or {}
    label = (data.get("label") or "").strip()
    iana_zone = (data.get("iana_zone") or "").strip()
    if not label or not iana_zone:
        return jsonify({"error": "label e iana_zone son requeridos"}), 400

    # valida que sea una zona IANA real antes de guardarla
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(iana_zone)
    except Exception:
        return jsonify({"error": f'"{iana_zone}" no es una zona horaria IANA válida (ej. "Europe/Madrid")'}), 400

    max_pos = db.session.query(db.func.max(WorldClockZone.position)).scalar() or 0
    z = WorldClockZone(label=label, iana_zone=iana_zone, position=max_pos + 1)
    db.session.add(z)
    db.session.commit()
    return jsonify(z.to_dict()), 201


@app.route("/api/timezones/<int:zone_id>", methods=["DELETE"])
def delete_timezone(zone_id):
    z = WorldClockZone.query.get_or_404(zone_id)
    db.session.delete(z)
    db.session.commit()
    return "", 204


@app.route("/api/timezones/reorder", methods=["PUT"])
def reorder_timezones():
    """
    body: {"order": [id1, id2, id3, ...]} — el nuevo orden completo.
    La posición de cada zona pasa a ser su índice en esa lista, así que
    las 5 primeras del array son las que se muestran en Home.
    """
    data = request.get_json(force=True) or {}
    order = data.get("order")
    if not isinstance(order, list) or not order:
        return jsonify({"error": "order debe ser una lista de IDs"}), 400

    zones = {z.id: z for z in WorldClockZone.query.all()}
    for pos, zone_id in enumerate(order):
        if zone_id in zones:
            zones[zone_id].position = pos
    db.session.commit()
    return jsonify([z.to_dict() for z in WorldClockZone.query.order_by(WorldClockZone.position).all()])


# ==================== CLIMA (OpenWeatherMap) ====================

@app.route("/api/weather", methods=["GET"])
def get_weather():
    return jsonify(weather.get_weather())


# ==================== SISTEMA: wifi, salir del kiosko, actualizar ====================

@app.route("/api/wifi/status", methods=["GET"])
def wifi_status():
    return jsonify(system_control.wifi_status())


@app.route("/api/wifi/scan", methods=["GET"])
def wifi_scan():
    return jsonify(system_control.wifi_scan())


@app.route("/api/wifi/connect", methods=["POST"])
def wifi_connect():
    data = request.get_json(force=True) or {}
    ssid = data.get("ssid", "").strip()
    password = data.get("password", "")
    result = system_control.wifi_connect(ssid, password)
    return jsonify(result), (200 if result.get("success") else 400)


@app.route("/api/system/exit-kiosk", methods=["POST"])
def exit_kiosk():
    return jsonify(system_control.exit_kiosk())


@app.route("/api/system/update", methods=["POST"])
def system_update():
    result = system_control.update_and_restart(BASE_DIR)
    return jsonify(result), (200 if result.get("success") else 500)


@app.route("/api/system/version", methods=["GET"])
def system_version():
    return jsonify(system_control.git_version(BASE_DIR))


# ==================== FOTOS (carpeta local sincronizada) ====================

@app.route("/api/photos", methods=["GET"])
def get_photos():
    return jsonify(photos_module.list_photos())


@app.route("/photos/<path:filename>")
def serve_photo(filename):
    servable_path = photos_module.get_servable_path(filename)
    if servable_path is None:
        return jsonify({"error": "Foto no encontrada"}), 404
    # send_from_directory revalida además que no se escape del directorio dado
    return send_from_directory(os.path.dirname(servable_path), os.path.basename(servable_path))


# ==================== FRONTEND ====================

@app.route("/")
def index():
    return app.send_static_file("index.html")


# ==================== SEED (datos de ejemplo al primer arranque) ====================

def seed_if_empty():
    if Recipe.query.count() == 0:
        # Tus 36 recetas originales de menu-generator.py, mapeadas a nuestro esquema:
        # desayuno->Desayuno, almuerzo->Comida, cena->Cena, carb->has_carb
        seed_recipes = [
            # -------- Desayuno --------
            ("huevos con champi y jamon", "Desayuno", "huevos, champis, jamon iberico", False),
            ("huevos con cebolla calabacin y jamon", "Desayuno", "huevos, cebolla, calabacin, jamon", False),
            ("huevos con tomates asados", "Desayuno", "huevos, tomates, queso feta", False),
            ("avenita", "Desayuno", "avena, leche, canela, mantequilla de mani, frutas", True),
            ("panquecas de proteina", "Desayuno", "avena, huevos, platano, chia", True),
            ("tosta de aguacate", "Desayuno", "pan, aguacate, sesamo", True),
            ("huevos revueltos con pimenton asado", "Desayuno", "huevos, pimenton rojo, jamon iberico", False),
            ("lomo adobado con vegetales", "Desayuno", "lomo, champis, tomate", False),
            ("arepa de verduras", "Desayuno", "harina pan, zanahoria", True),
            ("huevos con puerro", "Desayuno", "huevos, puerro, jamon", False),
            ("parfait", "Desayuno", "yogur, avena, almendras, frutas", True),
            ("fritatta de salmon", "Desayuno", "huevos, salmon, puerro", False),
            # -------- Comida (almuerzo) --------
            ("ensalada de pollo", "Comida", "verdes, manzana, pollo, almendras, queso brie", False),
            ("ensalada de pescado", "Comida", "verdes, tomate, pescado, mostaza dijon, pepino", False),
            ("ensalada de camarones", "Comida", "camarones congelados, verdes, pimenton, naranja, frutos rojos", False),
            ("ensalada de lentejas", "Comida", "verdes, lentejas, aceitunas negras, pimenton, queso feta", True),
            ("ensalada fresca de huevo", "Comida", "verdes, huevo hervido, jamon iberico, tomate, pepino", False),
            ("ensalada de garbanzo", "Comida", "verdes, garbanzo, jamon iberico, tomate, pepino", True),
            ("ensalada de pollo a la parrilla", "Comida", "verdes, pollo, tomates, aguacate, cebolla", False),
            ("hamburguesa", "Comida", "carne picada, verdes, tomate, queso, pepinillos", False),
            ("pollo al horno con veggies", "Comida", "muslo de pollo deshuesado, cebolla, tomate, calabacin, pimenton", False),
            ("pasta integral", "Comida", "carne picada, cebolla, lata de tomate, pimenton, puerro, pasta integral", True),
            ("bistec a la pobre", "Comida", "filetes de res, cebolla, tomate", False),
            ("lasagna de berenjena", "Comida", "berenjena, tomate, ajo, cebollas, mozarella", False),
            # -------- Cena --------
            ("lomo con vegetales", "Cena", "lomo de cerdo, cebolla, tomate, pimenton", False),
            ("camarones creole", "Cena", "camarones, cebolla, pimenton, leche de coco, curcuma, curry, pimenton de la vera, comino", False),
            ("wok de pollo", "Cena", "pechuga de pollo, cebolla, pimenton, jenjibre, salsa de soja", False),
            ("risotto de setas", "Cena", "arroz, caldo de pollo, setas", True),
            ("trucha con esparragos", "Cena", "trucha, esparragos", False),
            ("ensalada de pescado", "Cena", "verdes, tomate, pescado, mostaza dijon, pepino", False),
            ("plato italiano", "Cena", "jamon iberico, aceitunas, pepinillos, quesos, almendras", False),
            ("chile de carne", "Cena", "carne picada, cebolla, tomate, pimenton, alubias rojas", False),
            ("taco destruido", "Cena", "alubias rojas, cebolla, tomate, pimenton", False),
            ("lomo de cerdo con queso y ensalada", "Cena", "lomo, queso, verdes, tomate, pepinillo", False),
            ("calabacines rellenos", "Cena", "calabacin, cebolla, queso, tomate, crema de leche", False),
            ("sopa de lentejas", "Cena", "lentejas, cebolla, pimenton", True),
        ]
        for name, cat, ing, has_carb in seed_recipes:
            db.session.add(Recipe(name=name, category=cat, ingredients=ing, has_carb=has_carb))
        db.session.commit()

    if Task.query.count() == 0:
        seed_tasks = [
            ("grocery", "Leche", False),
            ("grocery", "Salmón", False),
            ("grocery", "Pan", True),
            ("todo", "Reservar mesa cena de Ana", False),
            ("todo", "Comprar material para el cole", False),
            ("todo", "Pagar recibo de la comunidad", True),
        ]
        for list_type, text, done in seed_tasks:
            db.session.add(Task(list_type=list_type, text=text, done=done))
        db.session.commit()

    # El menú semanal (MealSlot) ya NO se siembra con datos fijos:
    # se genera desde la app tocando "Generar menú" (POST /api/meals/generate)

    if WorldClockZone.query.count() == 0:
        seed_zones = [
            ("Madrid", "Europe/Madrid"),
            ("London", "Europe/London"),
            ("Miami", "America/New_York"),   # Miami no tiene zona IANA propia; usa la de Nueva York (misma hora)
            ("Caracas", "America/Caracas"),
            ("Santiago de Chile", "America/Santiago"),
        ]
        for i, (label, zone) in enumerate(seed_zones):
            db.session.add(WorldClockZone(label=label, iana_zone=zone, position=i))
        db.session.commit()


with app.app_context():
    db.create_all()
    seed_if_empty()


if __name__ == "__main__":
    # host="0.0.0.0" para que sea accesible desde el móvil en la misma wifi
    # debug=False a propósito: el modo debug relanza el proceso solo (reloader)
    # y no conviene en el Pi corriendo como servicio en segundo plano
    app.run(host="0.0.0.0", port=5000, debug=False)
