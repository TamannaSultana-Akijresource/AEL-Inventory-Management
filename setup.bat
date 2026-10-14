@echo off
REM =====================================================================
REM  AEL dashboard - one-time setup
REM  Creates a private Python environment, installs the packages, and
REM  connects this folder to your GitHub repository.
REM =====================================================================
setlocal
cd /d "%~dp0"

echo ============================================================
echo   AEL dashboard - setup
echo ============================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [X] Python was not found on PATH. Install Python 3.10+ first.
  echo     https://www.python.org/downloads/
  goto :end
)

if not exist ".venv" (
  echo [1/4] Creating virtual environment (.venv)...
  python -m venv .venv
) else (
  echo [1/4] Virtual environment already exists.
)

echo [2/4] Installing requirements...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt

echo [3/4] Initialising git repository...
if not exist ".git" git init
git branch -M main

echo [4/4] Setting GitHub remote...
git remote remove origin 2>nul
git remote add origin https://github.com/TamannaSultana-Akijresource/AEL-Inventory-Management.git

echo.
echo ------------------------------------------------------------
echo  Setup complete.
echo.
echo  Next:
echo    * Put your database credentials in .streamlit\secrets.toml
echo    * Double-click run_daily.bat
echo      (the first push will ask you to sign in to GitHub once)
echo ------------------------------------------------------------
:end
echo.
pause
endlocal
