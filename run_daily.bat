@echo off
REM =====================================================================
REM  AEL dashboard - daily button
REM  Double-click this file (or schedule it) to:
REM    1. read the DWH
REM    2. rebuild index.html
REM    3. push it to GitHub (your Pages link updates automatically)
REM =====================================================================
setlocal
cd /d "%~dp0"

set "PYEXE=%~dp0.venv\Scripts\python.exe"
if not exist "%PYEXE%" set "PYEXE=python"

echo ============================================================
echo   AEL - MTD Order Fulfilment ^& Stock Coverage
echo   Rebuilding dashboard and publishing to GitHub...
echo ============================================================
echo.

"%PYEXE%" generate_dashboard.py --push
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" (
  echo [AEL] Finished with exit code %RC%.
  echo [AEL] See the "logs" folder for details. Common causes:
  echo        - database credentials not reachable
  echo        - GitHub not authenticated yet ^(run setup.bat once^)
) else (
  echo [AEL] Done. index.html was rebuilt and pushed to GitHub.
)

echo.
pause
endlocal
