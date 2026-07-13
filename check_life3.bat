@echo off
rem Quick check for summary/week API (ASCII only)
chcp 65001 >nul
echo === GET /api/life/summary?date=2026-07-06 ===
curl -s "http://127.0.0.1:8000/api/life/summary?date=2026-07-06"
echo.
echo.
echo === GET /api/life/week?date=2026-07-06 ===
curl -s "http://127.0.0.1:8000/api/life/week?date=2026-07-06"
echo.
pause
