@echo off
rem ============================================
rem  Focus & Cafe Roulette v2  -  SETUP
rem  Double-click this file. It will:
rem   1. Check Node.js
rem   2. Install frontend packages (npm install)
rem   3. Check Python
rem   4. Create venv + install backend packages
rem ============================================
cd /d "%~dp0"

echo === [1/4] Checking Node.js ===
node --version
if errorlevel 1 (
  echo.
  echo [ERROR] Node.js is not installed.
  echo A browser will open. Please download and install the "LTS" version.
  echo After installing, run this setup.bat again.
  start https://nodejs.org/
  pause
  exit /b 1
)

echo.
echo === [2/4] Installing frontend packages ^(npm install^) ===
cd frontend
call npm install
if errorlevel 1 (
  echo [ERROR] npm install failed. Please show this screen to Claude.
  pause
  exit /b 1
)
cd ..

echo.
echo === [3/4] Checking Python ===
python --version
if errorlevel 1 (
  echo [ERROR] Python not found. Please show this screen to Claude.
  pause
  exit /b 1
)

echo.
echo === [4/4] Creating venv and installing backend packages ===
cd backend
if not exist venv (
  python -m venv venv
)
venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] pip install failed. Please show this screen to Claude.
  pause
  exit /b 1
)

echo.
echo ============================================
echo  SETUP COMPLETE!  You can close this window.
echo ============================================
pause
