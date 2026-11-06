@echo off
rem This file lives in scripts\. ROOT = the app folder (one level up).
for %%I in ("%~dp0..") do set "ROOT=%%~fI\"
chcp 65001 >nul
rem Register the guard task "FocusCafe Guard" (every minute + at logon). Run once.
set "TASK=FocusCafe Guard"
schtasks /Query /TN "%TASK%" >nul 2>&1
if not errorlevel 1 (
  echo すでに登録されています。更新します...
  schtasks /Delete /TN "%TASK%" /F >nul
)
schtasks /Create /TN "%TASK%" /SC MINUTE /MO 1 /TR "\"%ROOT%backend\venv\Scripts\pythonw.exe\" \"%ROOT%ensure_workers.py\"" /F
if errorlevel 1 (
  echo [ERROR] 登録に失敗しました。この画面を Claude に見せてください。
  pause
  exit /b 1
)
schtasks /Create /TN "%TASK% Logon" /SC ONLOGON /TR "\"%ROOT%backend\venv\Scripts\pythonw.exe\" \"%ROOT%ensure_workers.py\"" /F >nul
start "" "%ROOT%backend\venv\Scripts\pythonw.exe" "%ROOT%ensure_workers.py"
echo 登録しました。制限ワーカーは止めても1分以内に復活します。
pause
