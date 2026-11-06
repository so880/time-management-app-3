@echo off
rem This file lives in scripts\. ROOT = the app folder (one level up).
for %%I in ("%~dp0..") do set "ROOT=%%~fI\"
chcp 65001 >nul
rem  Second half of setup_env.bat (runs in a new window where Python / Node are on PATH)
cd /d "%ROOT%"

echo ===== [4/7] backend: venv 作成 + pip install =====
cd backend
if not exist venv (
  py -3.12 -m venv venv
  if errorlevel 1 (
    python -m venv venv
  )
)
if not exist venv\Scripts\python.exe (
  echo [ERROR] venv を作れませんでした。Python が PATH にあるか確認してください（python --version）。
  pause
  exit /b 1
)
venv\Scripts\python.exe -m pip install --upgrade pip
venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] pip install に失敗しました。
  pause
  exit /b 1
)
cd ..

echo.
echo ===== [5/7] システム Python に PySide6 / psutil（小窓・常駐用） =====
py -3.12 -m pip install --upgrade PySide6 psutil
if errorlevel 1 (
  python -m pip install --upgrade PySide6 psutil
  if errorlevel 1 (
    echo [ERROR] PySide6 の導入に失敗しました。
    pause
    exit /b 1
  )
)

echo.
echo ===== [6/7] frontend: npm install =====
cd frontend
call npm install
if errorlevel 1 (
  echo [ERROR] npm install に失敗しました。
  pause
  exit /b 1
)
cd ..

echo.
echo ===== [7/7] 動作チェック（pytest） =====
backend\venv\Scripts\python.exe -m pytest -q backend\tests
if errorlevel 1 (
  echo [WARN] テストが失敗しました。起動はできる場合があります。画面を Claude に見せてください。
)

echo.
echo ==================================================================
echo  セットアップ完了。次は start_all.bat をダブルクリックしてください。
echo  Google 連携（任意）は docs/SETUP_GOOGLE_SYNC.md、
echo  AI プラン（任意）は マネー › 🤖 AI判定の設定 に Gemini のキーを入れてください。
echo ==================================================================
pause
