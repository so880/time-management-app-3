@echo off
rem Start the React dev server (Vite).
rem Keep this window open while using the app. Close it (or Ctrl+C) to stop.
if not exist "%~dp0frontend\node_modules" (
  echo ERROR: node_modules not found. Run this from the LOCAL C: drive folder,
  echo or run setup.bat first on a new PC.
  pause
  exit /b 1
)
cd /d "%~dp0frontend"
start "" http://localhost:5173
call npm run dev
pause
