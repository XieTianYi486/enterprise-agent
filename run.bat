@echo off
cd /d "%~dp0"
setlocal

echo ==============================================
echo    Enterprise Office Agent - Launcher
echo ==============================================
echo.

REM ---- 1. Virtual env ----
if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Creating virtualenv .venv ...
    py -3.12 -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create venv. Please install Python 3.12 first.
        pause
        exit /b 1
    )
)

set "PY=.venv\Scripts\python.exe"

REM ---- 2. Install dependencies ----
echo [2/3] Installing / checking dependencies ...
"%PY%" -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
    echo [ERROR] Dependency install failed. Please check network and retry.
    pause
    exit /b 1
)

REM ---- 3. Start server & open chat page ----
echo [3/3] Starting server on http://127.0.0.1:8002 ...
start "Enterprise-Agent Server" "%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port 8002

REM wait ~3s for server to boot, then open the chat page
ping -n 4 127.0.0.1 >nul
start "" http://127.0.0.1:8002/

echo.
echo Chat page   : http://127.0.0.1:8002/
echo API docs    : http://127.0.0.1:8002/docs
echo Demo account: demo / demo123456
echo.
echo Close the "Enterprise-Agent Server" window to stop the service.
pause