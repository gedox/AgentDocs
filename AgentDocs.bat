@echo off
title AgentDocs
cd /d "%~dp0"

REM Start the local UI server; it opens your browser automatically.
python -m agentdocs.ui
set EXITCODE=%ERRORLEVEL%

if not "%EXITCODE%"=="0" (
    echo.
    echo ---------------------------------------------------------------
    echo  AgentDocs could not start ^(exit code %EXITCODE%^).
    echo  If this is the first run, install the dependencies:
    echo.
    echo      python -m pip install -r requirements.txt
    echo ---------------------------------------------------------------
    echo.
    pause
)
