@echo off
setlocal DisableDelayedExpansion
if "%~1"=="" (
    start "" "%~dp0VideoMate\VideoMate.exe"
    exit /b 0
)
if "%~1"=="--check" if "%~2"=="" goto check
if "%~1"=="--self-test" if not "%~2"=="" if "%~3"=="" goto test
if "%~1"=="--config" if not "%~2"=="" if "%~3"=="" goto config
echo Usage: start.bat [--check ^| --self-test NEW-REPORT.json ^| --config SETTINGS.json]
echo All desktop dependencies are included. Use the Python test kit for CLI commands.
exit /b 2
:check
start "" /wait "%~dp0VideoMate\VideoMate.exe" --check
if errorlevel 1 (
    echo VideoMate dependency check failed. Re-extract a complete package.
    exit /b 2
)
echo VideoMate desktop dependencies ready. Offline; no separate Python required.
exit /b 0
:test
start "" /wait "%~dp0VideoMate\VideoMate.exe" --self-test "%~2"
exit /b %errorlevel%
:config
start "" "%~dp0VideoMate\VideoMate.exe" --config "%~2"
exit /b 0
