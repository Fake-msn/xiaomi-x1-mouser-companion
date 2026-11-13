@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>&1
if errorlevel 1 (
  echo [X1 Companion] Python 3.10+ was not found in PATH.
  echo Install Python and try again, or run: python main.py
  exit /b 1
)
python main.py %*
endlocal
