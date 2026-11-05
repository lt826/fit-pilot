@echo off
title FitPilot Launcher
cd /d %~dp0

echo ================================================
echo   FitPilot one-click launcher
echo   (Start Docker / Qdrant yourself first)
echo ================================================
echo.

echo [1/3] Checking Qdrant ...
curl -s -o nul -m 3 http://localhost:6333
if errorlevel 1 (
    echo   [!] Qdrant NOT running - knowledge QA will degrade to BM25 only
    echo       Run this first:  docker compose up -d qdrant
) else (
    echo   [OK] Qdrant online
)
echo.

echo [2/3] Starting backend FastAPI  :8000 ...
start "FitPilot-Backend" cmd /k ".venv\Scripts\python.exe scripts\run_server.py"

echo [3/3] Starting frontend Vite    :5174 ...
start "FitPilot-Frontend" cmd /k "cd web && npm run dev -- --port 5174"

echo.
echo Waiting for services, then opening browser...
timeout /t 10 >nul
start http://localhost:5174
echo.
echo Done. To STOP: close the [FitPilot-Backend] / [FitPilot-Frontend] windows.
pause
