@echo off
rem Start the FastAPI dev server.
rem Keep this window open while using the app. Close it (or Ctrl+C) to stop.
if not exist "%~dp0backend\venv\Scripts\python.exe" (
  echo ERROR: venv not found. Run this from the LOCAL C: drive folder,
  echo or run setup.bat first on a new PC.
  pause
  exit /b 1
)
cd /d "%~dp0backend"
rem Call the venv python directly (no "activate": it breaks if the
rem folder is renamed, because activate hard-codes the old path).
venv\Scripts\python.exe -m fastapi dev app/main.py
pause
