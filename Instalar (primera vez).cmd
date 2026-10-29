@echo off
title Instalar Meter movil LOA
rem Prepara este PC: Python + librerias, regla de firewall y parche de LOA Logs.
net session >nul 2>&1 || (powershell -NoProfile -Command "Start-Process -Verb RunAs -FilePath '%~f0'" & exit /b)
cd /d "%~dp0"

echo [1/4] Python...
python -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
if errorlevel 1 (
  echo     No hay Python 3.10+ en este PC.
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar_python.ps1" || (echo     ERROR: no se pudo instalar Python. Instalalo a mano desde python.org ^(marcando "Add to PATH"^) y vuelve a ejecutar esto. & pause & exit /b 1)
  rem esta ventana no ve el PATH nuevo: lo anadimos a mano
  set "PATH=%ProgramFiles%\Python313;%ProgramFiles%\Python313\Scripts;%PATH%"
)
python --version || (echo     ERROR: Python instalado pero no se encuentra. Reinicia el PC y vuelve a ejecutar esto. & pause & exit /b 1)

echo [2/4] Librerias (websockets, pillow, brotli)...
python -m pip install --upgrade --quiet websockets pillow brotli || (echo     ERROR instalando librerias & pause & exit /b 1)

echo [3/4] Regla de firewall (puerto 8765, solo red local)...
netsh advfirewall firewall delete rule name="Meter movil (LOA) 8765" >nul 2>&1
netsh advfirewall firewall add rule name="Meter movil (LOA) 8765" dir=in action=allow protocol=TCP localport=8765 remoteip=localsubnet >nul

echo [4/4] Parche de LOA Logs...
:buscar_loalogs
python -c "from ruta_loalogs import carpeta_loalogs as c; import sys; sys.exit(0 if (c()/'LOA Logs.exe').exists() else 1)"
if errorlevel 1 (
  echo     LOA Logs no esta instalado en este PC. Abro su pagina de descarga oficial...
  echo     Descarga el instalador .exe de la ultima version, instalalo y vuelve aqui.
  start "" "https://github.com/snoww/loa-logs/releases/latest"
  echo     Cuando este instalado, pulsa una tecla para seguir ^(o cierra esta ventana para salir^).
  pause >nul
  goto buscar_loalogs
)
tasklist | find /i "LOSTARK.exe" >nul && (echo     Lost Ark esta abierto: cierralo y vuelve a ejecutar esto. & pause & exit /b 1)
tasklist | find /i "LOA Logs.exe" >nul && (
  echo     Cierra LOA Logs ^(icono de la bandeja ^> Quit^) y pulsa una tecla...
  pause >nul
)
python parchear_loalogs.py

echo [+] Re-parcheo automatico cuando LOA Logs se actualice...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar_tarea.ps1" || echo     AVISO: no se pudo crear la tarea; tendras que repetir este instalador tras cada actualizacion.

echo.
echo Listo. Abre LOA Logs y luego "Meter movil.cmd". En el movil abre la direccion que salga.
pause
