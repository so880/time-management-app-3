@echo off
rem This file lives in scripts\. ROOT = the app folder (one level up).
for %%I in ("%~dp0..") do set "ROOT=%%~fI\"
rem Install/update backend packages (run after requirements.txt changes)
cd /d "%ROOT%backend"
venv\Scripts\python.exe -m pip install -r requirements.txt
echo.
echo ============================================
echo  UPDATE COMPLETE!
echo ============================================
pause
