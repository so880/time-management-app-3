@echo off
rem ============================================================
rem  Start everything WITHOUT opening any windows (launcher.py via pythonw).
rem    start_all.bat        -> start, then open the page in the browser
rem    start_all.bat auto   -> start only (for Task Scheduler at logon)
rem    start_all.bat widget -> bring back the quick widget only
rem  Logs: logs\launcher.log, logs\backend.log, logs\frontend.log
rem  Stop: stop_all.bat (locks only) / stop_all.bat all (everything)
rem ============================================================
if not exist "%~dp0backend\venv\Scripts\pythonw.exe" (
  echo ============================================================
  echo  ERROR: venv not found. Run scripts\setup_env.bat first.
  echo ============================================================
  pause
  exit /b 1
)
start "" "%~dp0backend\venv\Scripts\pythonw.exe" "%~dp0launcher.py" %1
exit /b 0
