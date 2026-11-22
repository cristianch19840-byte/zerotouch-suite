@echo off
chcp 65001 >nul
title ZeroTouch TITAN-OS v16.0 — Launcher Maestro
setlocal
cd /d "%~dp0"
set PY=C:\Users\CASADIK\AppData\Local\Programs\Python\Python312\python.exe
if not exist "%PY%" set PY=python

:MENU
cls
echo ====================================================================
echo           ZEROTOUCH TITAN-OS v16.0 — CENTRO DE MANDO
echo ====================================================================
echo   [1] Abrir Dashboard Web + API v2 + SSE Live (Recomendado)
echo   [2] Levantar Solo Servidor TITAN-OS v16 (titan_cli.py serve)
echo   [3] Diagnostico Integral (Doctor + Seguridad + AEGIS Drift)
echo   [4] Crear Backup Cifrado (.ztvault HMAC-SHA256)
echo   [5] Ejecutar Suite E2E Global (20 Fases)
echo   [0] Salir
echo ====================================================================
set /p op=Selecciona una opcion [1-5, 0]: 

if "%op%"=="1" (
    start "" "http://127.0.0.1:8765"
    "%PY%" dashboard_web.py
    goto MENU
)
if "%op%"=="2" (
    start "" "http://127.0.0.1:8765"
    "%PY%" titan_cli.py serve --port 8765
    goto MENU
)
if "%op%"=="3" (
    "%PY%" titan_cli.py doctor
    "%PY%" titan_cli.py audit --strict
    pause
    goto MENU
)
if "%op%"=="4" (
    "%PY%" titan_cli.py backup create --label manual
    pause
    goto MENU
)
if "%op%"=="5" (
    "%PY%" test_titan_e2e_v16.py
    pause
    goto MENU
)
if "%op%"=="0" exit /b 0
goto MENU