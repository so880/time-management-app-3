@echo off
rem This file lives in scripts\. ROOT = the app folder (one level up).
for %%I in ("%~dp0..") do set "ROOT=%%~fI\"
chcp 65001 >nul
rem ==================================================================
rem  Focus & Cafe v2 - automatic environment setup (new PC / third party)
rem  Just double-click. It installs what is needed, in order.
rem   [1] Python 3.12   (winget. Click Yes on the UAC dialog)
rem   [2] Node.js LTS   (winget)
rem   [3] Google Chrome (winget. Skipped if already installed)
rem   [4] backend venv + pip install (requirements.txt)
rem   [5] PySide6 / psutil for the system Python (quick widget)
rem   [6] frontend npm install
rem   [7] check (pytest)
rem  If something fails, show the window to Claude.
rem  Requirements: docs/REQUIREMENTS.md
rem ==================================================================
cd /d "%ROOT%"
set "FAIL="

echo.
echo ===== [0/7] winget（Windows 標準のインストーラー）の確認 =====
winget --version >nul 2>&1
if errorlevel 1 (
  echo [ERROR] winget が見つかりません。Windows 10 1809 以降 / Windows 11 で、
  echo         Microsoft Store の「アプリ インストーラー」を更新してから再実行してください。
  echo         https://apps.microsoft.com/detail/9NBLGGH4NNS1
  pause
  exit /b 1
)

echo.
echo ===== [1/7] Python 3.12 =====
py -3.12 --version >nul 2>&1
if errorlevel 1 (
  echo Python 3.12 を入れます（UAC が出たら「はい」）...
  winget install --id Python.Python.3.12 -e --scope user --accept-source-agreements --accept-package-agreements
  if errorlevel 1 (
    echo [ERROR] Python のインストールに失敗しました。
    set "FAIL=1"
  )
) else (
  echo Python 3.12 は入っています。
)

echo.
echo ===== [2/7] Node.js LTS =====
node --version >nul 2>&1
if errorlevel 1 (
  echo Node.js を入れます...
  winget install --id OpenJS.NodeJS.LTS -e --accept-source-agreements --accept-package-agreements
  if errorlevel 1 (
    echo [ERROR] Node.js のインストールに失敗しました。
    set "FAIL=1"
  )
) else (
  echo Node.js は入っています。
)

echo.
echo ===== [3/7] Google Chrome =====
set "CHROME_FOUND="
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "CHROME_FOUND=1"
set "PF86=%ProgramFiles(x86)%"
if exist "%PF86%\Google\Chrome\Application\chrome.exe" set "CHROME_FOUND=1"
if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" set "CHROME_FOUND=1"
if defined CHROME_FOUND (
  echo Chrome は入っています。
) else (
  echo Chrome を入れます...
  winget install --id Google.Chrome -e --accept-source-agreements --accept-package-agreements
  if errorlevel 1 echo [WARN] Chrome のインストールに失敗しました（他のブラウザでも動きます）。
)

if defined FAIL (
  echo.
  echo [ERROR] 必須ソフトの導入に失敗したため中断します。上のエラーを Claude に見せてください。
  pause
  exit /b 1
)

rem PATH is not refreshed in this window right after winget, so run the rest in a new cmd
echo.
echo ===== 続きは新しいウィンドウで実行します（PATH を反映するため） =====
start "Focus&Cafe setup (2/2)" cmd /k "%~dp0setup_env_part2.bat"
exit /b 0
