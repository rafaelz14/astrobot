# Calendario Familiar — Raspberry Pi

Pantalla de pared táctil para calendario, tareas, menú semanal y fotos.
Corre en un Raspberry Pi 3 con Chromium en modo kiosco, sirviendo un backend
Flask propio (sin depender de MagicMirror).

## Estado actual

| Sección | Estado |
|---|---|
| To-Do / Grocery | ✅ Backend real (SQLite), persiste, tachable |
| Recipes | ✅ Backend real, importadas las 36 recetas originales |
| Meals | ✅ Backend real + generador automático sin repetir plato en la semana |
| Calendar (eventos Google) | ✅ Código listo — falta que completes la configuración de Google (ver abajo) |
| Wifi / Kiosko / Update | ✅ Arranque automático, wifi desde pantalla, salir y actualizar — ver instalación abajo |
| Clima | ✅ OpenWeatherMap, actual + pronóstico 3 días, caché de 15 min |
| Fotos | ✅ Carpeta local sincronizada, rota cada 10s en Home y en modo portaretrato |

**Backend completo.** Lo que queda es trabajo de instalación en el Pi real
(ver más abajo) y completar las claves/credenciales de servicios externos
(Google, OpenWeatherMap) que solo tú puedes generar.

## Configurar las fotos (una sola vez)

1. La carpeta `photos/` ya existe junto a `app.py` (vacía, con un `.gitkeep`
   para que git la trackee — su contenido real nunca se sube, ver `.gitignore`).
2. Sincroniza ahí las fotos familiares por el método que prefieras:
   - **rclone** apuntando a un álbum de Google Photos, con un cronjob que
     sincronice cada pocas horas
   - **Dropbox**: cliente de Dropbox en el Pi + carpeta compartida como `PHOTOS_DIR`
   - O copiar fotos a mano con `scp` cuando quieras actualizar el álbum
3. Formatos soportados: `.jpg`, `.jpeg`, `.png`, `.webp`, `.heic`, `.heif`
   (los HEIC del iPhone se convierten a JPEG automáticamente la primera vez
   que se piden, con caché en `photos/.converted/`) — cualquier otro
   archivo se ignora automáticamente.
4. Si la carpeta está vacía, la app muestra 3 fotos de ejemplo con un aviso
   claro en vez de fotos reales falsas.

## Configurar el clima (una sola vez)

1. Regístrate gratis en [openweathermap.org/api](https://openweathermap.org/api)
   → "My API keys" → copia la key (puede tardar ~10-15 min en activarse).
2. En `.env`: `WEATHER_API_KEY=tu_key_aquí`
3. Opcional: cambia `WEATHER_LAT` / `WEATHER_LON` si no vives en Madrid
   (clic derecho en Google Maps sobre tu ciudad → copia las coordenadas).

## Configurar Google Calendar (una sola vez)

1. En tu cuenta de Google, crea 5 calendarios: uno por persona
   (**Rafael**, **Laura**, **Joaquín**, **Sienna**) y **Familia** para lo
   que no es de alguien en concreto
   (Google Calendar web → "Otros calendarios" → "+" → "Crear calendario nuevo").
2. En [console.cloud.google.com](https://console.cloud.google.com): crea un proyecto,
   activa la **Google Calendar API**, y en "Credenciales" crea un OAuth Client ID
   de tipo **Aplicación de escritorio**. Descarga el JSON y guárdalo como
   `credentials.json` en esta misma carpeta (nunca se sube a git).
3. Copia `.env.example` como `.env` y rellena los IDs de cada calendario
   (Ajustes del calendario → "Integrar calendario" → "ID de calendario"):
   `CAL_ID_RAFAEL`, `CAL_ID_LAURA`, `CAL_ID_JOAQUIN`, `CAL_ID_SIENNA`, `CAL_ID_FAMILIA`.
4. Desde un ordenador con navegador (no el Pi headless), con la cuenta de
   Google que "aloja" los 5 calendarios (solo hace falta autorizar UNA cuenta,
   no una por persona — ver más abajo cómo comparten calendario Rafael y Laura):
   ```bash
   python3 google_calendar.py --auth
   ```
   Esto abre el navegador para autorizar el acceso y genera `token.json`.
5. Copia `credentials.json`, `token.json` y `.env` al Raspberry Pi, en la
   misma carpeta que `app.py`.

### Que las dos personas puedan editar desde su propio móvil

Los 5 calendarios viven bajo UNA sola cuenta de Google (la que autorizaste
en el paso 4). Para que la otra persona pueda añadir/editar eventos desde
su propio móvil sin tocar esta app:

1. Google Calendar (web) → pasa el ratón sobre cada calendario → los 3
   puntos → "Configuración y uso compartido" → "Compartir con determinadas
   personas" → añade su email.
2. En el permiso, elige **"Hacer cambios en los eventos"** (no "Ver todos
   los detalles", que es de solo lectura).
3. Ella acepta la invitación por email — los calendarios aparecen solos en
   su app de Google Calendar del móvil, con su propia cuenta.

Mientras no completes esto, la app funciona con normalidad — el calendario
simplemente aparece vacío con un aviso, y `+ Add Event` avisa en vez de fallar.

## Instalación local (para probar antes del Pi)

```bash
pip install -r requirements.txt
python3 app.py
```

Abre `http://localhost:5000` en el navegador. La base de datos (`skylight.db`)
se crea sola la primera vez, con las recetas y tareas de ejemplo.

## Estructura

```
app.py              # Servidor Flask + modelos + API REST
requirements.txt
static/index.html   # Frontend (HTML/CSS/JS, sin frameworks)
```

## API

- `GET/POST /api/tasks`, `PATCH/DELETE /api/tasks/<id>` — Grocery y To-Do
- `GET/POST /api/recipes`, `PUT/DELETE /api/recipes/<id>`
- `GET /api/meals`, `PUT /api/meals/<day>/<slot>`
- `POST /api/meals/generate` — genera la semana sin repetir plato por categoría
  y añade los ingredientes que falten a la Grocery List
- `GET /api/events?start=YYYY-MM-DD&end=YYYY-MM-DD` — eventos combinados de
  los 3 calendarios (caché de 2 min)
- `POST /api/events` — crea un evento real en el calendario del owner elegido
- `GET /api/events/status` — para saber si Google ya está configurado
- `GET /api/weather` — clima actual + pronóstico 3 días (caché 15 min)
- `GET /api/photos` — lista de fotos en la carpeta sincronizada
- `GET /photos/<filename>` — sirve una foto individual

## Instalación completa en el Raspberry Pi (modo kiosko)

Además de correr el backend, el Pi arranca directo en modo "electrodoméstico":
pantalla completa, sin escritorio visible, listo para usar.

Esto asume **Raspberry Pi OS de 64 bits** con **labwc** (Wayland) como gestor
de ventanas — el que trae por defecto cualquier instalación reciente con
escritorio. Comprueba cuál tienes con `echo $XDG_SESSION_TYPE` (debería
decir `wayland`) antes de seguir.

1. Clona el repo en el Pi (el nombre de la carpeta no importa, `install.sh`
   detecta la ruta real sola): `git clone <tu-repo> ~/tu-carpeta`
2. `cd ~/tu-carpeta && pip install --break-system-packages -r requirements.txt`
3. `bash setup/install.sh` — instala Chromium, el servicio systemd del backend,
   el autostart del kiosko (labwc), y los permisos de sudo de mínimo privilegio
   (solo `nmcli` y `reboot`, nada más). Detecta tu usuario real automáticamente
   (con `whoami`) — no hace falta que se llame "pi".
4. Pasos manuales que quedan (el script te los recuerda al final):
   - `sudo raspi-config` → activar autologin de escritorio
   - Pegar `setup/labwc-keybinds-snippet.xml` en `~/.config/labwc/rc.xml`,
     sustituyendo `__USER__` por tu usuario real
     (atajos de teclado: Ctrl+Alt+K salir del kiosko, Ctrl+Alt+R volver a
     entrar, Ctrl+Alt+T abrir una terminal — red de seguridad física si la
     pantalla táctil deja de responder)
   - `sudo reboot` para probarlo de verdad

**Nota honesta sobre el cursor del ratón:** bajo Wayland/labwc no existe
todavía un equivalente fiable a `unclutter` (la herramienta que usábamos en
X11 para esconderlo tras un instante quieto) — es una limitación conocida
de labwc a día de hoy, sin solución limpia en la comunidad. El cursor se
queda visible en pantalla. Es solo cosmético, no afecta a nada funcional.

### Wifi, salir del kiosko, y actualizar — desde la propia pantalla

- **Settings → Wifi**: escanea redes cercanas y te deja conectar tocando
  la pantalla, sin tocar la configuración del sistema a mano.
- **Settings → "Salir del kiosko"**: cierra Chromium y muestra el escritorio
  por debajo, para poder conectar un teclado y trabajar directamente. Para
  volver a entrar sin reiniciar todo el Pi, usa el atajo Ctrl+Alt+R.
- **Settings → "Actualizar sistema"**: hace `git pull` en el proyecto,
  reinstala dependencias si cambiaron, y reinicia el Pi entero — la forma
  más simple y fiable de asegurar que todo (backend, kiosko, frontend)
  arranca limpio con el código nuevo.

### Nota de seguridad sobre los permisos

La app puede ejecutar `sudo` SOLO para `nmcli` y `reboot` (ver
`setup/sudoers-skylight`) — nada más queda abierto. El SSID y la contraseña
de wifi que escribes en pantalla se pasan siempre como argumentos separados
al comando, nunca como texto concatenado, así que no hay forma de "inyectar"
comandos adicionales aunque la contraseña tenga caracteres raros.

## Notas de seguridad

- Nunca commitear `skylight.db` (datos reales), ni `credentials.json`, `token.json`
  o `.env` — todos están en `.gitignore`.
