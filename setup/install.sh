#!/bin/bash
# setup/install.sh
# Ejecutar UNA VEZ en el Raspberry Pi, desde dentro de la carpeta del proyecto:
#   cd ~/tu-carpeta-del-proyecto && bash setup/install.sh
#
# Qué hace:
#   1. Instala paquetes de sistema que faltan (chromium, network-manager)
#   2. Copia el servicio systemd del backend y lo activa
#   3. Configura el autostart de labwc (modo kiosko)
#   4. Instala las reglas de sudoers de mínimo privilegio
#
# Los archivos de plantilla (setup/skylight-backend.service, setup/labwc-autostart,
# setup/sudoers-skylight) usan "__USER__" y "__PROJECT_DIR__" en vez de valores
# fijos — este script los sustituye por tu usuario real (whoami) y la ruta
# real donde vive el proyecto (detectada sola, sea cual sea el nombre que le
# hayas puesto a la carpeta — "skylight-backend", "astrobot", lo que sea).
#
# NO toca tu rc.xml de labwc automáticamente (los atajos de teclado hay
# que pegarlos a mano — ver setup/labwc-keybinds-snippet.xml — para no
# arriesgarnos a romper atajos que ya tengas).

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CURRENT_USER="$(whoami)"
echo "Proyecto detectado en: $PROJECT_DIR"
echo "Usuario detectado: $CURRENT_USER"

# Función helper: sustituye ambos placeholders en un archivo de plantilla.
# Usa "|" como delimitador de sed (no "/") porque PROJECT_DIR contiene barras.
render_template(){
  sed -e "s/__USER__/$CURRENT_USER/g" -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" "$1"
}

echo ""
echo "== 1. Paquetes de sistema =="
sudo apt-get update -qq
sudo apt-get install -y -qq chromium-browser network-manager

echo ""
echo "== 2. Servicio systemd del backend =="
render_template "$PROJECT_DIR/setup/skylight-backend.service" | sudo tee /etc/systemd/system/skylight-backend.service > /dev/null
sudo systemctl daemon-reload
sudo systemctl enable skylight-backend.service
sudo systemctl restart skylight-backend.service
sleep 1
if systemctl is-active --quiet skylight-backend.service; then
  echo "Backend activo y arrancará solo en cada reinicio."
else
  echo "⚠️  El backend no arrancó bien. Revisa con: systemctl status skylight-backend.service"
fi

echo ""
echo "== 3. Autostart del kiosko (labwc) =="
chmod +x "$PROJECT_DIR/setup/kiosk-autostart.sh"
mkdir -p ~/.config/labwc
render_template "$PROJECT_DIR/setup/labwc-autostart" > ~/.config/labwc/autostart
chmod +x ~/.config/labwc/autostart
echo "Autostart de labwc instalado en ~/.config/labwc/autostart."
echo ""
echo "  IMPORTANTE (manual, no lo hace este script):"
echo "  Activa el autologin gráfico con: sudo raspi-config"
echo "  -> System Options -> Boot / Auto Login -> Desktop Autologin"
echo "  Así el Pi entra directo al escritorio (y por tanto al kiosko) sin"
echo "  pedir usuario/contraseña en cada arranque."

echo ""
echo "== 4. Permisos de sudo de mínimo privilegio (wifi + reboot) =="
render_template "$PROJECT_DIR/setup/sudoers-skylight" | sudo tee /etc/sudoers.d/skylight > /dev/null
sudo chmod 440 /etc/sudoers.d/skylight
sudo visudo -c
echo "sudoers verificado sin errores de sintaxis."

echo ""
echo "== Instalación completa =="
echo "Pasos manuales que TE QUEDAN:"
echo "  1. sudo raspi-config -> activar autologin de escritorio (arriba)"
echo "  2. Pega los atajos de setup/labwc-keybinds-snippet.xml en ~/.config/labwc/rc.xml"
echo "     (sustituyendo __PROJECT_DIR__ por: $PROJECT_DIR)"
echo "  3. Reinicia el Pi para probarlo de verdad: sudo reboot"
