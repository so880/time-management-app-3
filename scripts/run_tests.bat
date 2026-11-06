@echo off
rem This file lives in scripts\. ROOT = the app folder (one level up).
for %%I in ("%~dp0..") do set "ROOT=%%~fI\"
rem Run backend tests (pytest). Run update.bat once before first use.
cd /d "%ROOT%backend"
venv\Scripts\python.exe -m pytest -v
pause
