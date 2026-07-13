@echo off
rem Quick check for money API (ASCII only)
chcp 65001 >nul
echo === GET /api/health ===
curl -s http://127.0.0.1:8000/api/health
echo.
echo.
echo === GET /api/money/entries (init defaults) ===
curl -s http://127.0.0.1:8000/api/money/entries
echo.
echo.
echo === POST spend 500 TEST ===
curl -s -X POST http://127.0.0.1:8000/api/money/entries -H "Content-Type: application/json" -d "{\"kind\":\"spend\",\"date\":\"2026-07-06\",\"amount\":500,\"category\":\"TEST-cat\",\"detail\":\"TEST-item\"}"
echo.
echo.
echo === POST spend 5000 TEST (should be judged high) ===
curl -s -X POST http://127.0.0.1:8000/api/money/entries -H "Content-Type: application/json" -d "{\"kind\":\"spend\",\"date\":\"2026-07-06\",\"amount\":5000,\"category\":\"TEST-cat\",\"detail\":\"TEST-item2\"}"
echo.
echo.
echo === GET /api/life/summary money block ===
curl -s "http://127.0.0.1:8000/api/life/summary?date=2026-07-06"
echo.
echo.
echo === cleanup: DELETE ids 1 and 2 ===
curl -s -X DELETE http://127.0.0.1:8000/api/money/entries/1
curl -s -X DELETE http://127.0.0.1:8000/api/money/entries/2
echo.
pause
