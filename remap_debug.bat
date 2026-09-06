@echo off
setlocal enabledelayedexpansion

where pythonw >nul 2>&1
if errorlevel 1 (
    echo 'pythonw' is not recognized as a command. Make sure python is installed.
    pause
    exit /b 1
)

set PACKAGES=keyboard, mouse, imgui_bundle
python -c "import %PACKAGES%" >nul 2>&1
if errorlevel 1 (
    for %%P in (%PACKAGES%) do (
        python -c "import %%P" >nul 2>&1
        if errorlevel 1 (
            echo Python package "%%P" is not installed. Please run "pip install %%P".
            pause
            exit /b 1
        )
    )
)

python remap.py
pause
