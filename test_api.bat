@echo off
rem Quick API check (run while start_backend.bat is running)
chcp 65001 >nul
echo === GET /api/health ===
curl -s http://127.0.0.1:8000/api/health
echo.
echo.
echo === GET /api/settings ===
curl -s http://127.0.0.1:8000/api/settings
echo.
echo.
echo === GET /api/logs ===
curl -s http://127.0.0.1:8000/api/logs
echo.
echo.
echo === GET /api/state ===
curl -s http://127.0.0.1:8000/api/state
echo.
pause
