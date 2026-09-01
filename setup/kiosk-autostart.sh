#!/bin/bash
# setup/kiosk-autostart.sh
# Lanzado por labwc al iniciar sesión gráfica (ver setup/labwc-autostart).
# Espera a que el backend Flask responda, y abre Chromium a pantalla
# completa apuntando a la app, renderizando nativamente en Wayland.
#
# NOTA sobre el salvapantallas: labwc no tiene sistema de salvapantallas
# propio (a diferencia de X11), así que no hace falta desactivar nada aquí.
# Si algún día la pantalla se apagara sola, sería a otro nivel (firmware/
# HDMI del propio monitor, o consoleblank del kernel) — no de labwc.
#
# NOTA sobre el cursor: bajo Wayland/labwc no existe todavía un equivalente
# fiable a "unclutter" (X11) para esconder el cursor del ratón tras un
# instante de inactividad. Es una limitación conocida de labwc a día de
# hoy — el cursor se queda visible. Cosmético, no rompe nada.

# --- Esperar a que el backend Flask esté realmente arriba ---
until curl -s -o /dev/null http://localhost:5000/; do
  sleep 1
done

# --- Detectar qué binario de Chromium existe (varía según la versión de
#     Raspberry Pi OS: "chromium" en las más recientes, "chromium-browser"
#     en las anteriores). Así el script funciona en ambas sin tocar nada. ---
if command -v chromium-browser &> /dev/null; then
  CHROMIUM_BIN="chromium-browser"
elif command -v chromium &> /dev/null; then
  CHROMIUM_BIN="chromium"
else
  echo "ERROR: no se encontró ni 'chromium' ni 'chromium-browser' instalado." >&2
  echo "Instálalo con: sudo apt install -y chromium" >&2
  exit 1
fi

# --- Lanzar Chromium en modo kiosko, nativo en Wayland ---
# --ozone-platform=wayland: renderiza directo en Wayland en vez de caer a
#   XWayland (la capa de compatibilidad con X11), más eficiente en un Pi 3.
# --noerrdialogs / --disable-infobars: sin popups de "Chromium no se cerró bien" etc.
# --incognito: no guarda historial/caché entre sesiones (pantalla compartida por la familia)
"$CHROMIUM_BIN" \
  --ozone-platform=wayland \
  --kiosk \
  --noerrdialogs \
  --disable-infobars \
  --disable-session-crashed-bubble \
  --incognito \
  --check-for-update-interval=31536000 \
  http://localhost:5000/