@echo off
title ClipperCS2 - Local Desktop Application Launcher
cd /d "%~dp0"

echo Launching ClipperCS2 Desktop Application...
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m src.desktop_app
) else (
    python -m src.desktop_app
)
if %errorlevel% neq 0 (
    echo [WARNING] App exited with code %errorlevel%. If dependencies are missing, run Install_and_Run.bat first!
    pause
)
