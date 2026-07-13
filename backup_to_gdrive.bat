@echo off
rem Sync this folder (latest app) to Google Drive. Double-click anytime.
if not exist "%~dp0backend\venv\Scripts\python.exe" (
  echo ============================================================
  echo  ERROR: venv not found.
  echo  You are probably running the BACKUP COPY on Google Drive.
  echo  Please run the one in the LOCAL folder on the C: drive.
  echo  ^(C drive ^> "atarashii folder" / C:\...\backup_to_gdrive.bat^)
  echo ============================================================
  pause
  exit /b 1
)
"%~dp0backend\venv\Scripts\python.exe" "%~dp0backup_to_gdrive.py"
pause
