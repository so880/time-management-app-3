@echo off
rem This file lives in scripts\. ROOT = the app folder (one level up).
for %%I in ("%~dp0..") do set "ROOT=%%~fI\"
chcp 65001 >nul
rem Remove the guard task. Refuses while locked.
"%ROOT%backend\venv\Scripts\python.exe" "%ROOT%stop_guard.py" check_only
if errorlevel 1 (
  echo 制限中のため、見守りタスクは解除できません。
  pause
  exit /b 1
)
schtasks /Delete /TN "FocusCafe Guard" /F
schtasks /Delete /TN "FocusCafe Guard Logon" /F
echo 解除しました。
pause
