@echo off
rem This file lives in scripts\. ROOT = the app folder (one level up).
for %%I in ("%~dp0..") do set "ROOT=%%~fI\"
rem Right-click > "Run as administrator".
rem 1) Stop the backend that was started with admin rights (the normal launcher cannot stop it).
rem    Only this app's backend is stopped (appctl.py), never another program on the same port.
rem 2) Ask the guard task to restart everything AS THE NORMAL USER (so launcher can manage it later).
rem    Do NOT run restart_all.bat here: it would start workers/Vite with admin rights.
cd /d "%ROOT%"
echo Stopping this app's backend ...
"%ROOT%backend\venv\Scripts\python.exe" -c "import appctl; appctl.stop_backend()"
echo restart> "%ROOT%logs\_request.txt"
echo Done. The guard task will restart the app as the normal user within 1 minute.
echo Then run start_all.bat to open the page.
pause
