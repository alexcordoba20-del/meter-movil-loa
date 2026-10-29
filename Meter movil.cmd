@echo off
title Meter movil LOA
rem Lanzador fijo (no se actualiza): toda la logica esta en lanzar.py.
rem Va como administrador para poder copiar la ventana de LOA Logs (que tambien va como admin).
net session >nul 2>&1 || (powershell -NoProfile -Command "Start-Process -Verb RunAs -FilePath '%~f0'" & exit /b)
cd /d "%~dp0"
python -u lanzar.py
pause
