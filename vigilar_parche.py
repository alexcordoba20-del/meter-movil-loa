"""Vigila LOA Logs y vuelve a aplicar el parche del meter móvil cuando se actualiza.

Se arranca al iniciar sesión con la tarea programada "Meter movil - parche LOA Logs"
(la crea el instalador, con privilegios altos para poder reiniciar LOA Logs sin UAC).

- Cada 20 s mira si LOA Logs.exe ha cambiado. Si ha perdido el parche, lo aplica
  (aunque esté abierto: se aparta el .exe en uso y se pone el parcheado en su sitio).
- Si LOA Logs estaba abierto, lo reinicia para que el parche se active, pero SOLO con
  Lost Ark cerrado (cerrar LOA Logs/nineveh con el juego abierto deja WinDivert enganchado).
- Registro: vigilar_parche.log en esta carpeta.
"""
import ctypes
import importlib
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import parchear_loalogs as P  # noqa: E402
from ruta_loalogs import carpeta_loalogs  # noqa: E402

LOG = HERE / "vigilar_parche.log"
NO_WINDOW = 0x08000000
INTERVALO = 20


def log(msg):
    linea = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
    try:
        if LOG.exists() and LOG.stat().st_size > 512_000:
            LOG.replace(LOG.with_suffix(".log.1"))
        with LOG.open("a", encoding="utf-8") as f:
            f.write(linea + "\n")
    except OSError:
        pass


def procesos():
    try:
        out = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True,
                             creationflags=NO_WINDOW, timeout=15).stdout
    except Exception:
        return set()
    return {l.split('","')[0].strip('"').lower() for l in out.splitlines() if l}


def avisar(texto):
    """Notificación de Windows (sin dependencias)."""
    ps = ("[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime]>$null;"
          "$x=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(1);"
          f"$x.GetElementsByTagName('text')[0].AppendChild($x.CreateTextNode('Meter movil: {texto}'))>$null;"
          "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
          "'{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe').Show("
          "[Windows.UI.Notifications.ToastNotification]::new($x))")
    try:
        subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps], creationflags=NO_WINDOW)
    except Exception:
        pass


def reiniciar_loalogs(exe):
    log("Reiniciando LOA Logs para activar el parche (Lost Ark cerrado).")
    for im in ("LOA Logs.exe", "nineveh.exe"):
        subprocess.run(["taskkill", "/f", "/im", im], capture_output=True, creationflags=NO_WINDOW)
        time.sleep(2)
    P.limpiar_viejos(exe)
    # Se abre en la sesión del usuario; como esta tarea va elevada, no sale UAC.
    os.startfile(str(exe))
    avisar("LOA Logs actualizado y parcheado")


def main():
    ctypes.windll.kernel32.CreateMutexW(None, False, "MeterMovilVigilaParche")
    if ctypes.windll.kernel32.GetLastError() == 183:  # ya hay otro vigilante
        return
    log("Vigilante arrancado.")
    visto = None          # (tamaño, fecha) del .exe ya comprobado
    pendiente = False     # parcheado con LOA Logs abierto: falta reiniciarlo
    proxima_act = 0
    while True:
        # Actualizaciones desde GitHub cada 10 min
        if time.time() >= proxima_act:
            proxima_act = time.time() + 600
            try:
                import actualizar
                cambios = actualizar.actualizar()
                if cambios:
                    log("Actualizado desde GitHub: " + ", ".join(cambios))
                    if "vigilar_parche.py" in cambios:
                        log("El vigilante ha cambiado: me reinicio.")
                        sys.exit(1)  # la tarea programada lo vuelve a abrir al minuto
                    if "parchear_loalogs.py" in cambios or "ruta_loalogs.py" in cambios:
                        importlib.reload(P)
                        visto = None  # vuelve a comprobar (y rehacer) el parche
            except SystemExit:
                raise
            except Exception as e:
                log(f"No se pudo comprobar actualizaciones: {e!r}")
        try:
            exe = carpeta_loalogs() / "LOA Logs.exe"
            if exe.exists():
                st = exe.stat()
                firma = (st.st_size, st.st_mtime_ns)
                if firma != visto:
                    time.sleep(5)  # por si el actualizador aún está escribiendo
                    try:
                        estado = P.parchear(exe, log=log)
                    except P.ErrorParche as e:
                        log("ERROR: " + str(e))
                        avisar("no se pudo parchear la nueva versión de LOA Logs")
                        estado = "error"
                    except PermissionError:
                        log("El .exe está ocupado; reintento en un rato.")
                        estado = "reintentar"
                    if estado != "reintentar":
                        st = exe.stat()
                        visto = (st.st_size, st.st_mtime_ns)
                    if estado == "parcheado_en_uso":
                        pendiente = True
                    elif estado == "parcheado":
                        avisar("LOA Logs actualizado y parcheado")
                if pendiente:
                    ps = procesos()
                    if "loa logs.exe" not in ps:
                        pendiente = False  # lo han cerrado: al abrirlo ya va parcheado
                        P.limpiar_viejos(exe)
                        avisar("parche listo, se activa al abrir LOA Logs")
                    elif "lostark.exe" not in ps:
                        pendiente = False
                        reiniciar_loalogs(exe)
        except Exception as e:  # el vigilante no debe morir nunca
            log(f"Fallo inesperado: {e!r}")
        time.sleep(INTERVALO)


if __name__ == "__main__":
    main()
