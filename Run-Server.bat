@echo off
REM THIRAMAI Genesis — double-click this OR run: Run-Server.bat
REM WRONG (will error): python -m main.py   |   uvicorn main:app
REM RIGHT:              python main.py      |   python -m uvicorn main:app
cd /d "%~dp0"
echo.
echo  [THIRAMAI] Starting API with: python main.py
echo  Do NOT use: python -m main.py
echo.
set THIRAMAI_UVICORN_RELOAD=1
python main.py
if errorlevel 1 pause
