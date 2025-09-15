@echo off
echo Finding pipenv virtual environment...
pipenv --venv
echo.
echo Finding Python executable in pipenv...
pipenv run python -c "import sys; print('Python executable:', sys.executable)"
echo.
echo Copy the Python executable path above and use it in VS Code
pause