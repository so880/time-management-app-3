@echo off
rem Quick check for recurring assignments + day API (ASCII only)
chcp 65001 >nul
echo === GET /api/health ===
curl -s http://127.0.0.1:8000/api/health
echo.
echo.
echo === POST /api/assignments/recurring (weekly test, due Monday) ===
curl -s -X POST http://127.0.0.1:8000/api/assignments/recurring -H "Content-Type: application/json" -d "{\"title\":\"TEST-weekly\",\"weekday\":0}"
echo.
echo.
echo === GET /api/assignments (instance should exist) ===
curl -s http://127.0.0.1:8000/api/assignments
echo.
echo.
echo === GET /api/settings mustdo check ===
curl -s http://127.0.0.1:8000/api/state >nul
curl -s http://127.0.0.1:8000/api/settings | find "mustdo_list" >nul && echo settings ok
curl -s http://127.0.0.1:8000/api/settings
echo.
pause
