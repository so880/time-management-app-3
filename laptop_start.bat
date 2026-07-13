@echo off
rem ============================================================
rem  LAPTOP LAUNCHER - run this file FROM GOOGLE DRIVE.
rem   1. Copies the latest app code from Google Drive to C:\Life_app
rem      (the record DB is not copied here; start_all.bat will ask
rem       "pull newer DB? [y/N]" as usual)
rem   2. First run only: installs packages automatically (setup.bat)
rem   3. Starts the app (start_all.bat)
rem  On the desktop PC this file does nothing special - it just
rem  starts the app if you run the local copy directly.
rem ============================================================
set "SRC=%~dp0"
set "DST=C:\Life_app"

if /i "%SRC%"=="%DST%\" (
  echo This is the local copy. Starting the app...
  call "%DST%\start_all.bat"
  exit /b
)

echo Copying latest code from Google Drive to %DST% ...
robocopy "%SRC%." "%DST%" /E /XD node_modules venv __pycache__ .pytest_cache data /XF *.db *.db.bak >nul
if errorlevel 8 (
  echo ERROR: copy failed. Please show this screen to Claude.
  pause
  exit /b 1
)

if not exist "%DST%\backend\venv\Scripts\python.exe" (
  echo First run on this PC: installing packages. This takes a few minutes...
  call "%DST%\setup.bat"
)
if not exist "%DST%\frontend\node_modules" (
  echo Installing frontend packages...
  pushd "%DST%\frontend"
  call npm install
  popd
)

start "" "%DST%\start_all.bat"
exit /b
