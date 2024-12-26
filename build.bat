@echo off
setlocal EnableDelayedExpansion

:: Check if Python is installed
python --version > nul 2>&1
if errorlevel 1 (
    echo Python is not installed or not in PATH
    pause
    exit /b 1
)

:: Create and activate virtual environment
if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
)

:: Activate virtual environment
call venv\Scripts\activate.bat

:: Upgrade pip
python -m pip install --upgrade pip

:: Install requirements with --no-cache-dir to force fresh install
echo Installing required packages...
pip install --no-cache-dir -r requirements.txt
if errorlevel 1 (
    echo Failed to install requirements
    pause
    exit /b 1
)

:: Clean dist and build directories
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build

:: Build using spec file
echo Building application...
pyinstaller --clean --noconfirm RiceBagCounter.spec
if errorlevel 1 (
    echo Build failed
    pause
    exit /b 1
)

echo Build completed successfully!
echo The executable can be found in the dist/RiceBagCounter folder.

:: Copy additional files if needed
echo Copying additional files...
if exist additional_files (
    xcopy /E /I /Y additional_files dist\RiceBagCounter\additional_files
)

deactivate
pause