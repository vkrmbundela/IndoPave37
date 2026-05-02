@echo off
title FlexPave-Opt Launcher
echo Starting FlexPave-Opt...

start "FlexPave Backend" cmd /k "cd /d %~dp0 && python -m mep_opt.web.main"
timeout /t 2 /nobreak >nul
start "FlexPave Frontend" cmd /k "cd /d %~dp0\frontend && npm run dev"

echo.
echo Backend: http://127.0.0.1:8000
echo Frontend: http://localhost:5173
echo.
echo Close both terminal windows to stop.
