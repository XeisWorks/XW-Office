@echo off
setlocal

set "ROOT=%~dp0"
set "VENV_PY=%ROOT%.venv\Scripts\python.exe"
set "ENTRYPOINT=-m xw_studio"
set "PY_EXE="
set "PY_ARGS="

if exist "%VENV_PY%" (
    set "PY_EXE=%VENV_PY%"
) else (
    call :try_candidate "python" ""
    if "%PY_EXE%"=="" call :try_candidate "py" "-3.14"
    if "%PY_EXE%"=="" call :try_candidate "py" "-3.13"
    if "%PY_EXE%"=="" call :try_candidate "py" "-3.12"
    if "%PY_EXE%"=="" call :try_candidate "py" "-3.11"
    if "%PY_EXE%"=="" call :try_candidate "py" ""
)

if "%PY_EXE%"=="" (
    echo [XW-Studio] Kein Python-Interpreter gefunden.
    echo.
    echo Erwarte entweder:
    echo   1^) "%VENV_PY%" oder
    echo   2^) Einen lauffaehigen Python-Interpreter im PATH.
    echo.
    echo Tipp: py -0p zeigt verfuegbare Installationen.
    pause
    exit /b 1
)

pushd "%ROOT%"

rem Support src-layout start without requiring editable install.
set "PYTHONPATH=%ROOT%src;%PYTHONPATH%"
call "%PY_EXE%" %PY_ARGS% %ENTRYPOINT%
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [XW-Studio] Start fehlgeschlagen mit Exit-Code %EXIT_CODE%.
    echo Falls Module fehlen, installiere Abhaengigkeiten im venv:
    echo   python -m venv .venv
    echo   .venv\Scripts\python -m pip install -e ".[dev]"
    pause
)

popd
exit /b %EXIT_CODE%

:try_candidate
set "CAND_EXE=%~1"
set "CAND_ARGS=%~2"

if "%CAND_ARGS%"=="" (
    call "%CAND_EXE%" -c "import sys" >nul 2>&1
) else (
    call "%CAND_EXE%" %CAND_ARGS% -c "import sys" >nul 2>&1
)

if errorlevel 1 goto :eof

set "PY_EXE=%CAND_EXE%"
set "PY_ARGS=%CAND_ARGS%"
goto :eof
