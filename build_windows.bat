@echo off
setlocal enabledelayedexpansion

:: Check if Python is installed
where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo Python is not installed or not in PATH. Please install Python 3.8 or later.
    exit /b 1
)

:: Capture commit date for version metadata
where git >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo Git is not installed or not in PATH. Please install Git to stamp version metadata.
    exit /b 1
)

for /f %%i in ('git log -1 --format=%%cs') do set VERSION_DATE=%%i
if "%VERSION_DATE%"=="" (
    echo Failed to read commit date from Git.
    exit /b 1
)

python -c "import json, pathlib; pathlib.Path('app/resources/version.json').write_text(json.dumps({'date': '%VERSION_DATE%'}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')"
if %ERRORLEVEL% neq 0 (
    echo Failed to write version metadata.
    exit /b 1
)

:: Create virtual environment if it doesn't exist
if not exist "venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv venv
    if %ERRORLEVEL% neq 0 (
        echo Failed to create virtual environment.
        exit /b 1
    )
    
    :: Activate the virtual environment and install dependencies
    call venv\Scripts\activate
    if %ERRORLEVEL% neq 0 (
        echo Failed to activate virtual environment.
        exit /b 1
    )
    
    echo Installing build dependencies...
    python -m pip install --upgrade pip
    pip install -r requirements-build.txt
    if %ERRORLEVEL% neq 0 (
        echo Failed to install dependencies.
        exit /b 1
    )
) else (
    echo Using existing virtual environment
    call venv\Scripts\activate
)

:: Build the application
echo Building the application...
python build.py --onefile
if %ERRORLEVEL% neq 0 (
    echo Build failed.
    exit /b 1
)

echo.
echo Build completed successfully!
echo The executable can be found in the 'dist' folder.
echo.
