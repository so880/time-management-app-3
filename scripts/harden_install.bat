@echo off
rem This file lives in scripts\. ROOT = the app folder (one level up).
for %%I in ("%~dp0..") do set "ROOT=%%~fI\"
chcp 65001 >nul
rem Harden the lock: SYSTEM guard task, read-only lock files (ACL), hosts blocking. Run as admin (UAC once).
rem Undo: harden_uninstall.bat (refuses while locked).
net session >nul 2>&1
if errorlevel 1 (
  echo 管理者として実行し直します（UAC が出たら「はい」）...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
cd /d "%ROOT%"
set "ME=%USERNAME%"

echo [1/3] 見守りタスクを SYSTEM 権限で登録...
schtasks /Delete /TN "FocusCafe Guard" /F >nul 2>&1
schtasks /Delete /TN "FocusCafe Guard Logon" /F >nul 2>&1
schtasks /Create /TN "FocusCafe Guard" /SC MINUTE /MO 1 /TR "\"%ROOT%backend\venv\Scripts\pythonw.exe\" \"%ROOT%ensure_workers.py\"" /RU SYSTEM /RL HIGHEST /F
if errorlevel 1 goto :fail
schtasks /Create /TN "FocusCafe Guard Logon" /SC ONLOGON /TR "\"%ROOT%backend\venv\Scripts\pythonw.exe\" \"%ROOT%ensure_workers.py\"" /RU SYSTEM /RL HIGHEST /F >nul
schtasks /Create /TN "FocusCafe SiteBlocker" /SC ONLOGON /TR "\"%ROOT%backend\venv\Scripts\pythonw.exe\" \"%ROOT%site_blocker.py\"" /F >nul


echo [2/3] 制限関連ファイルを書き込み禁止に（%ME% の変更・削除を拒否）...
for %%F in (blocker.py site_blocker.py stop_guard.py ensure_workers.py appctl.py launcher.py scripts\harden_install.bat scripts\harden_uninstall.bat) do (
  icacls "%ROOT%%%F" /inheritance:r /grant:r "SYSTEM:(F)" "Administrators:(F)" "%ME%:(RX)" >nul
  if errorlevel 1 echo [WARN] %%F の権限設定に失敗しました
)
for %%F in (backend\app\gate_api.py backend\app\logic.py backend\app\policy.py backend\app\todo_api.py) do (
  icacls "%ROOT%%%F" /inheritance:r /grant:r "SYSTEM:(F)" "Administrators:(F)" "%ME%:(RX)" >nul
  if errorlevel 1 echo [WARN] %%F の権限設定に失敗しました
)

echo [3/3] hosts でドメインを遮断...
set "HOSTS=%SystemRoot%\System32\drivers\etc\hosts"
findstr /C:"# FocusCafe-block" "%HOSTS%" >nul 2>&1
if not errorlevel 1 (
  echo   すでに設定済みです。
) else (
  copy /y "%HOSTS%" "%HOSTS%.focuscafe.bak" >nul
  (
    echo.
    echo # FocusCafe-block begin
    for %%D in (youtube.com www.youtube.com m.youtube.com music.youtube.com youtu.be primevideo.com www.primevideo.com store.steampowered.com steamcommunity.com www.twitch.tv twitch.tv www.tiktok.com tiktok.com abema.tv www.nicovideo.jp nicovideo.jp) do (
      echo 0.0.0.0 %%D
      echo :: %%D
    )
    echo # FocusCafe-block end  # FocusCafe-block
  ) >> "%HOSTS%"
  ipconfig /flushdns >nul
)
echo.
echo 完了しました。見守りタスクの削除・制限ファイルの変更・hosts の変更には、以後 UAC（管理者）が必要です。
pause
exit /b 0

:fail
echo [ERROR] 失敗しました。この画面を Claude に見せてください。
pause
exit /b 1
