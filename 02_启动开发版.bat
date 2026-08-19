@echo off
chcp 65001 >nul
setlocal
set "ROOT=%~dp0"
set "PATH=C:\Program Files\nodejs;%PATH%"
set "PYTHON_EXE=%ROOT%.venv-local\Scripts\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=%ROOT%.venv\Scripts\python.exe"
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\doctor.ps1"
if errorlevel 1 goto :environment_error
set "BACKEND_RUNNING=0"
netstat -ano | findstr /R /C:":8014 .*LISTENING" >nul
if errorlevel 1 goto :start_backend
powershell -NoProfile -Command "try { $r=Invoke-WebRequest 'http://127.0.0.1:8014/api/news/sources' -UseBasicParsing; if($r.StatusCode -eq 200 -and $r.Content.Contains('PUBLIC_RSS')){exit 0}; exit 1 } catch {exit 1}"
if errorlevel 1 goto :stale_backend_error
set "BACKEND_RUNNING=1"
:start_backend
if "%BACKEND_RUNNING%"=="1" goto :start_frontend
start "DELTA Backend" /D "%ROOT%backend" "%PYTHON_EXE%" -m uvicorn app.main:app --host 127.0.0.1 --port 8014 --reload
:start_frontend
netstat -ano | findstr /R /C:":5184 .*LISTENING" >nul
if not errorlevel 1 goto :open_terminal
start "DELTA Frontend" /D "%ROOT%frontend" "C:\Program Files\nodejs\npm.cmd" run dev -- --host 127.0.0.1 --port 5184
timeout /t 3 /nobreak >nul
:open_terminal
start "" http://127.0.0.1:5184
echo DELTA development terminal is ready.
if not defined DELTA_NO_PAUSE pause
exit /b 0
:environment_error
echo Environment check failed.
if not defined DELTA_NO_PAUSE pause
exit /b 1
:stale_backend_error
echo Error: port 8014 is running an old or unrelated backend instance.
echo Close the existing DELTA Backend terminal, then run this launcher again.
if not defined DELTA_NO_PAUSE pause
exit /b 1
