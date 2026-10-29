"""Arranca el meter móvil (lo llama "Meter movil.cmd", que va como administrador).

1. Cierra un servidor anterior.
2. Busca actualizaciones en GitHub (actualizar.py).
3. Si LOA Logs está cerrado: aplica el parche si hace falta y lo abre.
4. Mantiene el servidor en marcha; si una actualización cambia su código, lo reinicia solo.
"""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.chdir(HERE)
sys.path.insert(0, str(HERE))
NO_WINDOW = 0x08000000
REINICIAR = 3  # código con el que server.py pide que lo vuelvan a lanzar


def procesos():
    out = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True,
                         creationflags=NO_WINDOW).stdout
    return {l.split('","')[0].strip('"').lower() for l in out.splitlines() if l}


def cerrar_servidor_anterior():
    ps = ("Get-CimInstance Win32_Process -Filter \"name like 'python%'\" | "
          f"? {{ $_.CommandLine -match 'server\\.py' -and $_.ProcessId -ne {os.getpid()} }} | "
          "% { Stop-Process -Id $_.ProcessId -Force }")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], creationflags=NO_WINDOW)


def main():
    cerrar_servidor_anterior()
    try:
        import actualizar
        cambios = actualizar.actualizar()
        print("Actualizado: " + ", ".join(cambios) if cambios else "Meter movil al día.")
    except Exception as e:
        print(f"No se pudo comprobar actualizaciones ({e}). Sigo con la versión que hay.")

    from ruta_loalogs import carpeta_loalogs
    exe = carpeta_loalogs() / "LOA Logs.exe"
    if "loa logs.exe" in procesos():
        print("LOA Logs ya está abierto.")
    elif exe.exists():
        # con LOA Logs cerrado se puede parchear sin riesgo (si ya lo está, no hace nada)
        subprocess.run([sys.executable, "parchear_loalogs.py"])
        print("Abriendo LOA Logs...")
        os.startfile(str(exe))
    else:
        print("LOA Logs no está instalado: el directo no tendrá datos.")

    while True:
        r = subprocess.run([sys.executable, "-u", "server.py"]).returncode
        if r != REINICIAR:
            break
        print("\nEl servidor se ha actualizado; reiniciándolo...\n")


if __name__ == "__main__":
    main()
