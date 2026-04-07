@echo off
REM THIRAMAI Genesis — start API without needing `uvicorn` on PATH (uses: python run.py).
REM WRONG: python -m main.py  |  bare: uvicorn main:app
cd /d "%~dp0"
echo.
echo  [THIRAMAI] Starting API (prefers .venv\Scripts\python.exe if present)
echo  Do NOT use: python -m main.py
echo.
set THIRAMAI_UVICORN_RELOAD=1
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" run.py
) else (
  python run.py
)
if errorlevel 1 pause
