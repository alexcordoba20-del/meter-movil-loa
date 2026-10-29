"""Encuentra la carpeta de instalación de LOA Logs (registro de Windows o la ruta por defecto)."""
import winreg
from pathlib import Path


def carpeta_loalogs() -> Path:
    for raiz in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for base in (r"Software\Microsoft\Windows\CurrentVersion\Uninstall",
                     r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"):
            try:
                with winreg.OpenKey(raiz, base) as k:
                    for i in range(winreg.QueryInfoKey(k)[0]):
                        try:
                            with winreg.OpenKey(k, winreg.EnumKey(k, i)) as s:
                                if winreg.QueryValueEx(s, "DisplayName")[0] != "LOA Logs":
                                    continue
                                p = Path(winreg.QueryValueEx(s, "InstallLocation")[0].strip('"'))
                                if (p / "LOA Logs.exe").exists():
                                    return p
                        except OSError:
                            continue
            except OSError:
                continue
    return Path.home() / "AppData" / "Local" / "LOA Logs"
