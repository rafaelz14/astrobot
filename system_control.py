"""
Control de sistema — Fase "electrodoméstico".

Todo lo de aquí ejecuta comandos del sistema operativo (nmcli, systemctl,
git, reboot). Se apoya en las reglas de /etc/sudoers.d/skylight, que dan
permiso SOLO a esos comandos exactos, sin contraseña, al usuario que corre
la app — nunca sudo sin restricciones.

IMPORTANTE sobre seguridad: todos los subprocess.run() de aquí pasan los
argumentos como LISTA, nunca como string concatenado con shell=True. Esto
es deliberado: si se construyera el comando como texto (p. ej.
f"nmcli ... password {password}"), un carácter especial en la contraseña
de wifi podría inyectar comandos adicionales. Con listas de argumentos,
eso no es posible aunque la contraseña contenga comillas, `;`, `$`, etc.
"""

import subprocess
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _run(cmd, timeout=15):
    """Ejecuta un comando (lista de argumentos) y devuelve (ok, stdout/stderr)."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, (result.stderr or result.stdout).strip()
    except FileNotFoundError:
        return False, f"Comando no encontrado: {cmd[0]} (¿estás en el Pi real?)"
    except subprocess.TimeoutExpired:
        return False, "El comando tardó demasiado y se canceló."
    except Exception as e:
        return False, str(e)


# ==================== WIFI ====================

def wifi_status():
    """Estado actual de la conexión wifi."""
    ok, out = _run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"])
    if not ok:
        return {"available": False, "error": out}

    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) >= 4 and parts[1] == "wifi":
            return {
                "available": True,
                "connected": parts[2] == "connected",
                "ssid": parts[3] if parts[2] == "connected" else None,
                "device": parts[0],
            }
    return {"available": False, "error": "No se encontró un dispositivo wifi"}


def wifi_scan():
    """Lista de redes wifi visibles. Requiere sudo (nmcli lo pide para rescan)."""
    ok, out = _run(["sudo", "nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list", "--rescan", "yes"], timeout=25)
    if not ok:
        return {"available": False, "error": out, "networks": []}

    networks = []
    seen = set()
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) >= 3 and parts[0] and parts[0] not in seen:
            seen.add(parts[0])
            networks.append({
                "ssid": parts[0],
                "signal": int(parts[1]) if parts[1].isdigit() else 0,
                "secured": bool(parts[2]),
            })
    networks.sort(key=lambda n: -n["signal"])
    return {"available": True, "networks": networks}


def wifi_connect(ssid, password):
    """Conecta a una red wifi. ssid/password van como argumentos separados,
    nunca concatenados en un string de shell (ver nota de seguridad arriba)."""
    if not ssid:
        return {"success": False, "error": "SSID vacío"}

    cmd = ["sudo", "nmcli", "device", "wifi", "connect", ssid]
    if password:
        cmd += ["password", password]

    ok, out = _run(cmd, timeout=30)
    return {"success": ok, "message": out if ok else None, "error": None if ok else out}


# ==================== SISTEMA (salir del kiosko / actualizar) ====================

def exit_kiosk():
    """Cierra Chromium, dejando visible el escritorio (labwc) por debajo.
    No requiere sudo: Chromium corre como el mismo usuario que la app."""
    ok, out = _run(["pkill", "-f", "chromium"])
    # pkill devuelve código != 0 si no encontró procesos, no es un error real
    return {"success": True, "message": "Kiosko cerrado. Deberías ver el escritorio."}


def update_and_restart(repo_dir):
    """
    git pull en el repo + reinicio completo del Pi (más simple y fiable que
    intentar reiniciar servicios sueltos: garantiza que TODO — backend,
    kiosko, dependencias — arranca limpio con el código nuevo).

    Programa el reboot 3 segundos en el futuro para poder devolver la
    respuesta HTTP antes de que el sistema se apague.
    """
    ok, out = _run(["git", "-C", repo_dir, "pull"], timeout=60)
    if not ok:
        return {"success": False, "error": f"git pull falló: {out}"}

    pip_ok, pip_out = _run(
        ["pip", "install", "--break-system-packages", "-q", "-r",
         os.path.join(repo_dir, "requirements.txt")],
        timeout=120,
    )

    # Reinicio programado en background, para que esta función pueda
    # devolver la respuesta antes de que el sistema se reinicie de verdad.
    subprocess.Popen(["sudo", "bash", "-c", "sleep 3 && reboot"])

    return {
        "success": True,
        "git_output": out,
        "pip_ok": pip_ok,
        "message": "Actualizado. Reiniciando el sistema en unos segundos...",
    }


def git_version(repo_dir):
    """Hash corto + mensaje del último commit, para mostrar en Settings."""
    ok_hash, out_hash = _run(["git", "-C", repo_dir, "rev-parse", "--short", "HEAD"])
    ok_msg, out_msg = _run(["git", "-C", repo_dir, "log", "-1", "--pretty=%s"])
    if not ok_hash:
        return {"available": False}
    return {
        "available": True,
        "hash": out_hash,
        "message": out_msg if ok_msg else "",
    }
