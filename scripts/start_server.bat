@echo off
REM THIRAMAI — bind all interfaces (LAN / Docker). Do not use 127.0.0.1 as host here.
cd /d "%~dp0.."
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m uvicorn main:app --host 0.0.0.0 --port 8000
) else (
  python -m uvicorn main:app --host 0.0.0.0 --port 8000
)
