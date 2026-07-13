@echo off
rem Start everything: backend (FastAPI) + frontend (React)
rem                  + game blocker + quick-start widget + PC tracker
rem Close the windows to stop.
if not exist "%~dp0backend\venv\Scripts\python.exe" (
  echo ============================================================
  echo  ERROR: venv not found.
  echo  You are probably running the BACKUP COPY on Google Drive.
  echo  Please run the one in the LOCAL folder on the C: drive.
  echo  If this IS a new PC, run setup.bat here first.
  echo ============================================================
  pause
  exit /b 1
)
cd /d "%~dp0"

rem --- Pull newer DB from Google Drive if another PC updated it ---
"%~dp0backend\venv\Scripts\python.exe" "%~dp0sync_db_pull.py"

rem --- Game blocker (pythonw = no console window) ---
start "" "%~dp0backend\venv\Scripts\pythonw.exe" "%~dp0blocker.py"

rem --- Quick-start widget (global pythonw: PySide6 is installed there) ---
start "" pythonw "%~dp0quick_widget.py"

rem --- PC screen-time tracker (pythonw = no console window) ---
start "" "%~dp0backend\venv\Scripts\pythonw.exe" "%~dp0pc_tracker.py"

rem --- Backend (minimized console: open it from the taskbar to see logs) ---
start "FocusCafe Backend" /min cmd /c "%~dp0start_backend.bat"

rem Wait a few seconds so the backend is ready before the browser opens
timeout /t 4 /nobreak >nul

rem --- Frontend (minimized console; opens the browser) ---
start "FocusCafe Frontend" /min cmd /c "%~dp0start_frontend.bat"
