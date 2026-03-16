@echo off
setlocal enabledelayedexpansion

:: Set Python 3.12 path
set PYTHON312_PATH=C:\Users\home\AppData\Local\Programs\Python\Python312
set PYTHON_EXE=%PYTHON312_PATH%\python.exe

:: Check if Python 3.12 is installed
if not exist "%PYTHON_EXE%" (
    echo Python 3.12 is not found at %PYTHON_EXE%
    echo Please install Python 3.12 or update the path in this script.
    exit /b 1
)

echo Using Python 3.12 from: %PYTHON_EXE%

:: Install build dependencies if needed
echo Installing build dependencies...
"%PYTHON_EXE%" -m pip install -r requirements-build.txt
if %ERRORLEVEL% neq 0 (
    echo Failed to install dependencies.
    exit /b 1
)

:: Build the application
echo Building the application...
"%PYTHON_EXE%" build.py --onefile
if %ERRORLEVEL% neq 0 (
    echo Build failed.
    exit /b 1
)

echo.
echo Build completed successfully!
echo The executable can be found in the 'dist' folder.
echo.
