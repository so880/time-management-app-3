@echo off
rem This file lives in scripts\. ROOT = the app folder (one level up).
for %%I in ("%~dp0..") do set "ROOT=%%~fI\"
chcp 65001 >nul
rem Undo harden_install.bat. Refuses while locked. Run as admin (UAC).
"%ROOT%backend\venv\Scripts\python.exe" "%ROOT%stop_guard.py" check_only
if errorlevel 1 (
  echo 制限中のため元に戻せません。ノルマを達成してから実行してください。
  pause
  exit /b 1
)
net session >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
cd /d "%ROOT%"
set "ME=%USERNAME%"
for %%F in (blocker.py site_blocker.py stop_guard.py ensure_workers.py appctl.py launcher.py scripts\harden_install.bat scripts\harden_uninstall.bat backend\app\gate_api.py backend\app\logic.py backend\app\policy.py backend\app\todo_api.py) do (
  icacls "%ROOT%%%F" /reset >nul
)
set "HOSTS=%SystemRoot%\System32\drivers\etc\hosts"
powershell -NoProfile -Command "$h = Get-Content -Raw '%HOSTS%'; $h = [regex]::Replace($h, '(?s)\r?\n# FocusCafe-block begin.*?# FocusCafe-block end[^\r\n]*', ''); Set-Content -Path '%HOSTS%' -Value $h -NoNewline"
ipconfig /flushdns >nul
schtasks /Delete /TN "FocusCafe Guard" /F >nul 2>&1
schtasks /Delete /TN "FocusCafe Guard Logon" /F >nul 2>&1
schtasks /Delete /TN "FocusCafe SiteBlocker" /F >nul 2>&1
schtasks /Create /TN "FocusCafe Guard" /SC MINUTE /MO 1 /TR "\"%ROOT%backend\venv\Scripts\pythonw.exe\" \"%ROOT%ensure_workers.py\"" /F >nul
echo 元に戻しました（見守りタスクは通常権限で残しています）。
pause
