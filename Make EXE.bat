@echo off
setlocal
cd /d "%~dp0"

set "DEBUG_BUILD=0"
if /I "%~1"=="debug" set "DEBUG_BUILD=1"

echo Building ToolBar2...

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

if "%DEBUG_BUILD%"=="1" (
    set "ToolBar2_DEBUG=1"
    echo Debug console build enabled.
) else (
    set "ToolBar2_DEBUG="
)

python -m PyInstaller "ToolBar2.spec"
if errorlevel 1 (
    echo.
    echo Build failed.
    pause
    exit /b 1
)

echo.
echo Build complete: dist\ToolBar2.exe
echo User files were not removed: toolbar_config.json, toolbar_config.backup.json, user_profiles\
pause
