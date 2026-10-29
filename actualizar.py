"""Actualiza esta carpeta con la última versión publicada en GitHub.

Lee el repositorio de actualizar.json ({"repo": "usuario/nombre", "rama": "main"}), mira el último
commit y, si es nuevo, descarga el zip de ese commit y copia sus archivos encima de esta carpeta.
No necesita git ni iniciar sesión (el repositorio es público).

Uso: python actualizar.py [--forzar]   Devuelve (como programa): 0 sin cambios, 10 si actualizó, 1 si falló.
"""
import io
import json
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONF = HERE / "actualizar.json"
VERSION = HERE / ".version"          # commit instalado (no se sube a GitHub)
LOG = HERE / "actualizar.log"
# Archivos de este PC que nunca se tocan aunque vengan en el repositorio.
LOCALES = {".version", "actualizar.log", "vigilar_parche.log", "posicion_original.json",
           "peticion.json", "peticion_resultado.txt"}


def log(msg):
    linea = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
    print(msg)
    try:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(linea + "\n")
    except OSError:
        pass


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "meter-movil-actualizador",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def actualizar(forzar=False):
    """Devuelve la lista de archivos cambiados (vacía si ya estaba al día)."""
    conf = json.loads(CONF.read_text(encoding="utf-8"))
    repo, rama = conf["repo"], conf.get("rama", "main")
    sha = json.loads(_get(f"https://api.github.com/repos/{repo}/commits/{rama}"))["sha"]
    actual = VERSION.read_text().strip() if VERSION.exists() else ""
    if sha == actual and not forzar:
        return []
    datos = _get(f"https://codeload.github.com/{repo}/zip/{sha}", timeout=60)
    cambiados = []
    with zipfile.ZipFile(io.BytesIO(datos)) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            # el zip trae todo dentro de "<repo>-<sha>/"
            partes = Path(info.filename).parts[1:]
            if not partes or partes[0] in LOCALES or partes[0].startswith("."):
                continue
            destino = HERE.joinpath(*partes)
            if HERE not in destino.resolve().parents:
                continue  # nada fuera de esta carpeta
            nuevo = z.read(info)
            if destino.exists() and destino.read_bytes() == nuevo:
                continue
            destino.parent.mkdir(parents=True, exist_ok=True)
            tmp = destino.with_name(destino.name + ".nuevo")
            tmp.write_bytes(nuevo)
            tmp.replace(destino)
            cambiados.append("/".join(partes))
    VERSION.write_text(sha)
    log(f"Actualizado a {sha[:7]}: " + (", ".join(cambiados) or "sin cambios en archivos"))
    return cambiados


if __name__ == "__main__":
    try:
        c = actualizar("--forzar" in sys.argv)
    except Exception as e:
        log(f"No se pudo comprobar actualizaciones: {e}")
        sys.exit(1)
    if not c:
        print("Meter movil al día.")
    sys.exit(10 if c else 0)
