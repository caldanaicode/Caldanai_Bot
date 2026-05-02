@echo off
REM ----------------------------------------------------------------------
REM vael_collect launcher — runs the Python collector inside the
REM project's venv. Designed for Windows Task Scheduler invocation:
REM
REM   Action:    Start a program
REM   Program:   E:\path\to\Caldanai_Bot\tools\vael_collect.bat
REM   Trigger:   Daily, repeat every 1 hour for indefinitely
REM   Settings:  "Run whether user is logged on or not" (optional)
REM
REM Resolves the project root from this script's own location
REM (%~dp0 is this script's directory, .. is the parent — i.e. the
REM project root). No hardcoded operator-specific paths; the .bat is
REM portable as long as the caller keeps it inside `tools/` and the
REM venv at `.venv314/` in the project root.
REM
REM Forwards any args through to the Python module, so:
REM   tools\vael_collect.bat            # one-shot collection
REM   tools\vael_collect.bat --show     # print tail of digest
REM   tools\vael_collect.bat --reset-cursor
REM ----------------------------------------------------------------------

setlocal

set PROJECT_ROOT=%~dp0..

REM cd into project root so .env (gitignored, holds BG_VAEL_DIR
REM among other tool-config env vars) loads from the expected place.
cd /d "%PROJECT_ROOT%"

"%PROJECT_ROOT%\.venv314\Scripts\python.exe" -m tools.vael_collect %*

endlocal
