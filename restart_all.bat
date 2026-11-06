@echo off
rem Stop everything, then start again (no windows). Lock workers are restarted immediately.
start "" "%~dp0backend\venv\Scripts\pythonw.exe" "%~dp0launcher.py" restart
exit /b 0
