@echo off
rem ============================================
rem  Install Node.js LTS via winget (official)
rem  A UAC dialog will appear - please click "Yes".
rem ============================================
echo === Installing Node.js LTS via winget ===
winget install --id OpenJS.NodeJS.LTS -e --accept-source-agreements --accept-package-agreements
if errorlevel 1 (
  echo.
  echo [ERROR] winget install failed or was cancelled.
  pause
  exit /b 1
)
echo.
echo ============================================
echo  Node.js INSTALL COMPLETE!
echo ============================================
pause
