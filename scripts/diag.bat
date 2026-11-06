@echo off
rem This file lives in scripts\. ROOT = the app folder (one level up).
for %%I in ("%~dp0..") do set "ROOT=%%~fI\"
rem Diagnostics -> logs\diag_out.txt (the real work is diag.py)
"%ROOT%backend\venv\Scripts\python.exe" "%ROOT%diag.py"
echo written: logs\diag_out.txt
