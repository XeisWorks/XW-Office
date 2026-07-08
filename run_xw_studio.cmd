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
    where py >nul 2>&1
    if not errorlevel 1 (
        set "PY_EXE=py"
        set "PY_ARGS=-3.11"
    ) else (
        where python >nul 2>&1
        if not errorlevel 1 (
            set "PY_EXE=python"
        )
    )
)

if "%PY_EXE%"=="" (
    echo [XW-Studio] Kein Python-Interpreter gefunden.
    echo.
    echo Erwarte entweder:
    echo   1^) "%VENV_PY%" oder
    echo   2^) Python Launcher ^(py^) oder python im PATH.
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
