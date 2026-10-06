@echo off
setlocal DisableDelayedExpansion
rem Always resolve files relative to this launcher, not the caller's directory.
cd /d "%~dp0"
if not "%~1"=="" goto source
rem A source checkout must run its current code, even beside an older binary.
if exist "%~dp0src\videomate\gui.py" goto source
if exist "%~dp0VideoMate\VideoMate.exe" (
    start "" "%~dp0VideoMate\VideoMate.exe"
    exit /b 0
)
:source
if defined VIDEOMATE_PYTHON goto custom
if defined VIRTUAL_ENV if exist "%VIRTUAL_ENV%\Scripts\python.exe" goto venv
if defined CONDA_PREFIX if exist "%CONDA_PREFIX%\python.exe" goto conda
set "VIDEOMATE_PLATFORM=windows-x86_64"
if /I "%PROCESSOR_ARCHITECTURE%"=="ARM64" set "VIDEOMATE_PLATFORM=windows-arm64"
if /I "%PROCESSOR_ARCHITEW6432%"=="ARM64" set "VIDEOMATE_PLATFORM=windows-arm64"
if defined VIDEOMATE_RUNTIME_ROOT if exist "%VIDEOMATE_RUNTIME_ROOT%\%VIDEOMATE_PLATFORM%\python\python.exe" goto overriddenruntime
if exist "%~dp0dependencies\python\%VIDEOMATE_PLATFORM%\python\python.exe" goto localpython
py -3.13 -I -c "import sys,struct;sys.exit(not(sys.version_info >= (3,11) and struct.calcsize('P') == 8))" >nul 2>&1
if not errorlevel 1 goto py313
py -3.12 -I -c "import sys,struct;sys.exit(not(sys.version_info >= (3,11) and struct.calcsize('P') == 8))" >nul 2>&1
if not errorlevel 1 goto py312
py -3.11 -I -c "import sys,struct;sys.exit(not(sys.version_info >= (3,11) and struct.calcsize('P') == 8))" >nul 2>&1
if not errorlevel 1 goto py311
python -I -c "import sys,struct;sys.exit(not(sys.version_info >= (3,11) and struct.calcsize('P') == 8))" >nul 2>&1
if not errorlevel 1 goto python
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -File "%~dp0tools\bootstrap_runtime.ps1" %*
if errorlevel 1 (
    if "%~1"=="" pause
    exit /b 2
)
if defined VIDEOMATE_RUNTIME_ROOT goto overriddenruntime
goto localpython
:custom
"%VIDEOMATE_PYTHON%" -I -X utf8 "%~dp0tools\bootstrap.py" %*
exit /b %errorlevel%
:venv
set "VIDEOMATE_PYTHON=%VIRTUAL_ENV%\Scripts\python.exe"
goto custom
:conda
set "VIDEOMATE_PYTHON=%CONDA_PREFIX%\python.exe"
goto custom
:overriddenruntime
"%VIDEOMATE_RUNTIME_ROOT%\%VIDEOMATE_PLATFORM%\python\python.exe" -I -X utf8 "%~dp0tools\bootstrap.py" %*
exit /b %errorlevel%
:localpython
"%~dp0dependencies\python\%VIDEOMATE_PLATFORM%\python\python.exe" -I -X utf8 "%~dp0tools\bootstrap.py" %*
exit /b %errorlevel%
:py313
py -3.13 -I -X utf8 "%~dp0tools\bootstrap.py" %*
exit /b %errorlevel%
:py312
py -3.12 -I -X utf8 "%~dp0tools\bootstrap.py" %*
exit /b %errorlevel%
:py311
py -3.11 -I -X utf8 "%~dp0tools\bootstrap.py" %*
exit /b %errorlevel%
:python
python -I -X utf8 "%~dp0tools\bootstrap.py" %*
exit /b %errorlevel%
