@echo off
rem ============================================================
rem  STOP (guarded)
rem  - Default: stops ONLY the locks (game blocker + site blocker).
rem    The widget, backend, page and PC tracker keep running.
rem  - "stop_all.bat all": stops EVERYTHING (backend/frontend/widget/...).
rem  - If game/site restrictions are still active, you must type
rem    a reason (10+ chars). The reason is logged with timestamp and
rem    the locks stay released until the date changes.
rem ============================================================
"%~dp0backend\venv\Scripts\python.exe" "%~dp0stop_guard.py" %*
