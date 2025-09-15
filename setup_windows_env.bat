@echo off
echo Setting up Windows Python virtual environment for VS Code testing...
echo.

REM Check if python is available
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Python is not installed or not in PATH. Please install Python first.
    pause
    exit /b 1
)

REM Create virtual environment
echo Creating virtual environment...
python -m venv venv

REM Activate and install dependencies
echo Activating environment and installing dependencies...
call venv\Scripts\activate.bat
pip install --upgrade pip
pip install pipenv

REM Install from Pipfile
pipenv install --dev

echo.
echo Virtual environment created successfully!
echo.
echo To use in VS Code:
echo 1. Press Ctrl+Shift+P
echo 2. Type "Python: Select Interpreter"
echo 3. Choose: %cd%\venv\Scripts\python.exe
echo.
pause