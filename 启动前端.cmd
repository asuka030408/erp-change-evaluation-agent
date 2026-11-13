@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\erp-change.exe" (
  echo Please install the project first: .venv\Scripts\python.exe -m pip install -e .
  pause
  exit /b 1
)
set "ERP_KEY_FILE=%USERPROFILE%\Desktop\api key.txt"
if exist "%ERP_KEY_FILE%" (
  ".venv\Scripts\erp-change.exe" ui --key-file "%ERP_KEY_FILE%"
) else (
  ".venv\Scripts\erp-change.exe" ui --ask-api-key
)
pause
