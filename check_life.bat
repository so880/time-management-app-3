@echo off
rem Quick check for the Life API (L1) - ASCII only to avoid codepage issues
chcp 65001 >nul
echo === GET /api/health ===
curl -s http://127.0.0.1:8000/api/health
echo.
echo.
echo === POST /api/life/schedule (test row) ===
curl -s -X POST http://127.0.0.1:8000/api/life/schedule -H "Content-Type: application/json" -d "{\"weekday\":0,\"start\":\"08:50\",\"end\":\"10:20\",\"title\":\"TEST-block\"}"
echo.
echo.
echo === GET /api/life/day?date=2026-07-06 ===
curl -s "http://127.0.0.1:8000/api/life/day?date=2026-07-06"
echo.
pause
