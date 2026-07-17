@echo off
setlocal
title ClipperCS2 - 1-Click All-in-One Installer & Launcher

echo ================================================================
echo   🎬 ClipperCS2 - 1-Click All-in-One Installer & Launcher
echo ================================================================
echo.

:: 1. Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    py --version >nul 2>&1
    if %errorlevel% neq 0 (
        echo [ERROR] Python is not installed or not added to your PATH!
        echo.
        echo Please install Python 3.10+ from python.org and make sure to check
        echo the box: [x] "Add Python to PATH" at the bottom of the installer!
        echo.
        echo Opening official Python download page now...
        start https://www.python.org/downloads/windows/
        pause
        exit /b 1
    ) else (
        set PYTHON_CMD=py
    )
) else (
    set PYTHON_CMD=python
)

echo [1/4] Python detected successfully (%PYTHON_CMD%).
echo [2/4] Checking local Python virtual environment (.venv)...
if not exist ".venv" (
    echo       Creating clean isolated virtual environment (.venv)...
    %PYTHON_CMD% -m venv .venv
)

echo [3/4] Installing / verifying dependencies from requirements.txt...
echo       (Downloading demoparser2, pywebview, fastapi, uvicorn, scikit-learn...)
.venv\Scripts\python.exe -m pip install --upgrade pip >nul 2>&1
.venv\Scripts\pip.exe install -r requirements.txt

if %errorlevel% neq 0 (
    echo [ERROR] Dependency installation encountered an issue. Please check network/permissions.
    pause
    exit /b 1
)

echo [4/4] Creating Windows Desktop Shortcut (ClipperCS2.lnk)...
set SCRIPT_DIR=%~dp0
set SHORTCUT_VBS=%TEMP%\create_clipper_shortcut.vbs

echo Set oWS = WScript.CreateObject("WScript.Shell") > "%SHORTCUT_VBS%"
echo sLinkFile = oWS.SpecialFolders("Desktop") ^& "\ClipperCS2.lnk" >> "%SHORTCUT_VBS%"
echo Set oLink = oWS.CreateShortcut(sLinkFile) >> "%SHORTCUT_VBS%"
echo oLink.TargetPath = "%SCRIPT_DIR%Launch_ClipperCS2_Silent.vbs" >> "%SHORTCUT_VBS%"
echo oLink.WorkingDirectory = "%SCRIPT_DIR%" >> "%SHORTCUT_VBS%"
echo oLink.Description = "ClipperCS2 Autonomous Highlight Engine" >> "%SHORTCUT_VBS%"
echo oLink.IconLocation = "%SCRIPT_DIR%.venv\Scripts\python.exe,0" >> "%SHORTCUT_VBS%"
echo oLink.Save >> "%SHORTCUT_VBS%"

cscript /nologo "%SHORTCUT_VBS%"
del "%SHORTCUT_VBS%" >nul 2>&1

echo.
echo ================================================================
echo   🎉 Installation Complete!
echo   A shortcut "ClipperCS2" has been added to your Windows Desktop.
echo   Launching standalone native desktop application right now...
echo ================================================================
echo.

:: Launch silent vbs wrapper inside isolated virtual environment
start "" /B wscript.exe "%SCRIPT_DIR%Launch_ClipperCS2_Silent.vbs"
exit /b 0
