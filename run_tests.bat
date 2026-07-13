@echo off
rem Run backend tests (pytest). Run update.bat once before first use.
cd /d "%~dp0backend"
venv\Scripts\python.exe -m pytest -v
pause
