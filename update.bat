@echo off
rem Install/update backend packages (run after requirements.txt changes)
cd /d "%~dp0backend"
venv\Scripts\python.exe -m pip install -r requirements.txt
echo.
echo ============================================
echo  UPDATE COMPLETE!
echo ============================================
pause
